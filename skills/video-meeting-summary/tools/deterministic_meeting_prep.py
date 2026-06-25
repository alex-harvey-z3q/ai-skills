#!/usr/bin/env python3
"""Deterministic meeting preprocessing.

- Extract frames from a video with ffmpeg.
- Parse transcript turns from docx/txt/md/vtt.
- Align turns to frames by timestamp.
- Generate deterministic Markdown and machine-readable artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "if", "in", "is", "it", "its",
    "me", "my", "no", "not", "of", "on", "or", "our", "she", "so", "that",
    "the", "their", "them", "there", "they", "this", "to", "us", "was", "we",
    "were", "what", "when", "where", "which", "who", "will", "with", "you",
    "your", "yeah", "okay", "um", "uh", "like", "just", "can", "could", "should",
}

ACTION_PATTERNS = [
    re.compile(r"\bneed to\b", re.IGNORECASE),
    re.compile(r"\bwe will\b", re.IGNORECASE),
    re.compile(r"\baction\b", re.IGNORECASE),
    re.compile(r"\bfollow up\b", re.IGNORECASE),
    re.compile(r"\bnext step\b", re.IGNORECASE),
    re.compile(r"\bto do\b", re.IGNORECASE),
    re.compile(r"\btodo\b", re.IGNORECASE),
]

TURN_LINE_RE = re.compile(
    r"^(?P<speaker>.+?)\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<text>.*)$"
)


@dataclass
class Turn:
    index: int
    speaker: str
    time_label: str
    time_sec: int
    text: str
    frame_index: int = 1
    frame_file: str = ""


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for deterministic meeting pre-processing."""
    parser = argparse.ArgumentParser(description="Deterministic meeting preprocessor")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--transcript", required=True, help="Path to transcript file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--frame-interval-sec",
        type=float,
        default=5.0,
        help="Seconds between extracted frames (default: 5)",
    )
    parser.add_argument(
        "--max-keywords",
        type=int,
        default=8,
        help="Top keywords per timeline bucket (default: 8)",
    )
    parser.add_argument(
        "--timeline-bucket-sec",
        type=int,
        default=300,
        help="Bucket size in seconds for timeline grouping (default: 300)",
    )
    return parser.parse_args()


def run_cmd(cmd: List[str]) -> str:
    """Run a shell command and return stdout, raising on failure."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nstdout:\n"
            + proc.stdout
            + "\n\nstderr:\n"
            + proc.stderr
        )
    return proc.stdout.strip()


def ffprobe_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    out = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    return float(out)


def extract_frames(video_path: Path, frames_dir: Path, interval_sec: float) -> int:
    """Extract PNG frames at a fixed interval and return frame count."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    out_pattern = str(frames_dir / "frame_%06d.png")
    fps_filter = f"fps=1/{interval_sec:g}"

    run_cmd(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            fps_filter,
            out_pattern,
        ]
    )

    return len(list(frames_dir.glob("frame_*.png")))


def read_docx_text(path: Path) -> List[str]:
    """Read non-empty paragraph text lines from a .docx transcript."""
    lines: List[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        xml_content = zf.read("word/document.xml")
    root = ET.fromstring(xml_content)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for para in root.findall(".//w:p", ns):
        text = "".join(t.text for t in para.findall(".//w:t", ns) if t.text)
        text = text.strip()
        if text:
            lines.append(text)
    return lines


def read_vtt_text(path: Path) -> List[str]:
    """Read spoken lines from a .vtt transcript, skipping cue metadata."""
    lines: List[str] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "WEBVTT":
            continue
        if "-->" in line:
            continue
        if line.isdigit():
            continue
        lines.append(line)
    return lines


def read_transcript_lines(path: Path) -> List[str]:
    """Load transcript lines from supported file formats."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx_text(path)
    if suffix == ".vtt":
        return read_vtt_text(path)
    if suffix in {".txt", ".md", ".log"}:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
    raise ValueError(f"Unsupported transcript extension: {suffix}")


def parse_timestamp(value: str) -> int:
    """Convert MM:SS or HH:MM:SS text to total seconds."""
    parts = [int(p) for p in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported timestamp format: {value}")


def looks_like_metadata(line: str) -> bool:
    """Heuristically detect transcript metadata lines to skip."""
    lower = line.lower()
    prefixes = (
        "meeting in",
        "started transcription",
        "stopped transcription",
    )
    if lower.startswith(prefixes):
        return True
    if re.match(r"^\d+\s*[mh]\b", lower):
        return True
    if re.match(r"^\d{1,2}\s+\w+\s+\d{4}", lower):
        return True
    return False


def parse_turns(lines: Iterable[str]) -> List[Turn]:
    """Parse transcript lines into structured speaker turns."""
    turns: List[Turn] = []

    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or looks_like_metadata(line):
            continue

        match = TURN_LINE_RE.match(line)
        if match:
            speaker = match.group("speaker").strip()
            time_label = match.group("time").strip()
            text = match.group("text").strip() or "[no text captured]"
            turns.append(
                Turn(
                    index=len(turns) + 1,
                    speaker=speaker,
                    time_label=time_label,
                    time_sec=parse_timestamp(time_label),
                    text=text,
                )
            )
            continue

        if turns:
            turns[-1].text = f"{turns[-1].text} {line}".strip()

    return turns


def assign_frames(turns: List[Turn], interval_sec: float, frame_count: int) -> None:
    """Assign each turn to its nearest extracted frame index."""
    max_idx = max(frame_count, 1)
    for turn in turns:
        frame_index = int(math.floor(turn.time_sec / interval_sec)) + 1
        frame_index = min(max(frame_index, 1), max_idx)
        turn.frame_index = frame_index
        turn.frame_file = f"frame_{frame_index:06d}.png"


def tokenize(text: str) -> List[str]:
    """Tokenise text into lower-cased keywords with stopword filtering."""
    return [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()) if t not in STOPWORDS]


def sec_to_hhmmss(sec: int) -> str:
    """Format seconds as HH:MM:SS."""
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_keywords(turns: List[Turn], max_keywords: int) -> List[tuple[str, int]]:
    """Compute most frequent keywords across all turns."""
    counter: Counter[str] = Counter()
    for t in turns:
        counter.update(tokenize(t.text))
    return counter.most_common(max_keywords)


def build_timeline(turns: List[Turn], bucket_sec: int, max_keywords: int) -> list[dict]:
    """Group turns into time buckets with summary metadata."""
    grouped: dict[int, List[Turn]] = defaultdict(list)
    for t in turns:
        grouped[t.time_sec // bucket_sec].append(t)

    timeline = []
    for bucket in sorted(grouped):
        bucket_turns = grouped[bucket]
        start = bucket * bucket_sec
        end = start + bucket_sec - 1

        kw_counter: Counter[str] = Counter()
        for t in bucket_turns:
            kw_counter.update(tokenize(t.text))

        timeline.append(
            {
                "start_sec": start,
                "end_sec": end,
                "start": sec_to_hhmmss(start),
                "end": sec_to_hhmmss(end),
                "turn_count": len(bucket_turns),
                "speakers": sorted({t.speaker for t in bucket_turns}),
                "top_keywords": [k for k, _ in kw_counter.most_common(max_keywords)],
                "sample": bucket_turns[0].text[:220],
                "sample_frame": bucket_turns[0].frame_file,
            }
        )
    return timeline


def extract_action_items(turns: List[Turn]) -> List[Turn]:
    """Return turns that match action-oriented heuristic patterns."""
    out: List[Turn] = []
    for t in turns:
        if any(p.search(t.text) for p in ACTION_PATTERNS):
            out.append(t)
    return out


def write_alignment_csv(path: Path, turns: List[Turn]) -> None:
    """Write turn-to-frame alignment data to CSV."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["turn_index", "speaker", "time_label", "time_sec", "frame_index", "frame_file", "text"])
        for t in turns:
            writer.writerow([t.index, t.speaker, t.time_label, t.time_sec, t.frame_index, t.frame_file, t.text])


def write_json(path: Path, payload: dict) -> None:
    """Write a dictionary payload as pretty-printed JSON."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def write_summary_markdown(
    path: Path,
    video_name: str,
    transcript_name: str,
    duration_sec: int,
    frame_count: int,
    interval_sec: float,
    turns: List[Turn],
    timeline: list[dict],
    keywords: list[tuple[str, int]],
    action_items: List[Turn],
) -> None:
    """Write a deterministic Markdown summary draft from computed artefacts."""
    speaker_counts = Counter(t.speaker for t in turns)
    speaker_words = Counter()
    for t in turns:
        speaker_words[t.speaker] += len(t.text.split())

    lines: List[str] = []
    lines.append("# Meeting Summary Draft (Deterministic)")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- Video: {video_name}")
    lines.append(f"- Transcript: {transcript_name}")
    lines.append(f"- Duration: {sec_to_hhmmss(duration_sec)}")
    lines.append(f"- Frame interval: {interval_sec:g}s")
    lines.append(f"- Frames extracted: {frame_count}")
    lines.append(f"- Parsed turns: {len(turns)}")
    lines.append("")

    lines.append("## Participant Activity")
    lines.append("| Participant | Turns | Words |")
    lines.append("|---|---:|---:|")
    for speaker, count in speaker_counts.most_common():
        lines.append(f"| {speaker} | {count} | {speaker_words[speaker]} |")
    lines.append("")

    lines.append("## Top Keywords")
    if keywords:
        lines.append("- " + ", ".join(f"{k} ({n})" for k, n in keywords))
    else:
        lines.append("- None detected")
    lines.append("")

    lines.append("## Action Candidates")
    if action_items:
        for t in action_items[:30]:
            lines.append(
                f"- [{t.time_label}] {t.speaker}: {t.text} (frame: frames/{t.frame_file})"
            )
    else:
        lines.append("- No action-like phrases detected by heuristic.")
    lines.append("")

    lines.append("## Timeline Buckets")
    for bucket in timeline:
        speaker_text = ", ".join(bucket["speakers"]) if bucket["speakers"] else "Unknown"
        keyword_text = ", ".join(bucket["top_keywords"]) if bucket["top_keywords"] else "None"
        lines.append(f"### {bucket['start']} - {bucket['end']}")
        lines.append(f"- Turns: {bucket['turn_count']}")
        lines.append(f"- Speakers: {speaker_text}")
        lines.append(f"- Keywords: {keyword_text}")
        lines.append(f"- Sample frame: frames/{bucket['sample_frame']}")
        lines.append(f"- Sample quote: {bucket['sample']}")
        lines.append("")

    lines.append("## High-Fidelity Finalization Checklist")
    lines.append("- Verify key claims against transcript_normalized.json.")
    lines.append("- Open referenced frame images for visual context checks.")
    lines.append("- Replace heuristic action items with confirmed owner/action/due date.")
    lines.append("- Rewrite this draft into a concise stakeholder-ready summary.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Run deterministic pre-processing and write all output files."""
    args = parse_args()

    video_path = Path(args.video).expanduser().resolve()
    transcript_path = Path(args.transcript).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    frames_dir = output_dir / "frames"

    if not video_path.exists():
        print(f"Video not found: {video_path}", file=sys.stderr)
        return 2
    if not transcript_path.exists():
        print(f"Transcript not found: {transcript_path}", file=sys.stderr)
        return 2
    if args.frame_interval_sec <= 0:
        print("--frame-interval-sec must be > 0", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    duration_sec = int(round(ffprobe_duration(video_path)))
    frame_count = extract_frames(video_path, frames_dir, args.frame_interval_sec)

    lines = read_transcript_lines(transcript_path)
    turns = parse_turns(lines)
    assign_frames(turns, args.frame_interval_sec, frame_count)

    timeline = build_timeline(turns, args.timeline_bucket_sec, args.max_keywords)
    keywords = build_keywords(turns, args.max_keywords)
    action_items = extract_action_items(turns)

    write_alignment_csv(output_dir / "alignment.csv", turns)

    transcript_payload = {
        "turns": [
            {
                "index": t.index,
                "speaker": t.speaker,
                "time_label": t.time_label,
                "time_sec": t.time_sec,
                "text": t.text,
                "frame_index": t.frame_index,
                "frame_file": t.frame_file,
            }
            for t in turns
        ]
    }
    write_json(output_dir / "transcript_normalized.json", transcript_payload)

    metadata = {
        "video": str(video_path),
        "transcript": str(transcript_path),
        "duration_sec": duration_sec,
        "duration_hhmmss": sec_to_hhmmss(duration_sec),
        "frame_interval_sec": args.frame_interval_sec,
        "frames_extracted": frame_count,
        "turns_parsed": len(turns),
        "timeline_bucket_sec": args.timeline_bucket_sec,
    }
    write_json(output_dir / "metadata.json", metadata)

    write_summary_markdown(
        path=output_dir / "summary_draft.md",
        video_name=video_path.name,
        transcript_name=transcript_path.name,
        duration_sec=duration_sec,
        frame_count=frame_count,
        interval_sec=args.frame_interval_sec,
        turns=turns,
        timeline=timeline,
        keywords=keywords,
        action_items=action_items,
    )

    print(f"Wrote: {output_dir / 'summary_draft.md'}")
    print(f"Wrote: {output_dir / 'alignment.csv'}")
    print(f"Wrote: {output_dir / 'transcript_normalized.json'}")
    print(f"Wrote: {output_dir / 'metadata.json'}")
    print(f"Frames directory: {frames_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
