#!/bin/zsh
cd "$(dirname "$0")"
PYTHON="$(pwd)/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" chrome_cdp_reports.py daily
