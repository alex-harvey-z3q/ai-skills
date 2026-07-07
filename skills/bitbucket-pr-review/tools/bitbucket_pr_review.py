#!/usr/bin/env python3
"""Bitbucket Server/Data Center PR snapshot and commenting utility.

This script uses BITBUCKET_TOKEN from the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, parse, request


class BitbucketClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_root = f"{self.base_url}/rest/api/1.0"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "bitbucket-pr-review-skill/1.0",
        }

    def _build_url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.api_root}{path}"
        if query:
            encoded_query = parse.urlencode(query)
            url = f"{url}?{encoded_query}"
        return url

    def request_json(
        self,
        method: str,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body_bytes = None
        headers = dict(self.headers)
        headers["Accept"] = "application/json"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body_bytes = json.dumps(payload).encode("utf-8")

        req = request.Request(
            self._build_url(path, query=query),
            data=body_bytes,
            method=method,
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data) if data else {}
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {method} {path}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Connection error for {method} {path}: {exc}") from exc

    def request_text(
        self,
        method: str,
        path: str,
        query: Optional[Dict[str, Any]] = None,
    ) -> str:
        headers = dict(self.headers)
        headers["Accept"] = "text/plain"
        req = request.Request(
            self._build_url(path, query=query),
            method=method,
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {method} {path}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Connection error for {method} {path}: {exc}") from exc


def pr_path(project: str, repo: str, pr_id: int, suffix: str = "") -> str:
    project_q = parse.quote(project, safe="")
    repo_q = parse.quote(repo, safe="")
    base = f"/projects/{project_q}/repos/{repo_q}/pull-requests/{pr_id}"
    return f"{base}{suffix}"


def fetch_changes(client: BitbucketClient, project: str, repo: str, pr_id: int) -> Dict[str, Any]:
    changes = []
    start = 0

    while True:
        page = client.request_json(
            "GET",
            pr_path(project, repo, pr_id, "/changes"),
            query={"limit": 500, "start": start},
        )
        values = page.get("values", [])
        changes.extend(values)

        if page.get("isLastPage", True):
            break
        start = page.get("nextPageStart")
        if start is None:
            break

    return {"size": len(changes), "values": changes}


def cmd_snapshot(args: argparse.Namespace, client: BitbucketClient) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pr_json = client.request_json("GET", pr_path(args.project, args.repo, args.pr_id))
    changes_json = fetch_changes(client, args.project, args.repo, args.pr_id)
    diff_text = client.request_text(
        "GET",
        pr_path(args.project, args.repo, args.pr_id, "/diff"),
        query={"contextLines": args.context_lines, "whitespace": args.whitespace},
    )

    (out_dir / "pr.json").write_text(json.dumps(pr_json, indent=2) + "\n", encoding="utf-8")
    (out_dir / "changes.json").write_text(json.dumps(changes_json, indent=2) + "\n", encoding="utf-8")
    (out_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    print(f"Wrote PR snapshot to: {out_dir}")
    print(f"- {out_dir / 'pr.json'}")
    print(f"- {out_dir / 'changes.json'}")
    print(f"- {out_dir / 'diff.patch'}")
    return 0


def read_comment_text(body: Optional[str], body_file: Optional[str]) -> str:
    if body and body_file:
        raise ValueError("Use either --body or --body-file, not both")
    if body_file:
        return Path(body_file).read_text(encoding="utf-8").strip()
    if body:
        return body.strip()
    raise ValueError("Provide comment text using --body or --body-file")


def cmd_comment(args: argparse.Namespace, client: BitbucketClient) -> int:
    text = read_comment_text(args.body, args.body_file)
    if not text:
        raise ValueError("Comment text is empty")

    payload = {"text": text}
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    response = client.request_json(
        "POST",
        pr_path(args.project, args.repo, args.pr_id, "/comments"),
        payload=payload,
    )
    print("Posted PR comment")
    print(json.dumps({"id": response.get("id")}, indent=2))
    return 0


def cmd_inline(args: argparse.Namespace, client: BitbucketClient) -> int:
    text = read_comment_text(args.text, args.body_file)
    if not text:
        raise ValueError("Inline comment text is empty")

    payload = {
        "text": text,
        "anchor": {
            "path": args.path,
            "line": args.line,
            "lineType": args.line_type,
            "fileType": "TO",
        },
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    response = client.request_json(
        "POST",
        pr_path(args.project, args.repo, args.pr_id, "/comments"),
        payload=payload,
    )
    print("Posted inline PR comment")
    print(json.dumps({"id": response.get("id")}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bitbucket PR snapshot and comment utility")
    parser.add_argument("--base-url", required=True, help="Bitbucket base URL, e.g. https://bitbucket.example.com")
    parser.add_argument("--project", required=True, help="Bitbucket project key")
    parser.add_argument("--repo", required=True, help="Bitbucket repository slug")
    parser.add_argument("--pr-id", required=True, type=int, help="Pull request ID")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")

    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Fetch PR metadata, changes, and diff")
    snapshot.add_argument("--out-dir", required=True, help="Output directory for snapshot files")
    snapshot.add_argument("--context-lines", type=int, default=10, help="Context lines for diff endpoint")
    snapshot.add_argument(
        "--whitespace",
        default="SHOW",
        choices=["SHOW", "IGNORE_ALL"],
        help="Diff whitespace handling",
    )

    comment = subparsers.add_parser("comment", help="Post a top-level PR comment")
    comment.add_argument("--body", help="Comment body")
    comment.add_argument("--body-file", help="Path to file containing comment body")
    comment.add_argument("--dry-run", action="store_true", help="Print payload without posting")

    inline = subparsers.add_parser("inline", help="Post an inline PR comment")
    inline.add_argument("--path", required=True, help="Repository-relative file path")
    inline.add_argument("--line", required=True, type=int, help="Line number")
    inline.add_argument(
        "--line-type",
        default="ADDED",
        choices=["ADDED", "REMOVED", "CONTEXT"],
        help="Line type in the PR diff",
    )
    inline.add_argument("--text", help="Inline comment text")
    inline.add_argument("--body-file", help="Path to file containing comment body")
    inline.add_argument("--dry-run", action="store_true", help="Print payload without posting")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    token = os.environ.get("BITBUCKET_TOKEN", "").strip()
    if not token:
        print("BITBUCKET_TOKEN is not set", file=sys.stderr)
        return 2

    client = BitbucketClient(args.base_url, token=token, timeout=args.timeout)

    try:
        if args.command == "snapshot":
            return cmd_snapshot(args, client)
        if args.command == "comment":
            return cmd_comment(args, client)
        if args.command == "inline":
            return cmd_inline(args, client)
        parser.error(f"Unknown command: {args.command}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
