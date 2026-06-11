#!/bin/zsh
set -e

cd "$(dirname "$0")"

BASE_PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$BASE_PYTHON" ]; then
  BASE_PYTHON="python3"
fi

"$BASE_PYTHON" -m venv --system-site-packages .venv
PYTHON="$(pwd)/.venv/bin/python"

"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" -m playwright install chromium

echo ""
echo "浏览器自动化依赖安装完成。"
echo "下一步双击桌面的“经营日报一键采集并发布.command”。"

if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
