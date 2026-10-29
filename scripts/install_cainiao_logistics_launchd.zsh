#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
/bin/zsh "$ROOT/scripts/uninstall_cainiao_logistics_launchd.zsh"
echo "菜鸟任务已取消，拒绝重新安装。" >&2
exit 2
