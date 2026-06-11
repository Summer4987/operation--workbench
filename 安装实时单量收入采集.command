#!/bin/zsh
cd "$(dirname "$0")"
chmod +x scripts/install_macmini_operation_launchd.zsh
scripts/install_macmini_operation_launchd.zsh
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
