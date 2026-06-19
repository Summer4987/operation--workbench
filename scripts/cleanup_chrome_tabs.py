from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEBUG_URL = "http://127.0.0.1:9222"
OUTPUT_DIR = ROOT / "outputs" / "chrome_session_cleanup"
DIRECT_MEITUAN_CONFIG = ROOT / "config" / "direct_meituan_accounts.json"

KEEP_PATTERNS = [
    re.compile(r"r\.ele\.me/doujin-isv-manage"),
    re.compile(r"waimaieapp\.meituan\.com/ad/"),
    re.compile(r"e\.waimai\.meituan\.com"),
    re.compile(r"melody\.shop\.ele\.me"),
    re.compile(r"^about:blank$"),
    re.compile(r"^chrome://newtab/?$"),
]

CATEGORY_PATTERNS = [
    ("blank", re.compile(r"^about:blank$|^chrome://newtab/?$")),
    ("eleme_realtime", re.compile(r"melody\.shop\.ele\.me")),
    ("eleme_promo", re.compile(r"r\.ele\.me/doujin-isv-manage")),
    ("meituan_ad", re.compile(r"waimaieapp\.meituan\.com/ad/")),
    ("meituan_reviews", re.compile(r"waimaieapp\.meituan\.com/frontweb/ffw/userComment_gw")),
    ("meituan_report", re.compile(r"waimaieapp\.meituan\.com/.*/report/download|waimaieapp\.meituan\.com/bizdata_pc/report/download")),
    ("meituan_business", re.compile(r"e\.waimai\.meituan\.com")),
]


def read_json(url: str) -> object:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def load_direct_ports() -> list[int]:
    if not DIRECT_MEITUAN_CONFIG.exists():
        return []
    try:
        payload = json.loads(DIRECT_MEITUAN_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return []
    ports = []
    for account in payload.get("accounts") or []:
        port = account.get("debug_port")
        try:
            ports.append(int(port))
        except (TypeError, ValueError):
            continue
    return ports


def resolve_ports(values: list[str]) -> list[int]:
    ports: list[int] = []
    for value in values:
        if value == "auto":
            ports.extend([9222, 9223, *load_direct_ports()])
            continue
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            ports.append(int(part))
    return sorted(set(ports))


def keep_tab(url: str) -> bool:
    return any(pattern.search(url) for pattern in KEEP_PATTERNS)


def tab_category(url: str) -> str:
    for name, pattern in CATEGORY_PATTERNS:
        if pattern.search(url):
            return name
    return ""


def cleanup_port(port: int, *, dry_run: bool, max_per_category: int) -> dict:
    debug_url = f"http://127.0.0.1:{port}"
    try:
        tabs = read_json(f"{debug_url}/json/list")
    except (OSError, URLError) as exc:
        return {"port": port, "available": False, "error": str(exc), "kept": [], "closed": []}

    closed = []
    kept = []
    seen_categories: dict[str, int] = {}
    for tab in reversed(list(tabs)):
        if tab.get("type") != "page":
            continue
        tab_id = str(tab.get("id") or "")
        url = str(tab.get("url") or "")
        title = str(tab.get("title") or "")
        category = tab_category(url)
        if category:
            count = seen_categories.get(category, 0)
            if count < max_per_category:
                seen_categories[category] = count + 1
                kept.append({"id": tab_id, "title": title, "url": url, "category": category})
                continue
        elif keep_tab(url):
            kept.append({"id": tab_id, "title": title, "url": url})
            continue
        if not tab_id:
            continue
        try:
            if not dry_run:
                urlopen(f"{debug_url}/json/close/{quote(tab_id, safe='')}", timeout=5).read()
            closed.append({"id": tab_id, "title": title, "url": url})
        except (OSError, URLError) as exc:
            print(f"关闭标签页失败：{title} {url}：{exc}", file=sys.stderr)

    return {
        "port": port,
        "available": True,
        "dry_run": dry_run,
        "kept_count": len(kept),
        "closed_count": len(closed),
        "kept": list(reversed(kept)),
        "closed": closed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="清理自动化 Chrome 多余标签页；不退出 Chrome，不清登录态。")
    parser.add_argument("--ports", nargs="*", default=["auto"], help="CDP 端口，默认 auto=9222,9223 和直营美团配置端口。")
    parser.add_argument("--dry-run", action="store_true", help="只输出将关闭的标签页，不实际关闭。")
    parser.add_argument("--max-per-category", type=int, default=1, help="每类页面最多保留几个，默认 1。")
    args = parser.parse_args()

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dry_run": args.dry_run,
        "ports": [],
    }
    for port in resolve_ports(args.ports):
        payload["ports"].append(cleanup_port(port, dry_run=args.dry_run, max_per_category=max(1, args.max_per_category)))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "latest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "output": str(output),
        "ports": [
            {
                "port": item.get("port"),
                "available": item.get("available"),
                "kept": item.get("kept_count", 0),
                "closed": item.get("closed_count", 0),
                "error": item.get("error", ""),
            }
            for item in payload["ports"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
