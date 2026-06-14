#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/daily-order"
SERVICE_FILE="/etc/systemd/system/daily-order.service"
NGINX_SITE="/etc/nginx/conf.d/inventory-board.conf"
LOCATION_MARKER="location /daily-order/"

cd "$APP_DIR"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

sudo cp deploy/daily-order.service "$SERVICE_FILE"

if ! sudo grep -q "$LOCATION_MARKER" "$NGINX_SITE"; then
  sudo cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  sudo python3 - "$NGINX_SITE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
location = """    location /daily-order/ {
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

"""
needle = "    location / {\n"
if needle not in text:
    raise SystemExit("没有找到库存系统的根 location，已停止修改 Nginx")
path.write_text(text.replace(needle, location + needle, 1), encoding="utf-8")
PY
fi

sudo systemctl daemon-reload
sudo systemctl enable daily-order
sudo systemctl restart daily-order
sudo nginx -t
sudo systemctl reload nginx

echo "日常订货链接已安装：http://139.155.148.169/daily-order/"
