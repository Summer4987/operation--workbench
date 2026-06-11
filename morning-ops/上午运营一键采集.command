#!/bin/zsh
cd "$(dirname "$0")"
WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$WORKSPACE/business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" run_morning_ops.py
open "http://139.155.148.169/operation-workbench/"
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
