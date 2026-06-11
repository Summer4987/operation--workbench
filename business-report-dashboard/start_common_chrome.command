#!/bin/zsh
set -e

cd "$(dirname "$0")"

PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

"$PYTHON" chrome_cdp_reports.py start-chrome

if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
