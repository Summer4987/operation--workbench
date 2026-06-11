#!/bin/zsh
cd "$(dirname "$0")/.."

scripts/run_eleme_automation.zsh --time 10:40 --mode rehearse --limit all

echo
read -r "?按回车关闭窗口..."
