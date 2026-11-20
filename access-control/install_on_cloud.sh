#!/usr/bin/env bash
# Invoked by the Mac mini, from GitHub-main source only. Existing credentials stay here.
set -euo pipefail
cd "$(dirname "$0")/.."
release="$PWD"
previous="$(readlink /opt/xiong-access/current || true)"
backup="/var/backups/xiong-access/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup" /var/lib/xiong-access
chown ubuntu:ubuntu /var/lib/xiong-access
chmod 700 /var/lib/xiong-access
auth_config=/etc/nginx/conf.d/inventory-board.conf
# HTTPS migration keeps authorization locations in the shared TLS include.
if [[ -f /etc/nginx/snippets/xiong-workbench-https.conf ]]; then
 auth_config=/etc/nginx/snippets/xiong-workbench-https.conf
fi
cp "$auth_config" "$backup/nginx.conf"
if [[ -f /etc/systemd/system/xiong-access.service ]]; then cp /etc/systemd/system/xiong-access.service "$backup/service"; fi
rollback() {
 cp "$backup/nginx.conf" "$auth_config"
 if [[ -n "$previous" ]]; then
  ln -sfn "$previous" /opt/xiong-access/current
  if [[ -f "$backup/service" ]]; then cp "$backup/service" /etc/systemd/system/xiong-access.service; fi
  systemctl daemon-reload
  systemctl restart xiong-access || true
 else
  systemctl stop xiong-access || true
 fi
 nginx -t && systemctl reload nginx
}
trap rollback ERR
ln -sfn "$release" /opt/xiong-access/current
cp access-control/xiong-access.service /etc/systemd/system/xiong-access.service
systemctl daemon-reload
systemctl enable xiong-access
systemctl restart xiong-access
for attempt in $(seq 1 15); do
 if curl -fsS http://127.0.0.1:8020/health >/dev/null; then break; fi
 sleep 1
done
curl -fsS http://127.0.0.1:8020/health >/dev/null
python3 access-control/install_gateway.py "$auth_config"
if ! nginx -t; then
 cp "$backup/nginx.conf" "$auth_config"
 exit 1
fi
systemctl reload nginx
printf 'Gateway installed; previous nginx config: %s\n' "$backup/nginx.conf"
