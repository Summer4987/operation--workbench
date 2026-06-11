#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
/bin/zsh "$ROOT/scripts/sync_source_data_to_cloud.zsh"

echo ""
echo "轻量源数据同步完成。可以关闭这个窗口。"
