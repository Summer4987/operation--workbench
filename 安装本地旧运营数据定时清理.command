#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
/bin/zsh "$ROOT/scripts/install_operation_cleanup_launchd.zsh"

echo ""
echo "定时清理安装完成。可以关闭这个窗口。"
