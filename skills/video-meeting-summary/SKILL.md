---
name: video-meeting-summary
description: Split a meeting video into frames with ffmpeg, align transcript turns to frames deterministically, and generate a structured Markdown summary draft.
---

# Video Meeting Summary Skill

Use this skill when the user provides a meeting video and transcript and wants an organised Markdown summary.

## Deterministic First Pass

Always run the deterministic preprocessor first. It performs these steps:
1. Extracts video metadata with `ffprobe`.
2. Splits the video into PNG frames with `ffmpeg`.
3. Parses transcript turns from `.docx`, `.txt`, `.md`, or `.vtt`.
4. Aligns each timestamped turn to a frame index.
5. Writes deterministic outputs:
- `summary_draft.md`
- `alignment.csv`
- `transcript_normalized.json`
- `metadata.json`

Run:

```bash
cd /path/to/video-meeting-summary
python3 tools/deterministic_meeting_prep.py \
  --video "./meeting.mp4" \
  --transcript "./transcript.docx" \
  --output-dir "./output" \
  --frame-interval-sec 5
```

Paths can be relative or absolute.

## Synthesis Step

After the deterministic pass:
1. Read `summary_draft.md` first.
2. Use `alignment.csv` and selected frame images to verify key moments.
3. Produce the final Markdown summary with:
- Executive summary
- Key decisions
- Action items with owners and due dates if present
- Risks and blockers
- Chronological timeline
- Technical notes

## Notes

- Prefer a frame interval between 3 and 10 seconds for long calls.
- If transcript quality is poor, keep deterministic outputs and explicitly mark uncertain statements.
- Do not skip deterministic pre-processing; it reduces hallucinations and improves consistency.
