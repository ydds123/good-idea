#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/apple/Documents/Claude/good-idea"
UV_BIN="/opt/homebrew/bin/uv"

if [[ ! -d "$PROJECT_ROOT/.git" || ! -f "$PROJECT_ROOT/.goodidea/state.json" ]]; then
  print -u2 "Good idea repository is missing or not initialized: $PROJECT_ROOT"
  exit 2
fi
if [[ ! -x "$UV_BIN" ]]; then
  print -u2 "uv is not executable: $UV_BIN"
  exit 2
fi

cd "$PROJECT_ROOT"
"$UV_BIN" run goodidea --root "$PROJECT_ROOT" review --expire
"$UV_BIN" run goodidea --root "$PROJECT_ROOT" verify

