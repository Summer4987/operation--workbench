#!/bin/zsh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/outputs/manual_resume"
date '+%F %T' > "$ROOT/outputs/manual_resume/continue.flag"
echo "已收到：继续上午运营自动化。"
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
