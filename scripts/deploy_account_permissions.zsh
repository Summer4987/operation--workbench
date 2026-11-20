#!/bin/zsh
# Run from a clean GitHub main checkout on the Mac mini only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != Darwin ]] || ! system_profiler SPHardwareDataType | /usr/bin/grep -Eq 'Model Name: Mac mini|机型名称：Mac mini'; then
  echo '拒绝发布：此脚本只允许在 Mac mini 生产主机运行。' >&2
  exit 64
fi
if [[ -n "$(git status --porcelain)" ]] || [[ "$(git branch --show-current)" != main ]]; then
  echo '拒绝发布：需要干净的 main 分支；请先保留并判断现有改动。' >&2
  exit 64
fi
git fetch origin main
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo '拒绝发布：当前提交与 GitHub main 不一致，请先拉取已验证代码。' >&2
  exit 64
fi
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
PUBLIC_URL="${OPERATION_CLOUD_PUBLIC_URL:-https://139.155.148.169/operation-workbench/}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then SSH_OPTS+=(-i "$IDENTITY_FILE"); fi
ssh "${SSH_OPTS[@]}" "$SERVER" "test -d '$REMOTE_DIR' && mkdir -p '$REMOTE_DIR/account-permissions'"
rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r -e "ssh ${SSH_OPTS[*]}" account-permissions/ "$SERVER:$REMOTE_DIR/account-permissions/"
# Publish only the navigation HTML, leaving all operational data untouched.
rsync -az --chmod=Fu=rw,Fgo=r -e "ssh ${SSH_OPTS[*]}" index.html "$SERVER:$REMOTE_DIR/index.html"
for file in index.html account-permissions/index.html account-permissions/styles.css account-permissions/model.js account-permissions/app.js; do
  expected="$(shasum -a 256 "$file" | awk '{print $1}')"
  actual="$(ssh "${SSH_OPTS[@]}" "$SERVER" "sha256sum '$REMOTE_DIR/$file'" | awk '{print $1}')"
  if [[ "$expected" != "$actual" ]]; then
    echo "线上校验失败：$file" >&2
    exit 1
  fi
done
# Existing login protection may redirect anonymous requests. Do not bypass it.
headers="$(curl -sS --connect-timeout 10 --max-time 30 -D - -o /dev/null "${PUBLIC_URL}account-permissions/")"
if ! print -r -- "$headers" | /usr/bin/grep -Eq '^HTTP/[^ ]+ (200|302)'; then
  echo '正式页面 HTTP 检查失败。' >&2
  exit 1
fi
if print -r -- "$headers" | /usr/bin/grep -Eq '^HTTP/[^ ]+ 302'; then
  if ! print -r -- "$headers" | /usr/bin/grep -Eiq '^Location: .*/login\?next='; then
    echo '正式页面跳转到非预期入口，请检查。' >&2
    exit 1
  fi
fi
echo "页面文件哈希及正式入口检查通过：${PUBLIC_URL}account-permissions/；还需在已登录浏览器验证显示。"
