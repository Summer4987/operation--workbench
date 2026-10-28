#!/usr/bin/env python3
"""Capture two customer screenshots from a visually confirmed store result.

Run on the production Mac mini. Runtime evidence belongs outside the checkout.
The caller supplies an observed store-logo coordinate, never a product coordinate.
This tool does not solve verification, navigate offers, or interact with a cart.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

PACKAGES = {"meituan": "com.sankuai.meituan.takeoutnew", "taobao-shangou": "me.ele"}


def compact(value):
    return re.sub(r"\s+", "", value).upper()


def verification(rows):
    text = compact(" ".join(row["text"] for row in rows))
    return any(word in text for word in ("身份验证", "滑动验证", "向右滑动", "安全验证", "账户保护", "账号保护", "验证码", "登录后继续"))


def category_target(rows):
    return next((row for row in rows if row["x"] < 245 and row["y"] > 320
                 and compact(row["text"]) in {"牛排饭", "STEAK", "牛排饭STEAK"}), None)


def header_valid(rows):
    text = compact(" ".join(row["text"] for row in rows))
    return ("熊小小牛排饭" in text and ("点餐" in text or "点菜" in text)
            and ("减" in text or "红包" in text or "立减" in text))


def identity_matches(text, store):
    # Fail closed on truncated/ambiguous headings instead of labeling by intent.
    aliases = {"朝阳门店": ("朝阳门", "第B2档口", "第B2"),
               "中关村店": ("中关村", "第3档口")}
    names = aliases.get(store, (store.removesuffix("店"),))
    heading = compact(text)
    return any(compact(name) in heading for name in names)


class Capture:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.adb = [str(Path(args.adb).expanduser()), "-s", args.serial]
        self.directory = Path(args.output).expanduser() / args.platform / args.store
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ocr = Path(__file__).with_name("customer_inspection_ocr.swift")
        self.events = []

    def command(self, command):
        remaining = self.args.timeout - (time.monotonic() - self.started)
        if remaining <= 0:
            raise TimeoutError("Store time limit reached")
        return subprocess.run(command, check=True, capture_output=True, timeout=min(remaining, 30)).stdout

    def foreground(self):
        state = self.command(self.adb + ["shell", "dumpsys", "activity", "activities"]).decode(errors="replace")
        resumed = "\n".join(line for line in state.splitlines() if "mResumedActivity" in line or "topResumedActivity" in line)
        if PACKAGES[self.args.platform] not in resumed:
            raise RuntimeError("Unexpected foreground app; stop to avoid cross-task input")

    def screen(self, name):
        self.foreground()
        path = self.directory / name
        path.write_bytes(self.command(self.adb + ["exec-out", "screencap", "-p"]))
        rows = json.loads(self.command(["/usr/bin/swift", str(self.ocr), str(path)]))
        if verification(rows):
            raise RuntimeError("Human verification required; platform paused")
        return path, rows

    def tap(self, x, y):
        self.foreground()
        self.command(self.adb + ["shell", "input", "tap", str(int(x)), str(int(y))])

    def run(self):
        # Read before entering, so an existing challenge cannot receive a tap.
        before, entry_rows = self.screen("entry-check.png")
        merchant = next((r for r in entry_rows if "熊小小牛排饭" in compact(r["text"])
                         and r["y"] < 850 and identity_matches(r["text"], self.args.store)), None)
        if merchant is None:
            raise RuntimeError("Expected merchant heading absent from top result")
        self.tap(merchant["x"], merchant["y"])
        time.sleep(4)
        first, rows = self.screen("first-candidate.png")
        if not header_valid(rows):
            expand = next((r for r in rows if r["x"] < 190 and ("点餐" in r["text"] or "点菜" in r["text"])), None)
            if expand is None:
                raise RuntimeError("Store header absent; one expansion attempt unavailable")
            self.tap(150, expand["y"])
            time.sleep(1.5)
            first, rows = self.screen("first-candidate.png")
        if not header_valid(rows):
            raise RuntimeError("Store name and coupon header could not be verified")
        if not any(identity_matches(r["text"], self.args.store) for r in rows
                   if "熊小小牛排饭" in compact(r["text"])):
            raise RuntimeError("Store identity mismatch or truncated identity; capture rejected")
        first.rename(self.directory / "01-first-screen.png")
        category = category_target(rows)
        if category is None:
            # Only the category rail is touched; never the product/add buttons.
            self.foreground()
            self.command(self.adb + ["shell", "input", "swipe", "120", "2200", "120", "1100", "450"])
            time.sleep(1)
            _, rows = self.screen("category-navigation.png")
            category = category_target(rows)
        if category is None:
            raise RuntimeError("STEAK category absent after one rail swipe")
        self.tap(category["x"], category["y"])
        time.sleep(2)
        second, rows = self.screen("category-candidate.png")
        text = compact(" ".join(r["text"] for r in rows))
        if "牛排饭" not in text or not any(v in text for v in ("五花", "板腱", "选购指南", "嫩肩")):
            raise RuntimeError("STEAK product screen could not be verified")
        second.rename(self.directory / "02-steak-category.png")
        before.unlink(missing_ok=True)
        (self.directory / "category-navigation.png").unlink(missing_ok=True)
        return "captured_pending_visual_review"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PACKAGES, required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--entry", nargs=2, type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--adb", default="~/Library/Android/sdk/platform-tools/adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    capture = Capture(args)
    status, error = "failed", None
    try:
        status = capture.run()
    except (RuntimeError, TimeoutError, ValueError, subprocess.SubprocessError) as exc:
        error = str(exc)
    result = dict(platform=args.platform, store=args.store, status=status, error=error,
                  elapsed_seconds=round(time.monotonic() - capture.started, 2),
                  finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    (capture.directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
