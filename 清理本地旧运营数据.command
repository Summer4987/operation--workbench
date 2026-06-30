#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
/bin/zsh "$ROOT/scripts/cleanup_operation_data.zsh"

echo ""
echo "本地旧运营数据清理完成。可以关闭这个窗口。"
