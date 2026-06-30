#!/bin/zsh
cd "$(dirname "$0")"

echo "先用日常 Chrome 打开饿了么余额页。"
echo "如果这里能正常看到余额表，说明账号本身没问题。"
echo ""
open -a "Google Chrome" "https://e.ele.me/#/iframe/home"

if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
