#!/bin/zsh
set -euo pipefail

SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
REPO_RAW_BASE="${OPERATION_GITHUB_RAW_BASE:-https://raw.githubusercontent.com/Summer4987/operation--workbench/main}"
REPO_BRANCH_REF="${OPERATION_GITHUB_BRANCH_REF:-https://api.github.com/repos/Summer4987/operation--workbench/commits/main}"
REMOTE_SCRIPT="${OPERATION_GITHUB_UI_DEPLOY_SCRIPT:-/home/ubuntu/bin/deploy-operation-ui-from-github.sh}"
LOG_FILE="${OPERATION_GITHUB_UI_DEPLOY_LOG:-/home/ubuntu/operation-ui-github-deploy.log}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p \"$(dirname "$REMOTE_SCRIPT")\""

ssh "${SSH_OPTS[@]}" "$SERVER" "cat > '$REMOTE_SCRIPT'" <<'REMOTE_SCRIPT_EOF'
#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR="${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
RAW_BASE="${OPERATION_GITHUB_RAW_BASE:-https://raw.githubusercontent.com/Summer4987/operation--workbench/main}"
COMMIT_API="${OPERATION_GITHUB_BRANCH_REF:-https://api.github.com/repos/Summer4987/operation--workbench/commits/main}"
STATE_DIR="${OPERATION_GITHUB_UI_STATE_DIR:-/home/ubuntu/.operation-workbench}"
LOG_FILE="${OPERATION_GITHUB_UI_DEPLOY_LOG:-/home/ubuntu/operation-ui-github-deploy.log}"
FILES=(index.html workbench.css workbench.js)

mkdir -p "$STATE_DIR"
touch "$LOG_FILE"

latest_sha="$(
  python3 - "$COMMIT_API" <<'PY'
import json
import sys
from urllib.request import Request, urlopen

url = sys.argv[1]
request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "operation-workbench-autodeploy"})
with urlopen(request, timeout=20) as response:
    payload = json.load(response)
print(payload["sha"])
PY
)"

state_file="$STATE_DIR/github-ui.sha"
current_sha=""
if [[ -f "$state_file" ]]; then
  current_sha="$(cat "$state_file")"
fi

if [[ "$latest_sha" == "$current_sha" ]]; then
  exit 0
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

for file in "${FILES[@]}"; do
  curl -fsSL "$RAW_BASE/$file" -o "$tmp_dir/$file"
  test -s "$tmp_dir/$file"
done

for file in "${FILES[@]}"; do
  cp "$tmp_dir/$file" "$REMOTE_DIR/$file"
  chmod 644 "$REMOTE_DIR/$file"
done

find "$REMOTE_DIR" -maxdepth 1 -type d -exec chmod 755 {} +
printf '%s' "$latest_sha" > "$state_file"
date '+%F %T github ui deployed '"$latest_sha" >> "$LOG_FILE"
REMOTE_SCRIPT_EOF

ssh "${SSH_OPTS[@]}" "$SERVER" "chmod +x '$REMOTE_SCRIPT' && OPERATION_CLOUD_REMOTE_DIR='$REMOTE_DIR' OPERATION_GITHUB_RAW_BASE='$REPO_RAW_BASE' OPERATION_GITHUB_BRANCH_REF='$REPO_BRANCH_REF' OPERATION_GITHUB_UI_DEPLOY_LOG='$LOG_FILE' '$REMOTE_SCRIPT'"

cron_line="* * * * * OPERATION_CLOUD_REMOTE_DIR='$REMOTE_DIR' OPERATION_GITHUB_RAW_BASE='$REPO_RAW_BASE' OPERATION_GITHUB_BRANCH_REF='$REPO_BRANCH_REF' OPERATION_GITHUB_UI_DEPLOY_LOG='$LOG_FILE' '$REMOTE_SCRIPT' >/dev/null 2>&1"
ssh "${SSH_OPTS[@]}" "$SERVER" "(crontab -l 2>/dev/null | grep -v \"deploy-operation-ui-from-github.sh\"; printf '%s\n' \"$cron_line\") | crontab -"

echo "GitHub 到腾讯云 UI 自动发布已安装：每分钟检查 GitHub main，只更新 index.html / workbench.css / workbench.js。"
