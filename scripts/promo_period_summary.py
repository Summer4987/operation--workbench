"""午餐（13:00）/晚餐（20:10）推广时段汇总：美团龙虾店长 + 淘宝闪购自动调价，发到通知助手。

数据只读：龙虾店长 fleet-public-status.json / fleet-events.jsonl，
淘宝闪购 eleme-fleet-status.json / eleme-fleet-events.jsonl。不打开平台页面。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
APP = Path.home() / "Library/Application Support"
LONGXIA = APP / "xiong-dianjin-fleet-test"
ELEME = APP / "xiong-eleme-fleet"
WINDOWS = {"午餐": (10 * 60 + 20, 12 * 60 + 40), "晚餐": (16 * 60 + 55, 20 * 60 + 10)}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def events(path: Path, day: str, window: tuple[int, int]) -> list[dict]:
    out = []
    for p in (path.with_suffix(path.suffix + ".1"), path):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
                t = datetime.fromtimestamp(e["at"] / 1000)
            except Exception:
                continue
            if t.strftime("%F") == day and window[0] <= t.hour * 60 + t.minute < window[1]:
                out.append(e)
    return out


def yuan(cents) -> str:
    return "-" if cents is None else f"{cents / 100:.0f}"


def store_line(name: str, spend, expected, bid, adjusts: int) -> str:
    gap = None if spend is None or expected is None else spend - expected
    pace = "" if gap is None else ("持平" if abs(gap) < 500 else ("快" if gap > 0 else "慢") + yuan(abs(gap)))
    price = "-" if bid is None else f"{bid / 100:.2f}"
    return f"• {name.replace('店', '')}：{yuan(spend)}/{yuan(expected)} {pace}，调{adjusts}次，现{price}"


def section(title: str, stores: list[dict], adjust_count: dict, max_bid: int) -> tuple[list[str], list[str]]:
    lines, flags = [], []
    total_spend = sum(s.get("spend") or 0 for s in stores)
    total_plan = sum(s.get("expected") or 0 for s in stores)
    lines.append(f"{title}（{len(stores)}店）：花 {yuan(total_spend)} 元 / 计划 {yuan(total_plan)} 元")
    for s in stores:
        name = s.get("name") or ""
        lines.append(store_line(name, s.get("spend"), s.get("expected"), s.get("bid"), adjust_count.get(name, 0)))
        spend, expected, bid = s.get("spend"), s.get("expected"), s.get("bid")
        if bid is not None and bid >= max_bid and spend is not None and expected and spend < expected * 0.85:
            flags.append(f"{title}·{name}：出价已到上限仍花不出去")
        if s.get("state") in {"error", "reconcile"} or s.get("pending"):
            flags.append(f"{title}·{name}：{s.get('message') or '调价异常'}")
        if s.get("paused") or s.get("promotionStatus") == "paused":
            flags.append(f"{title}·{name}：推广已暂停")
    return lines, flags


def build(period: str, now: datetime) -> str:
    day, window = now.strftime("%F"), WINDOWS[period]
    lx = load(LONGXIA / "fleet-public-status.json", {})
    mt_stores = [s for s in lx.get("stores", []) if s.get("day") == day]
    mt_adj: dict[str, int] = {}
    for e in events(LONGXIA / "fleet-events.jsonl", day, window):
        if "已保存并回读确认" in str(e.get("message")):
            mt_adj[e.get("name", "")] = mt_adj.get(e.get("name", ""), 0) + 1
    el = load(ELEME / "eleme-fleet-status.json", {})
    el_stores = el.get("stores", []) if el.get("day") == day else []
    el_adj: dict[str, int] = {}
    for e in events(ELEME / "eleme-fleet-events.jsonl", day, window):
        if e.get("type") == "adjusted":
            el_adj[e.get("name", "")] = el_adj.get(e.get("name", ""), 0) + 1
    lines = [f"【推广{period}汇总｜{now.month}月{now.day}日】", "格式：已花/计划（元），快慢，调价次数，现价"]
    flags: list[str] = []
    for title, stores, adj in (("美团", mt_stores, mt_adj), ("淘宝闪购", el_stores, el_adj)):
        lines.append("")
        if not stores:
            lines.append(f"{title}：今天没有调价数据")
            continue
        sec, fl = section(title, stores, adj, 100)
        lines += sec
        flags += fl
    if flags:
        lines += ["", "需要留意："] + [f"• {f}" for f in flags[:8]]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=[*WINDOWS, "auto"], default="auto")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = datetime.now()
    period = args.period if args.period != "auto" else ("午餐" if now.hour < 16 else "晚餐")
    text = build(period, now)
    if args.dry_run:
        print(text)
        return 0
    import ops_notify
    delivered, _ = ops_notify.notify_with_result(text)
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
