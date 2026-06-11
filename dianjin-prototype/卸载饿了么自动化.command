#!/bin/zsh
cd "$(dirname "$0")/.."

scripts/uninstall_eleme_launchd.zsh

echo
read -r "?按回车关闭窗口..."
