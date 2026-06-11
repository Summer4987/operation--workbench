#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SSH_BIN="${SSH_BIN:-/usr/bin/ssh}"
RSYNC_BIN="${RSYNC_BIN:-/usr/bin/rsync}"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_SOURCE_CLOUD_REMOTE_DIR:-/var/www/html/operation-source-data/macmini}"
DATE_TEXT="${1:-$(date +%F)}"
DATE_COMPACT="${DATE_TEXT//-/}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

cd "$ROOT"
SOURCE_DIR="outputs/store_inspection"
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "没有找到巡检证据目录：$SOURCE_DIR"
  exit 1
fi

TMP_LIST="$(mktemp)"
trap 'rm -f "$TMP_LIST"' EXIT

find "$SOURCE_DIR" -type f \( -name "*$DATE_TEXT*" -o -name "*$DATE_COMPACT*" \) > "$TMP_LIST"
if [[ ! -s "$TMP_LIST" ]]; then
  echo "没有找到 $DATE_TEXT 的巡检证据文件。"
  exit 1
fi

"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT'"
"$RSYNC_BIN" -az --files-from="$TMP_LIST" -e "$SSH_BIN ${SSH_OPTS[*]}" ./ "$SERVER:$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT/"

echo "已按需上传 $DATE_TEXT 的巡检证据：$SERVER:$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT"
