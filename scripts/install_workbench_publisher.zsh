#!/bin/zsh
# Update only the publication wrapper; do not reinstall launchd or run platform jobs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(hostname | tr '[:upper:]' '[:lower:]')" == *mini* ]] || { echo '只能在 Mac mini 更新正式发布入口' >&2; exit 64; }
cd "$ROOT"
[[ "$(git branch --show-current)" == main ]] || { echo '正式发布只允许 main' >&2; exit 64; }
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo '请先同步 GitHub main' >&2; exit 64; }
# Runtime reports/config may differ; publication code must match verified GitHub code.
git diff --quiet HEAD -- scripts index.html workbench.js workbench.css eleme-bidding.js || { echo '发布代码存在未提交改动' >&2; exit 64; }
TARGET="$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh"
mkdir -p "$(dirname "$TARGET")"
if [[ -f "$TARGET" ]]; then
  cp -p "$TARGET" "$TARGET.before-$(date +%Y%m%d%H%M%S)"
fi
{
  print -r -- '#!/bin/zsh'
  print -r -- 'set -euo pipefail'
  printf 'export OPERATION_ROOT=%q\n' "$ROOT"
  printf 'export OPERATION_UI_SOURCE_ROOT=%q\n' "$ROOT"
  printf 'exec /bin/zsh %q "$@"\n' "$ROOT/scripts/deploy_workbench_to_cloud.zsh"
} > "$TARGET.tmp"
/bin/zsh -n "$TARGET.tmp"
chmod 755 "$TARGET.tmp"
mv "$TARGET.tmp" "$TARGET"
echo '正式看板发布入口已更新；未修改定时任务。'
