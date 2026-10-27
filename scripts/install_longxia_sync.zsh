#!/bin/zsh
set -euo pipefail
SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(hostname | tr '[:upper:]' '[:lower:]')" == *mini* ]] || exit 64
[[ "$(git -C "$SOURCE_ROOT" branch --show-current)" == main && -z "$(git -C "$SOURCE_ROOT" status --porcelain)" ]] || exit 64
[[ "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" == "$(git -C "$SOURCE_ROOT" rev-parse origin/main)" ]] || exit 64
for runtime in production node-runtime; do
 destination="$HOME/Library/Application Support/xiong-operation/$runtime"
 for relative in scripts/build_promo_budget_preview.mjs scripts/fleet-budget-trial.mjs scripts/sync_promo_budget_overrides.py scripts/sync_longxia_templates.py; do
  mkdir -p "$destination/${relative:h}"
  cp "$SOURCE_ROOT/$relative" "$destination/$relative.tmp"
  mv "$destination/$relative.tmp" "$destination/$relative"
 done
done
/usr/bin/python3 - <<'PY'
import plistlib
from pathlib import Path
home=Path.home()
label='com.summer.operation.longxia-template-sync'
log=home/'Library/Logs/xiong-dianjin-fleet-test'
log.mkdir(parents=True,exist_ok=True)
p={'Label':label,'ProgramArguments':['/usr/bin/python3',str(home/'Library/Application Support/xiong-operation/production/scripts/sync_longxia_templates.py')],'StartInterval':60,'RunAtLoad':True,'StandardOutPath':str(log/'template-sync.log'),'StandardErrorPath':str(log/'template-sync.error.log')}
(home/'Library/LaunchAgents'/f'{label}.plist').write_bytes(plistlib.dumps(p))
PY
label=com.summer.operation.longxia-template-sync
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$label.plist"
