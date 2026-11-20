#!/bin/zsh
# Deployment controller: Mac mini pulls GitHub main; the cloud fetches that exact commit.
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")/.."
[[ "$(hostname | tr '[:upper:]' '[:lower:]')" == *mini* ]] || { echo 'Mac mini only'; exit 64; }
[[ "$(git branch --show-current)" == main && -z "$(git status --porcelain)" ]] || { echo 'Clean main required'; exit 64; }
git fetch origin main
SHA="$(git rev-parse HEAD)"
[[ "$SHA" == "$(git rev-parse origin/main)" ]] || { echo 'Pull GitHub main first'; exit 64; }
ssh -o BatchMode=yes -o ConnectTimeout=15 -i "$HOME/.ssh/xiong_operation_cloud_ed25519" ubuntu@139.155.148.169 /bin/bash -s -- "$SHA" <<'REMOTE'
set -euo pipefail
SHA="$1"
SOURCE=/opt/xiong-security-source
if ! test -d "$SOURCE/.git"; then
 sudo mkdir -p "$SOURCE";sudo chown ubuntu:ubuntu "$SOURCE"
 git clone --depth 1 https://github.com/Summer4987/operation--workbench.git "$SOURCE"
fi
cd "$SOURCE"
test -z "$(git status --porcelain)"
git fetch origin main
git merge --ff-only origin/main
test "$(git rev-parse HEAD)" = "$SHA"
sudo python3 security/apply_on_cloud.py --commit "$SHA"
REMOTE

python3 security/migrate_runtime_https.py
