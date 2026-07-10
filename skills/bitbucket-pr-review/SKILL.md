---
name: bitbucket-pr-review
description: Review Bitbucket Server/Data Center pull requests by fetching PR metadata and diff with BITBUCKET_TOKEN, then optionally post summary or inline review comments.
---

# Bitbucket PR Review Skill

Use this skill when the user wants a structured code review for a Bitbucket PR and may want comments posted back to the PR.

## Preconditions

- `BITBUCKET_TOKEN` must be set in the shell environment.
- The repository must be reachable from the current machine.
- Use read-only snapshot commands first; only post when the user explicitly asks.

## Inputs You Need

Collect these values before running tools:
- Bitbucket base URL (example: `https://bitbucket.example.com`)
- Project key (example: `KEY`)
- Repository slug (example: `widget`)
- PR ID (example: `1`)

## 1) Fetch PR Snapshot (Read-Only)

Always start by fetching a local snapshot of the PR data and patch.

```bash
cd /path/to/ai-skills/skills/bitbucket-pr-review
python3 tools/bitbucket_pr_review.py \
  --base-url "https://bitbucket.example.com" \
  --project "KEY" \
  --repo "widget" \
  --pr-id 1 \
  snapshot \
  --out-dir "./output/pr-1"
```

This writes:
- `pr.json` (PR metadata)
- `changes.json` (changed files list)
- `diff.patch` (full textual diff)

## 2) Review Workflow

1. Read `pr.json` for context (title, branches, author).
2. Read `changes.json` to scope impact quickly.
3. Review `diff.patch` for bugs, regressions, and test gaps.
4. Draft review output using the template in `inputs/review-comment-template.md`.
5. Keep findings ordered by severity under the template heading.

## Required Review Format

Always structure the review comment body with this prefix:

```markdown
I am the Assistant: <The AI model and version if known>

## How I was Prompted
<Paste the actual user prompt/instructions used for this review>

## Review Findings
<Actual review content>
```

Use this format for both local review output and posted Bitbucket comments.

## 3) Post Summary Comment (Optional)

Only run this when the user explicitly asks to post.

```bash
cd /path/to/ai-skills/skills/bitbucket-pr-review
python3 tools/bitbucket_pr_review.py \
  --base-url "https://bitbucket.example.com" \
  --project "KEY" \
  --repo "widget" \
  --pr-id 1 \
  comment \
  --body-file "./inputs/review-comment-template.md"
```

## 4) Post Inline Comment (Optional)

Use inline comments for file/line-specific findings.

```bash
cd /path/to/ai-skills/skills/bitbucket-pr-review
python3 tools/bitbucket_pr_review.py \
  --base-url "https://bitbucket.example.com" \
  --project "KEY" \
  --repo "widget" \
  --pr-id 1 \
  inline \
  --path "scripts/widget-stuff.sh" \
  --line 120 \
  --line-type "ADDED" \
  --text "Potential null handling regression here when payload is empty."
```

## Safety and Behaviour

- Default to read-only snapshot first.
- Never request secrets in chat; token must already exist in environment.
- If posting fails, report HTTP status and body to the user.
- Do not auto-approve PRs; approval should remain an explicit user decision.
