#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SSH_BIN="${SSH_BIN:-/usr/bin/ssh}"
RSYNC_BIN="${RSYNC_BIN:-/usr/bin/rsync}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_SOURCE_CLOUD_REMOTE_DIR:-/var/www/html/operation-source-data/macmini}"
DATE_TEXT="$(date +%F)"
DAYS="${OPERATION_EVIDENCE_UPLOAD_DAYS:-1}"
LIMIT="${OPERATION_EVIDENCE_UPLOAD_LIMIT:-500}"
RETAIN_DAYS="${OPERATION_CLOUD_EVIDENCE_RETAIN_DAYS:-14}"
DRY_RUN_PRINT_LIMIT="${OPERATION_EVIDENCE_DRY_RUN_PRINT_LIMIT:-80}"
DRY_RUN="false"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

usage() {
  cat <<USAGE
用法：scripts/upload_store_inspection_evidence.zsh [--dry-run] [--date YYYY-MM-DD] [--days N] [--retain-days N]

说明：
  默认上传当天 outputs/store_inspection 下的巡检截图、OCR 和页面证据。
  --dry-run 只生成清单并打印将上传的文件，不连接云端。
  生产环境建议在 Mac mini 上运行；MacBook 可用 --dry-run 验证。
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --date)
      DATE_TEXT="$2"
      shift 2
      ;;
    --days)
      DAYS="$2"
      shift 2
      ;;
    --retain-days)
      RETAIN_DAYS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      DATE_TEXT="$1"
      shift
      ;;
  esac
done

cd "$ROOT"
SOURCE_DIR="outputs/store_inspection"
MANIFEST_PATH="outputs/store_inspection_evidence_manifest/latest.json"
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "没有找到巡检证据目录：$SOURCE_DIR"
  exit 1
fi

if [[ ! -x "$SSH_BIN" || ! -x "$RSYNC_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "缺少上传所需工具：ssh=$SSH_BIN rsync=$RSYNC_BIN python3=$PYTHON_BIN"
  exit 1
fi

"$PYTHON_BIN" scripts/build_store_inspection_evidence_manifest.py --date "$DATE_TEXT" --days "$DAYS" --limit "$LIMIT"

TMP_LIST="$(mktemp)"
TMP_REMOTE_LIST="$(mktemp)"
trap 'rm -f "$TMP_LIST" "$TMP_REMOTE_LIST"' EXIT

"$PYTHON_BIN" - "$MANIFEST_PATH" "$TMP_LIST" "$TMP_REMOTE_LIST" <<'PY'
import json
import sys
from pathlib import Path

manifest_path, list_path, remote_list_path = sys.argv[1:4]
manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
paths = [item["path"] for item in manifest.get("items", []) if item.get("path")]
Path(list_path).write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
remote_paths = [f"./{path}" for path in paths]
remote_paths.append(f"./{manifest_path}")
Path(remote_list_path).write_text("\n".join(remote_paths) + "\n", encoding="utf-8")
print(f"准备上传证据文件 {len(paths)} 个。")
PY

if [[ ! -s "$TMP_LIST" ]]; then
  echo "没有找到 $DATE_TEXT 往前 $DAYS 天内的巡检证据文件。"
  exit 1
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY_RUN=true，仅打印将上传的证据文件："
  sed -n "1,${DRY_RUN_PRINT_LIMIT}p" "$TMP_LIST" | sed 's/^/  /'
  total_count="$(wc -l < "$TMP_LIST" | tr -d ' ')"
  if (( total_count > DRY_RUN_PRINT_LIMIT )); then
    echo "  ... 另有 $(( total_count - DRY_RUN_PRINT_LIMIT )) 个文件，完整清单见 $MANIFEST_PATH"
  fi
  echo "远端目标：$SERVER:$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT/"
  echo "远端保留：$RETAIN_DAYS 天"
  exit 0
fi

"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT'"
"$RSYNC_BIN" -azR --files-from="$TMP_REMOTE_LIST" -e "$SSH_BIN ${SSH_OPTS[*]}" ./ "$SERVER:$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT/"
"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" "find '$REMOTE_DIR/on-demand/store_inspection' -mindepth 1 -maxdepth 1 -type d -mtime +$RETAIN_DAYS -exec rm -rf {} +"

echo "已按需上传 $DATE_TEXT 的巡检证据：$SERVER:$REMOTE_DIR/on-demand/store_inspection/$DATE_TEXT"
echo "云端证据保留策略：保留最近 $RETAIN_DAYS 天。"
