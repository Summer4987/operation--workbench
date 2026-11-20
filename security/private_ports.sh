#!/bin/sh
# Protect legacy/unused host services without changing SSH or HTTPS rules.
set -eu
for family in iptables ip6tables; do
    command -v "$family" >/dev/null 2>&1 || continue
    "$family" -w -N XIONG_PRIVATE_PORTS 2>/dev/null || true
    "$family" -w -F XIONG_PRIVATE_PORTS
    "$family" -w -A XIONG_PRIVATE_PORTS -i lo -j RETURN
    "$family" -w -A XIONG_PRIVATE_PORTS -p tcp -m multiport --dports 6080,8088,631 -j REJECT
    "$family" -w -C INPUT -j XIONG_PRIVATE_PORTS 2>/dev/null || "$family" -w -I INPUT 1 -j XIONG_PRIVATE_PORTS
done
