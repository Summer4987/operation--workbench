#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/inventory-board"
SERVICE_FILE="/etc/systemd/system/inventory-board.service"
ENV_FILE="/etc/inventory-board.env"
NGINX_SITE="/etc/nginx/conf.d/inventory-board.conf"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 用户运行这个脚本"
  exit 1
fi

cd "$APP_DIR"

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip nginx
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3 python3-pip nginx
else
  echo "没有识别到 apt-get 或 yum，请先安装 Python 3 和 Nginx"
  exit 1
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [[ ! -f "$ENV_FILE" ]]; then
  PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)"
  cat > "$ENV_FILE" <<EOF
INVENTORY_PASSWORD=$PASSWORD
EOF
  chmod 600 "$ENV_FILE"
  echo "已生成访问密码：$PASSWORD"
else
  echo "已存在 $ENV_FILE，保留原密码"
fi

cp deploy/inventory-board.service "$SERVICE_FILE"
cp deploy/nginx.conf "$NGINX_SITE"

systemctl daemon-reload
systemctl enable inventory-board
systemctl restart inventory-board
systemctl enable nginx
systemctl restart nginx

echo "库存看板已启动"
