#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != Darwin ]] || ! system_profiler SPHardwareDataType | /usr/bin/grep -Eq 'Model Name: Mac mini|机型名称：Mac mini'; then
 echo '拒绝发布：必须在 Mac mini 上运行。' >&2; exit 64
fi
if [[ -n "$(git status --porcelain)" || "$(git branch --show-current)" != main ]]; then
 echo '拒绝发布：必须使用干净 main 副本。' >&2; exit 64
fi
git fetch origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo '请先从 GitHub 拉取 main'; exit 64; }
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)
KEY="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
[[ ! -f "$KEY" ]] || SSH_OPTS+=(-i "$KEY")
SHA="$(git rev-parse HEAD)"
RELEASE="/opt/xiong-access/releases/$SHA"
ssh "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$RELEASE/access-control' '$RELEASE/account-permissions' && sudo chown -R ubuntu:ubuntu /opt/xiong-access"
rsync -az --exclude=__pycache__ --exclude='*.sqlite3*' -e "ssh ${SSH_OPTS[*]}" access-control/ "$SERVER:$RELEASE/access-control/"
rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r -e "ssh ${SSH_OPTS[*]}" account-permissions/ "$SERVER:$RELEASE/account-permissions/"
for tool in floor-plan-designer sales-receipt-generator franchise-contract-generator; do
 ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '/var/www/html/operation-workbench/$tool'"
 rsync -az --exclude='* 2*' --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r -e "ssh ${SSH_OPTS[*]}" "$tool/" "$SERVER:/var/www/html/operation-workbench/$tool/"
done
ssh "${SSH_OPTS[@]}" "$SERVER" "sudo bash '$RELEASE/access-control/install_on_cloud.sh'"
rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r -e "ssh ${SSH_OPTS[*]}" account-permissions/ "$SERVER:/var/www/html/operation-workbench/account-permissions/"
for file in app.js model.js index.html login.html member.html member.js styles.css; do
 expected="$(shasum -a 256 "account-permissions/$file" | awk '{print $1}')"
 actual="$(ssh "${SSH_OPTS[@]}" "$SERVER" "sha256sum '/var/www/html/operation-workbench/account-permissions/$file'" | awk '{print $1}')"
 [[ "$expected" == "$actual" ]] || { echo "文件校验失败 $file"; exit 1; }
done
curl -fsS http://139.155.148.169/login | /usr/bin/grep -q '使用个人账号登录'
echo '账号权限后台、静态页面和登录网关已发布。'
