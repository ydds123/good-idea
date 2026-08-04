#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/apple/Documents/Claude/good-idea"
CLI_BIN="$PROJECT_ROOT/.venv/bin/goodidea"

if [[ ! -d "$PROJECT_ROOT/.git" || ! -f "$PROJECT_ROOT/.goodidea/state.json" ]]; then
  print -u2 "Good idea repository is missing or not initialized: $PROJECT_ROOT"
  exit 2
fi
if [[ ! -x "$CLI_BIN" ]]; then
  print -u2 "Good idea virtual environment is missing: $CLI_BIN"
  exit 2
fi

cd "$PROJECT_ROOT"
"$CLI_BIN" --root "$PROJECT_ROOT" review --expire
"$CLI_BIN" --root "$PROJECT_ROOT" verify
