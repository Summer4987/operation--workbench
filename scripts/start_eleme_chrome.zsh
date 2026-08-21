#!/bin/zsh
set -euo pipefail

DEBUG_PORT="${ELEME_CDP_PORT:-9223}"
DEBUG_URL="http://127.0.0.1:${DEBUG_PORT}"
PROFILE_DIR="${ELEME_CHROME_PROFILE_DIR:-$HOME/Library/Application Support/xiong-operation/eleme-chrome-profile}"
PROMOTION_URL="https://r.ele.me/doujin-isv-manage/index.html?__path__=eleCpcChain/oldBranch"

if /usr/bin/curl -fsS --max-time 2 "$DEBUG_URL/json/version" >/dev/null 2>&1; then
  echo "饿了么专用 Chrome 已连接：$DEBUG_URL"
  exit 0
fi

mkdir -p "$PROFILE_DIR"
/usr/bin/open -na "Google Chrome" --args \
  --remote-debugging-port="$DEBUG_PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --profile-directory=Default \
  --disable-breakpad \
  --disable-crash-reporter \
  --no-first-run \
  --no-default-browser-check \
  "$PROMOTION_URL"

for _ in {1..30}; do
  if /usr/bin/curl -fsS --max-time 2 "$DEBUG_URL/json/version" >/dev/null 2>&1; then
    echo "饿了么专用 Chrome 已启动：$DEBUG_URL"
    exit 0
  fi
  sleep 1
done

echo "饿了么专用 Chrome 启动超时：$DEBUG_URL"
exit 1
