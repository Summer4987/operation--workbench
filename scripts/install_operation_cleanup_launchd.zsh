#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.summer.operation.cleanup-data.plist"
LOG_DIR="$HOME/Library/Logs/xiong-operation/launchd"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
RUNNER="$SCRIPT_DIR/run_cleanup_operation_data.zsh"
mkdir -p "$LOG_DIR" "$(dirname "$PLIST")" "$SCRIPT_DIR"

cat > "$RUNNER" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
FIND_BIN="\${FIND_BIN:-/usr/bin/find}"
RAW_DAYS="\${OPERATION_CLEAN_RAW_DAYS:-90}"
JSON_DAYS="\${OPERATION_CLEAN_JSON_DAYS:-60}"
EVIDENCE_DAYS="\${OPERATION_CLEAN_EVIDENCE_DAYS:-3}"
EVIDENCE_MAX_MB="\${OPERATION_CLEAN_EVIDENCE_MAX_MB:-800}"
LOG_DAYS="\${OPERATION_CLEAN_LOG_DAYS:-30}"
DRY_RUN="\${OPERATION_CLEAN_DRY_RUN:-false}"
PYTHON_BIN="\${PYTHON_BIN:-/usr/bin/python3}"
AUTOMATION_SCREENSHOT_MINUTES="\${OPERATION_CLEAN_AUTOMATION_SCREENSHOT_MINUTES:-0}"
EXTRA_AUTOMATION_SCREENSHOT_ROOTS="\${OPERATION_CLEAN_EXTRA_AUTOMATION_SCREENSHOT_ROOTS:-\$HOME/Library/Mobile Documents/.Trash:\$HOME/Documents/文稿 - summer的Mac mini/mac-mini-operation-migration}"

delete_old() {
  local label="\$1"
  local days="\$2"
  shift 2
  local paths=("\$@")
  local action=(-delete)
  if [[ "\$DRY_RUN" == "true" ]]; then
    action=(-print)
  fi
  echo "清理 \$label：保留最近 \$days 天"
  for path in "\${paths[@]}"; do
    local target="\$path"
    if [[ "\$target" != /* ]]; then
      target="\$ROOT/\$target"
    fi
    [[ -e "\$target" ]] || continue
    if ! "\$FIND_BIN" "\$target" -type f -mtime "+\$days" "\${action[@]}" 2>/dev/null; then
      echo "跳过 \$target：当前进程没有访问权限或目录暂不可用"
      continue
    fi
    "\$FIND_BIN" "\$target" -type d -empty -delete 2>/dev/null || true
  done
}

delete_automation_debug_artifacts() {
  local label="\$1"
  shift
  local roots=("\$@")
  local screenshot_names=(
    "eleme_balance*.png"
    "meituan_balance*.png"
    "meituan_find*.png"
    "meituan_promo_ready*.png"
    "chrome_restore_popup*.png"
    "eleme_account_branch*.png"
  )
  local cache_names=(
    "eleme_balance*.ocr.json"
    "eleme_balance*_ocr.json"
    "meituan_balance*.ocr.json"
    "meituan_find*.ocr.json"
    "meituan_promo_ready*.ocr.json"
    "chrome_restore_popup*.ocr.json"
    "eleme_account_branch*.ocr.json"
    "meituan_balance_body_probe.json"
    "meituan_balance_url_probe.json"
  )
  local age_args=()
  if [[ "\$AUTOMATION_SCREENSHOT_MINUTES" =~ '^[0-9]+\$' && "\$AUTOMATION_SCREENSHOT_MINUTES" -gt 0 ]]; then
    age_args=(-mmin "+\$AUTOMATION_SCREENSHOT_MINUTES")
    echo "清理 \$label：删除超过 \${AUTOMATION_SCREENSHOT_MINUTES} 分钟的自动化调试截图/OCR"
  else
    echo "清理 \$label：立即删除自动化调试截图/OCR"
  fi

  for root_path in "\${roots[@]}"; do
    if [[ "\$root_path" != /* ]]; then
      root_path="\$ROOT/\$root_path"
    fi
    [[ -n "\$root_path" && -e "\$root_path" ]] || continue
    for pattern in "\${screenshot_names[@]}" "\${cache_names[@]}"; do
      if [[ "\$DRY_RUN" == "true" ]]; then
        "\$FIND_BIN" "\$root_path" -type f -name "\$pattern" "\${age_args[@]}" -print 2>/dev/null || true
      else
        "\$FIND_BIN" "\$root_path" -type f -name "\$pattern" "\${age_args[@]}" -delete 2>/dev/null || true
      fi
    done
    if [[ "\$DRY_RUN" != "true" ]]; then
      "\$FIND_BIN" "\$root_path" -mindepth 1 -type d -empty -delete 2>/dev/null || true
    fi
  done
}

delete_old "日报/评价原始下载" "\$RAW_DAYS" \
  "business-report-dashboard/data/raw" \
  "business-report-dashboard/data/reviews/raw"

delete_old "自动化 JSON 和实时记录" "\$JSON_DAYS" \
  "outputs/current_budget" \
  "outputs/dianjin_automation" \
  "outputs/meituan_budget_automation" \
  "outputs/promo_budget_preview" \
  "outputs/realtime_order_income"

delete_old "巡检截图和 OCR 证据" "\$EVIDENCE_DAYS" \
  "outputs/store_inspection"

extra_roots=()
if [[ -n "\$EXTRA_AUTOMATION_SCREENSHOT_ROOTS" ]]; then
  IFS=":" read -rA extra_roots <<< "\$EXTRA_AUTOMATION_SCREENSHOT_ROOTS"
fi
delete_automation_debug_artifacts "自动化调试截图/OCR 缓存" \
  "outputs/store_inspection" \
  "\${extra_roots[@]}"

if [[ -d "\$ROOT/outputs/store_inspection" && -x "\$PYTHON_BIN" ]]; then
  "\$PYTHON_BIN" - <<PY
from pathlib import Path

root = Path("\$ROOT") / "outputs" / "store_inspection"
max_bytes = int("\$EVIDENCE_MAX_MB") * 1024 * 1024
dry_run = "\$DRY_RUN" == "true"
try:
    files = [p for p in root.rglob("*") if p.is_file()]
except PermissionError:
    print(f"跳过 {root}：当前进程没有访问权限")
    raise SystemExit(0)
total = sum(p.stat().st_size for p in files)
if total > max_bytes:
    print(f"巡检证据超过体量上限：当前 {total / 1024 / 1024:.1f}MB，上限 {max_bytes / 1024 / 1024:.1f}MB")
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= max_bytes:
            break
        size = path.stat().st_size
        print(path)
        if not dry_run:
            path.unlink()
        total -= size
    if not dry_run:
        for folder in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass
PY
fi

delete_old "日志文件" "\$LOG_DAYS" \
  "outputs/launchd_logs" \
  "business-report-dashboard/logs" \
  "\$HOME/Library/Logs/xiong-daily-report"

echo "本地运营数据清理完成。DRY_RUN=\$DRY_RUN"
EOF
chmod +x "$RUNNER"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.summer.operation.cleanup-data</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>/bin/zsh '$RUNNER'</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>20</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/com.summer.operation.cleanup-data.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/com.summer.operation.cleanup-data.err.log</string>
  <key>WorkingDirectory</key>
  <string>$SCRIPT_DIR</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"

echo "本地旧运营数据定时清理已安装：每天 03:20 自动执行"
echo "$PLIST"
