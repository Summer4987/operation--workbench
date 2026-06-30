#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== 熊小小AI业务中心 Mac mini Codex 接管 =="
echo "目录：$ROOT"
echo
echo "这条命令会："
echo "1. 准备或更新 ~/Documents/operation-workbench-clean 干净交接仓库"
echo "2. fast-forward 拉取 GitHub main"
echo "3. 打印 docs/MACMINI_NEXT_TASK.md"
echo
echo "它不会覆盖生产目录，不会安装定时任务，不会执行预算、下单、付款或发布。"
echo

/bin/zsh "$ROOT/scripts/macmini_takeover_clean_checkout.zsh"

echo
echo "Mac mini Codex 接管命令执行完成。"
