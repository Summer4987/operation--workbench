#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== 熊小小AI业务中心 Mac mini 生产交接 =="
echo "目录：$ROOT"
echo
echo "这条命令会："
echo "1. 拒绝覆盖有本地改动的生产现场"
echo "2. fast-forward 拉取 origin/main"
echo "3. 运行只读生产检查和只读冒烟"
echo "4. 检查通过后安装或刷新生产定时任务"
echo

/bin/zsh "$ROOT/scripts/macmini_pull_and_check.zsh" --smoke --install-launchd

echo
echo "生产交接命令执行完成。"
