# Bash Agent Guide

## Purpose

This file captures Bash-first style preferences for agents working in this repository.

Use these conventions when writing or editing:

- Bash scripts
- shell-script snippets
- Azure CLI automation
- Terraform `user_data`
- CloudFormation `UserData`
- shUnit2 tests

Keep the existing Bash-first style. Do not rewrite automation into Python, Go, or another language unless explicitly asked.

## Bash is intentional here

Prefer Bash for Azure CLI automation in this codebase.

A good pattern is a thin Bash function around each Azure CLI operation. Keep orchestration readable and close to the CLI commands being run.

Do not replace straightforward shell automation with a larger framework or a different runtime unless the user has explicitly requested that.

## Script header

Use:

```bash
#!/usr/bin/env bash
```

Use Bash deliberately. Do not downgrade scripts to POSIX `sh` unless explicitly requested. Thus used `[[ ... ]]` rather than `[ ... ]` and so on.

## Overall style

Prefer clear, top-to-bottom Bash code.

Use descriptive function names. Optimise for experienced developers who may not be Bash specialists.

It is acceptable to use globals for script-level state when that keeps the script simple and readable. Use `local` for function-local variables.

Quote variable expansions.

Prefer `$var` notation over `${var}` for simple variable expansion. Use braces only when
they are needed for disambiguation, parameter expansion, or readability.

Line up related assignments or repeated command arguments when the alignment makes the
code easier to scan. Do not force alignment where it makes the code noisier.

Use:

```bash
read -r
```

rather than plain `read`.

Prefer line-oriented loops where they are simpler and clearer.

Use arrays if they help, but stay compatible with Bash 3.

## Preferred script shape

Structure scripts in this order:

1. `usage`
2. `get_opts`
3. `validate_opts` when needed
4. small logic functions
5. `main`
6. guard clause

Example:

```bash
#!/usr/bin/env bash

usage() {
  cat <<'EOF'
Usage: example.sh -n NAME

Options:
  -n NAME   Name to process
  -h        Show this help
EOF
}

get_opts() {
  local opt OPTARG OPTIND

  while getopts ":n:h" opt; do
    case "$opt" in
      n)
        name="$OPTARG"
        ;;
      h)
        usage
        exit 0
        ;;
      :)
        echo "Option -$OPTARG requires an argument" >&2
        usage >&2
        exit 1
        ;;
      \?)
        echo "Unknown option: -$OPTARG" >&2
        usage >&2
        exit 1
        ;;
    esac
  done
}

validate_opts() {
  if [[ -z "${name:-}" ]]; then
    echo "Missing required option: -n NAME" >&2
    usage >&2
    exit 1
  fi
}

do_work() {
  printf 'Processing %s\n' "$name"
}

main() {
  get_opts "$@"
  validate_opts
  do_work
}

if [[ "$0" == "${BASH_SOURCE[0]}" ]]; then
  main "$@"
fi
```

## Argument parsing

Use `get_opts` for option parsing, usually using `getopts`.

Inside `get_opts`, localise parser variables:

```bash
local opt OPTARG OPTIND
```

Always pass `"$@"` explicitly:

```bash
main "$@"
```

and from `main` to `get_opts`:

```bash
get_opts "$@"
```

## Guard clause

Use a guard clause so tests can source the file without running `main`:

```bash
if [[ "$0" == "${BASH_SOURCE[0]}" ]]; then
  main "$@"
fi
```

This is preferred for scripts that have shUnit2 tests.

## Azure CLI style

Prefer small Bash functions that wrap Azure CLI operations.

Always prefer `jq` or `yq` over JMESPath when JSON/YAML processing is required. Move those filters into named functions that live in one section of the file.

Keep Azure commands visible and understandable. Generally wrap an Azure CLI command in a named function that identifies the command. This improves testability. Avoid hiding important behaviour behind overly clever abstractions.

When modifying live resources, be explicit about what commands are being run. Do not introduce mutating live-infrastructure commands unless explicitly requested.

## Testing

Prefer Bash plus shUnit2 for shell-script tests.

Place shUnit2 tests under a `shunit2/` directory unless the repository already has a different established convention.

Keep tests sourceable. The production script should not execute `main` when sourced by a test.

For Azure CLI scripts, prefer to stub the az wrapper functions rather than calling real Azure services.

When useful, log the az commands that would be run.

## Safety and reporting

Do not run commands that mutate live infrastructure unless the user explicitly asks for that.

When reporting back, say exactly which checks or commands were run and which were not run.

For example, distinguish between:

- `bash -n` run
- `shellcheck` run
- shUnit2 tests run
- Azure commands stubbed
- live Azure commands not run

Prefer honest partial validation over implying that live behaviour has been tested when it has not.
