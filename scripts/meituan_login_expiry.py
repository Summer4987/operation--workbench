"""美团登录到期提醒。

美团商家后台登录约 30 天失效。本脚本每天在固定空闲时间（launchd 14:30）读取各登录会话
`e.waimai.meituan.com` 的 token cookie 到期时间（只读 Cookies 数据库，不读 cookie 内容、
不打开平台页面、不占用美团账号队列），剩余 ≤ REMIND_DAYS 天时通过通知助手提醒老板
在空闲时段主动重新登录，避免在营业高峰或繁忙时掉线断档。

覆盖：Chrome 调试端口对应的总部/直营账号会话，以及龙虾店长 16 个门店分区会话。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
OUT_DIR = ROOT / "outputs" / "meituan_login_expiry"
FLEET = Path.home() / "Library/Application Support/xiong-dianjin-fleet-test"
REMIND_DAYS = 10
URGENT_DAYS = 5
CHROME_EPOCH = datetime(1601, 1, 1)
PORT_NAMES = {9222: "总部账号（采集/预算）"}


def port_names() -> dict[int, str]:
    names = dict(PORT_NAMES)
    try:
        accounts = json.loads((ROOT / "config/direct_meituan_accounts.json").read_text())["accounts"]
        for a in accounts:
            stores = "、".join(a.get("stores") or []) or a.get("id", "")
            names[int(a["debug_port"])] = f"直营账号·{stores}"
    except Exception:
        pass
    return names


def chrome_profiles() -> dict[int, Path]:
    """调试端口 → Chrome user-data-dir（从正在运行的 Chrome 进程参数读取）。"""
    out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    found: dict[int, Path] = {}
    for line in out.splitlines():
        if "--type=" in line:
            continue
        port = re.search(r"--remote-debugging-port=(\d+)", line)
        udd = re.search(r"--user-data-dir=(.+?)(?= --|$)", line)
        if port and udd:
            found[int(port.group(1))] = Path(udd.group(1).strip().strip('"'))
    return found


def token_expiry(cookie_db: Path) -> datetime | None:
    if not cookie_db.exists():
        return None
    uri = "file:" + str(cookie_db) + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True) as db:
            row = db.execute(
                "SELECT max(expires_utc) FROM cookies WHERE host_key LIKE '%e.waimai.meituan.com' AND name='token'"
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    return CHROME_EPOCH + timedelta(microseconds=int(row[0])) + (datetime.now().astimezone().utcoffset() or timedelta())


def cdp_token_expiry(port: int) -> datetime | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=8000)
            stamps = [c["expires"] for ctx in browser.contexts for c in ctx.cookies("https://e.waimai.meituan.com")
                      if c.get("name") == "token" and c.get("expires", -1) > 0]
    except Exception:
        return None
    return datetime.fromtimestamp(max(stamps)) if stamps else None


def sessions() -> list[dict]:
    rows = []
    names = port_names()
    for port, udd in sorted(chrome_profiles().items()):
        if port not in names:
            continue
        db = next((p for p in (udd / "Default/Cookies", udd / "Default/Network/Cookies") if p.exists()), None)
        # 某些目录（如“文稿”下）受系统隐私保护读不到文件时，改用调试端口只读取 cookie 到期时间。
        expires = token_expiry(db) if db else cdp_token_expiry(port)
        rows.append({"key": f"chrome-{port}", "name": names[port], "expires": expires})
    try:
        profiles = json.loads((FLEET / "profiles.json").read_text())["profiles"]
    except Exception:
        profiles = []
    for p in profiles:
        part = str(p.get("partition", "")).replace("persist:", "")
        rows.append({"key": f"longxia-{p.get('id')}", "name": f"龙虾店长·{p.get('name')}",
                     "expires": token_expiry(FLEET / "Partitions" / part / "Cookies")})
    now = datetime.now()
    for r in rows:
        e = r["expires"]
        r["days_left"] = None if e is None else round((e - now).total_seconds() / 86400, 1)
        r["expires"] = e.strftime("%Y-%m-%d %H:%M") if e else None
    return rows


def build_message(due: list[dict]) -> str:
    lines = ["【美团登录到期提醒】", f"有 {len(due)} 个美团登录即将失效或已失效，请在到期前找 14:30–15:30 的空闲时段，在 Mac mini 上重新登录（避开午晚高峰）："]
    for r in due:
        if r["days_left"] is None or r["days_left"] <= 0:
            lines.append(f"• {r['name']}：已失效，需要尽快登录")
        else:
            day = r["expires"][5:10].replace("-", "月") + "日"
            lines.append(f"• {r['name']}：剩 {int(r['days_left'])} 天（{day}到期）")
    lines.append("重新登录后，明天的检查会自动更新剩余天数。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只打印，不发通知")
    args = ap.parse_args()
    rows = sessions()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state_path = OUT_DIR / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    today = datetime.now().strftime("%F")
    due = []
    for r in rows:
        d = r["days_left"]
        level = "gone" if d is None or d <= 0 else "urgent" if d <= URGENT_DAYS else "remind" if d <= REMIND_DAYS else None
        if level is None:
            state.pop(r["key"], None)
            continue
        prev = state.get(r["key"], {})
        # 进入提醒期提醒一次；≤5 天或已失效时每天提醒，直到重新登录。
        if level == "remind" and prev.get("level") == "remind":
            continue
        if prev.get("date") == today:
            continue
        due.append(r)
        state[r["key"]] = {"level": level, "date": today}
    (OUT_DIR / "latest.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                                                     "sessions": rows}, ensure_ascii=False, indent=2))
    due.sort(key=lambda r: (r["days_left"] is not None, r["days_left"] or 0))
    if args.dry_run:
        for r in rows:
            print(r["name"], r["days_left"], r["expires"])
        print("\n" + (build_message(due) if due else "无需提醒"))
        return 0
    if due:
        import ops_notify
        delivered, _ = ops_notify.notify_with_result(build_message(due))
        if not delivered:
            return 1
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
