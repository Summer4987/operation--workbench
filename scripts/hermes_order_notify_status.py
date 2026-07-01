#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER = "ubuntu@139.155.148.169"
DEFAULT_TOKEN = "daily-order-admin"


def ssh(server: str, script: str, *, timeout: int = 45) -> tuple[int, str]:
    return run(["ssh", server, "bash", "-s"], input_text=script, timeout=timeout)


def run(command: list[str], *, timeout: int = 30, input_text: str | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return completed.returncode, (completed.stdout or "").strip()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def collect_status(server: str, date: str, token: str) -> dict[str, Any]:
    script = """
set -euo pipefail
DATE=__DATE__
TOKEN=__TOKEN__
python3 - <<'PY'
import json
import pathlib
import subprocess
import urllib.request

date = __DATE__
token = __TOKEN__
env_path = pathlib.Path("/etc/store-order-auth.env")
if token == "daily-order-admin" and env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("DAILY_ORDER_ADMIN_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

def sh(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, timeout=12)
        return 0, out.strip()
    except subprocess.CalledProcessError as exc:
        return exc.returncode, (exc.output or "").strip()
    except Exception as exc:
        return 124, str(exc)

service_code, service = sh("systemctl is-active daily-order.service")
timer_code, timer = sh("systemctl is-active daily-order-wechat-digest.timer")
_, timer_line = sh("systemctl list-timers daily-order-wechat-digest.timer --no-pager | sed -n '2p'")

conf_path = pathlib.Path("/etc/systemd/system/daily-order.service.d/notify.conf")
conf = conf_path.read_text() if conf_path.exists() else ""
notify = {
    "exists": conf_path.exists(),
    "type_wecom": "DAILY_ORDER_NOTIFY_TYPE=wecom" in conf,
    "has_webhook": "DAILY_ORDER_NOTIFY_WEBHOOK=" in conf,
    "has_message": "DAILY_ORDER_NOTIFY_MESSAGE=" in conf,
}

digest_url = f"http://127.0.0.1:8010/daily-order/api/admin/wechat-digest?token={token}&date={date}"
try:
    with urllib.request.urlopen(digest_url, timeout=12) as resp:
        digest_payload = json.loads(resp.read().decode("utf-8"))
        digest = {
            "ok": resp.status == 200,
            "has_orders": bool(digest_payload.get("has_orders")),
            "message_count": len(digest_payload.get("messages") or []),
        }
except Exception as exc:
    digest = {"ok": False, "error": str(exc)}

xlsx_url = f"http://127.0.0.1:8010/daily-order/api/admin/order-lines.xlsx?token={token}&date={date}"
try:
    req = urllib.request.Request(xlsx_url, method="GET")
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = resp.read(2)
        xlsx = {
            "ok": resp.status == 200 and data == b"PK",
            "status": resp.status,
            "content_type": resp.headers.get("content-type", ""),
        }
except Exception as exc:
    xlsx = {"ok": False, "error": str(exc)}

print(json.dumps({
    "date": date,
    "service": {"ok": service_code == 0 and service == "active", "state": service},
    "timer": {"ok": timer_code == 0 and timer == "active", "state": timer, "next": timer_line},
    "notify": notify,
    "digest": digest,
    "xlsx": xlsx,
}, ensure_ascii=False))
PY
""".replace("__DATE__", json.dumps(date)).replace("__TOKEN__", json.dumps(token))
    code, output = ssh(server, script, timeout=60)
    if code != 0:
        return {"ok": False, "date": date, "error": output}
    try:
        payload = json.loads(output.splitlines()[-1])
        payload["ok"] = True
        return payload
    except Exception as exc:
        return {"ok": False, "date": date, "error": f"{exc}: {output[-1000:]}"}


def send_excel(server: str, date: str, token: str) -> dict[str, Any]:
    script = """
set -euo pipefail
python3 - <<'PY'
import json
import pathlib
import urllib.request

date = __DATE__
token = __TOKEN__
env_path = pathlib.Path("/etc/store-order-auth.env")
if token == "daily-order-admin" and env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("DAILY_ORDER_ADMIN_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
url = f"http://127.0.0.1:8010/daily-order/api/admin/daily-excel/send?token={token}&date={date}"
req = urllib.request.Request(url, data=b"{}", method="POST")
with urllib.request.urlopen(req, timeout=20) as resp:
    print(resp.read().decode("utf-8"))
PY
""".replace("__DATE__", json.dumps(date)).replace("__TOKEN__", json.dumps(token))
    code, output = ssh(server, script, timeout=45)
    if code != 0:
        return {"ok": False, "date": date, "error": output}
    try:
        payload = json.loads(output)
    except Exception:
        payload = {"raw": output}
    return {"ok": True, "date": date, "result": payload}


def format_status(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return "我没查到企业微信通知状态。原因：" + str(payload.get("error") or "云服务器连接失败")
    service = payload.get("service") or {}
    timer = payload.get("timer") or {}
    notify = payload.get("notify") or {}
    digest = payload.get("digest") or {}
    xlsx = payload.get("xlsx") or {}
    problems = []
    if not service.get("ok"):
        problems.append("订货服务没在运行")
    if not notify.get("has_webhook"):
        problems.append("企业微信 webhook 没配置")
    if not notify.get("type_wecom"):
        problems.append("通知类型不是企业微信")
    if not timer.get("ok"):
        problems.append("微信群汇总定时器没启动")
    if not xlsx.get("ok"):
        problems.append("日配 Excel 下载接口不可用")

    if problems:
        head = "企业微信通知链路还没完全恢复。"
        result = "问题：" + "；".join(problems) + "。"
    else:
        head = "企业微信通知链路是恢复状态。"
        result = "订单通知、微信群汇总定时器、日配 Excel 下载接口都能查到。"

    digest_text = (
        f"你查的 {payload.get('date')} 微信群汇总：有 {digest.get('message_count', 0)} 条。"
        if digest.get("ok")
        else f"你查的 {payload.get('date')} 微信群汇总接口没通。"
    )
    timer_text = f"18 点汇总定时器：{timer.get('state') or '未知'}。"
    return "\n".join([head, result, digest_text, timer_text])


def format_excel_send(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return "日配 Excel 没推送成功。原因：" + str(payload.get("error") or "云服务器连接失败")
    result = payload.get("result") or {}
    if result.get("status") == "empty":
        return f"{payload.get('date')} 没有日配订单明细，所以没有推送 Excel。"
    if result.get("status") == "sent":
        return f"日配 Excel 已推送到企业微信。日期：{payload.get('date')}，明细 {result.get('line_count', 0)} 行。"
    return f"日配 Excel 推送已请求，但结果需要看一下：{json.dumps(result, ensure_ascii=False)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes 检查订货企业微信通知、微信群汇总和日配 Excel 链路")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--date", default=today())
    parser.add_argument("--send-excel", action="store_true", help="单独推送指定日期的日配 Excel 链接到企业微信")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = send_excel(args.server, args.date, args.token) if args.send_excel else collect_status(args.server, args.date, args.token)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.send_excel:
        print(format_excel_send(payload))
    else:
        print(format_status(payload))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
