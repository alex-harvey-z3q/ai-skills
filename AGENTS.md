# AGENTS.md

## Purpose

This repository contains source code for reusable AI agent skills and reusable
AI agent guidance, including `AGENTS.md` files and language-specific style
guides.

Each skill should live under `skills/<skill-name>/` and include a `SKILL.md`.
Tools used by a skill should live under that skill's `tools/` directory unless
there is a clear shared-code reason.

Agent guidance should live in a location that matches its scope. Keep
repository-wide guidance in root-level `AGENTS.md` files, and keep reusable
language-specific guidance under `docs/agent-guides/`.

## Language-Specific Guidance

Before writing or editing language-specific files, read the matching guide:

- Bash, shell snippets, Azure CLI automation, Terraform `user_data`,
  CloudFormation `UserData`, shUnit2:
  `docs/agent-guides/bash.md`

Future language guides should be added under `docs/agent-guides/` and linked
here.

## General Preferences

Keep skills and guidance self-contained where practical.
Prefer deterministic helper tools before model-only synthesis.
Do not introduce a new runtime or framework into a skill unless it is justified
by the task.

When reporting validation, clearly say which checks were run and which were not.
