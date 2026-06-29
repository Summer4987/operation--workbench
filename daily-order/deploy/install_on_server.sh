#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/daily-order"
SERVICE_FILE="/etc/systemd/system/daily-order.service"
DIGEST_SERVICE_FILE="/etc/systemd/system/daily-order-wechat-digest.service"
DIGEST_TIMER_FILE="/etc/systemd/system/daily-order-wechat-digest.timer"
NGINX_SITE="/etc/nginx/conf.d/inventory-board.conf"
LOCATION_MARKER="location /daily-order/"
DAILY_ORDER_ROOT_REDIRECT_MARKER="location = /daily-order"
BEIJING_LOCATION_MARKER="location /beijing-order/"
BEIJING_ADMIN_MARKER="location = /beijing-order/admin"

cd "$APP_DIR"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

sudo cp deploy/daily-order.service "$SERVICE_FILE"
sudo cp deploy/daily-order-wechat-digest.service "$DIGEST_SERVICE_FILE"
sudo cp deploy/daily-order-wechat-digest.timer "$DIGEST_TIMER_FILE"

if ! sudo grep -q "$LOCATION_MARKER" "$NGINX_SITE"; then
  sudo cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  sudo python3 - "$NGINX_SITE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
location = """    location = /daily-order/admin {
        auth_request /_operation_auth;
        error_page 401 = @operation_login_redirect;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /daily-order/api/admin/ {
        auth_request /_operation_auth;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /daily-order {
        return 307 /daily-order/;
    }

    location /daily-order/ {
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /beijing-order/admin {
        auth_request /_operation_auth;
        error_page 401 = @operation_login_redirect;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /beijing-order/api/admin/ {
        auth_request /_operation_auth;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /beijing-order/ {
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

if ! sudo grep -q "$DAILY_ORDER_ROOT_REDIRECT_MARKER" "$NGINX_SITE"; then
  sudo cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  sudo python3 - "$NGINX_SITE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
location = """    location = /daily-order {
        return 307 /daily-order/;
    }

"""
needle = "    location /daily-order/ {\n"
if needle not in text:
    raise SystemExit("没有找到日常订货 location，已停止添加 /daily-order 跳转")
path.write_text(text.replace(needle, location + needle, 1), encoding="utf-8")
PY
fi

if ! sudo grep -q "$BEIJING_ADMIN_MARKER" "$NGINX_SITE"; then
  sudo cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  sudo python3 - "$NGINX_SITE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
location = """    location = /beijing-order/admin {
        auth_request /_operation_auth;
        error_page 401 = @operation_login_redirect;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /beijing-order/api/admin/ {
        auth_request /_operation_auth;
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

"""
needle = "    location /beijing-order/ {\n"
if needle in text:
    text = text.replace(needle, location + needle, 1)
else:
    fallback = "    location / {\n"
    if fallback not in text:
        raise SystemExit("没有找到可插入北京后台 location 的位置，已停止修改 Nginx")
    text = text.replace(fallback, location + fallback, 1)
path.write_text(text, encoding="utf-8")
PY
fi

if ! sudo grep -q "$BEIJING_LOCATION_MARKER" "$NGINX_SITE"; then
  sudo cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  sudo python3 - "$NGINX_SITE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
location = """    location /beijing-order/ {
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
sudo systemctl enable --now daily-order-wechat-digest.timer
sudo systemctl restart daily-order
sudo nginx -t
sudo systemctl reload nginx

echo "日常订货链接已安装：http://139.155.148.169/daily-order/"
