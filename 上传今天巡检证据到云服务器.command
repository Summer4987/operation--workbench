#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
/bin/zsh "$ROOT/scripts/upload_store_inspection_evidence.zsh" "$(date +%F)"

echo ""
echo "今天的巡检证据上传完成。可以关闭这个窗口。"
