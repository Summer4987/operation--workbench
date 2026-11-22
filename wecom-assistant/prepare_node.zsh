#!/bin/zsh
# Keep launchd independent of Hermes, version managers and removable symlinks.
set -euo pipefail
RUNTIME="$HOME/.local/share/xiong-wecom-assistant/runtime"
NODE="${WECOM_NODE:-$RUNTIME/node}"
if [[ ! -x "$NODE" && -z "${WECOM_NODE:-}" ]]; then
  NODE="$HOME/.local/bin/node"
fi
if [[ ! -x "$NODE" ]]; then
  echo '缺少 Node >=22；请安装官方运行时后用 WECOM_NODE=/绝对路径/node 重新安装。' >&2
  exit 1
fi
VERSION="$("$NODE" --version)"
if [[ ! "$VERSION" =~ '^v([0-9]+)\.' ]] || (( match[1] < 22 )); then
  echo "需要 Node >=22，当前版本：$VERSION" >&2
  exit 1
fi
mkdir -p "$RUNTIME"
chmod 700 "$RUNTIME"
if [[ "$NODE" != "$RUNTIME/node" || -L "$NODE" ]]; then
  TMP="$(mktemp "$RUNTIME/.node.XXXXXX")"
  trap 'rm -f "$TMP"' EXIT
  cp -L "$NODE" "$TMP"
  chmod 700 "$TMP"
  [[ "$("$TMP" --version)" == "$VERSION" ]]
  mv -f "$TMP" "$RUNTIME/node"
fi
print -r -- "$RUNTIME/node"
