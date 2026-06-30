#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SSH_BIN="${SSH_BIN:-/usr/bin/ssh}"
RSYNC_BIN="${RSYNC_BIN:-/usr/bin/rsync}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_SOURCE_CLOUD_REMOTE_DIR:-/var/www/html/operation-source-data/macmini}"
PUBLIC_HINT="${OPERATION_SOURCE_CLOUD_PUBLIC_HINT:-ssh $SERVER:$REMOTE_DIR}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

SOURCE_PATHS=(
  "business-report-dashboard/data/latest.json"
  "business-report-dashboard/data/unified_daily.csv"
  "business-report-dashboard/data/unified_reviews.csv"
  "business-report-dashboard/data/raw"
  "business-report-dashboard/data/reviews/raw"
  "data/realtime-history.json"
  "data/source-sync-manifest.json"
  "outputs/current_budget"
  "outputs/dianjin_automation"
  "outputs/meituan_budget_automation"
  "outputs/promo_budget_preview"
  "outputs/realtime_order_income"
  "store-inspection/latest.json"
  "store-inspection/latest-data.js"
)

cd "$ROOT"

if [[ ! -x "$SSH_BIN" || ! -x "$RSYNC_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "缺少同步所需工具：ssh=$SSH_BIN rsync=$RSYNC_BIN python3=$PYTHON_BIN"
  exit 1
fi

"$PYTHON_BIN" scripts/build_source_data_manifest.py

existing_paths=()
for path in "${SOURCE_PATHS[@]}"; do
  if [[ -e "$path" ]]; then
    existing_paths+=("$path")
  fi
done

if [[ ${#existing_paths[@]} -eq 0 ]]; then
  echo "没有找到可同步的轻量源数据。"
  exit 1
fi

"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$REMOTE_DIR' && sudo chown -R \$(whoami):\$(whoami) '$REMOTE_DIR' && chmod -R u+rwX '$REMOTE_DIR'"

"$RSYNC_BIN" -azR \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '.venv/' \
  --exclude 'chrome-profile/' \
  --exclude 'node_modules/' \
  -e "$SSH_BIN ${SSH_OPTS[*]}" \
  "${existing_paths[@]}" \
  "$SERVER:$REMOTE_DIR/"

"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" "rm -rf '$REMOTE_DIR/outputs/store_inspection' && find '$REMOTE_DIR' -type f | wc -l > '$REMOTE_DIR/source-file-count.txt' && date '+%F %T' > '$REMOTE_DIR/last-sync.txt'"

echo "轻量源数据已同步到云服务器：$PUBLIC_HINT"
