#!/bin/zsh
set -e

cd "$(dirname "$0")"

PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

"$PYTHON" process_reports.py

mkdir -p logs
HTML_PATH="$(pwd)/dashboard/index.html"

if open "$HTML_PATH" >/dev/null 2>&1; then
  echo "已打开看板：$HTML_PATH"
else
  echo "看板已更新，但系统没有成功自动打开浏览器。"
  echo "请手动打开：$HTML_PATH"
fi

if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
