#!/bin/zsh
cd "$(dirname "$0")"
chmod +x install_launchd.zsh
./install_launchd.zsh
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
