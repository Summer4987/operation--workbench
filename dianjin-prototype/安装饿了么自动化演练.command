#!/bin/zsh
cd "$(dirname "$0")/.."

scripts/install_eleme_launchd.zsh rehearse all

echo
read -r "?按回车关闭窗口..."
