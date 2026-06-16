from __future__ import annotations

import json
import re
import sys
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen


DEBUG_URL = "http://127.0.0.1:9222"

KEEP_PATTERNS = [
    re.compile(r"r\.ele\.me/doujin-isv-manage"),
    re.compile(r"waimaieapp\.meituan\.com/ad/"),
    re.compile(r"e\.waimai\.meituan\.com"),
    re.compile(r"melody\.shop\.ele\.me"),
    re.compile(r"^about:blank$"),
    re.compile(r"^chrome://newtab/?$"),
]

CATEGORY_PATTERNS = [
    ("eleme_realtime", re.compile(r"melody\.shop\.ele\.me")),
    ("eleme_promo", re.compile(r"r\.ele\.me/doujin-isv-manage")),
    ("meituan_ad", re.compile(r"waimaieapp\.meituan\.com/ad/")),
    ("meituan_business", re.compile(r"e\.waimai\.meituan\.com")),
]


def read_json(url: str) -> object:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def keep_tab(url: str) -> bool:
    return any(pattern.search(url) for pattern in KEEP_PATTERNS)


def tab_category(url: str) -> str:
    for name, pattern in CATEGORY_PATTERNS:
        if pattern.search(url):
            return name
    return ""


def main() -> int:
    try:
        tabs = read_json(f"{DEBUG_URL}/json/list")
    except (OSError, URLError) as exc:
        print(f"Chrome 调试端口不可用，跳过标签页清理：{exc}")
        return 0

    closed = []
    kept = []
    seen_categories = set()
    for tab in tabs:
        if tab.get("type") != "page":
            continue
        tab_id = str(tab.get("id") or "")
        url = str(tab.get("url") or "")
        title = str(tab.get("title") or "")
        category = tab_category(url)
        if category:
            if category not in seen_categories:
                seen_categories.add(category)
                kept.append({"id": tab_id, "title": title, "url": url, "category": category})
                continue
        elif keep_tab(url):
            kept.append({"id": tab_id, "title": title, "url": url})
            continue
        if not tab_id:
            continue
        try:
            urlopen(f"{DEBUG_URL}/json/close/{quote(tab_id, safe='')}", timeout=5).read()
            closed.append({"id": tab_id, "title": title, "url": url})
        except (OSError, URLError) as exc:
            print(f"关闭标签页失败：{title} {url}：{exc}", file=sys.stderr)

    print(json.dumps({"kept": len(kept), "closed": len(closed), "closed_tabs": closed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
