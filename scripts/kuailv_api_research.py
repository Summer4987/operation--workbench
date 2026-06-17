from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_api_research"
LATEST_PATH = OUTPUT_DIR / "latest.json"
PACKAGE = "com.sjst.xgfe.android.kmall"
ADB_COMMON_PATHS = [
    Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
    Path("/opt/homebrew/bin/adb"),
    Path("/usr/local/bin/adb"),
]


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def run_command(args: list[str], timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "args": args,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        return {"args": args, "returncode": -1, "stdout": "", "stderr": str(exc)}


def find_adb() -> str:
    env_adb = os.environ.get("ADB")
    if env_adb and Path(env_adb).exists():
        return env_adb
    for path in ADB_COMMON_PATHS:
        if path.exists():
            return str(path)
    found = shutil.which("adb")
    if found:
        return found
    return "adb"


def adb_base(serial: str) -> list[str]:
    base = [find_adb()]
    if serial:
        base.extend(["-s", serial])
    return base


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def unique_limited(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    output = []
    for value in values:
        value = value.strip().strip("'\"")
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
        if len(output) >= limit:
            break
    return output


def grep_strings(path: Path, pattern: str, limit: int) -> list[str]:
    data = path.read_bytes()
    chunks = re.findall(rb"[\x20-\x7e]{4,}", data)
    regex = re.compile(pattern, re.IGNORECASE)
    hits: list[str] = []
    for chunk in chunks:
        text = chunk.decode("utf-8", errors="ignore")
        hits.extend(match.group(0) for match in regex.finditer(text))
        if len(hits) >= limit * 4:
            break
    return unique_limited(hits, limit)


def package_version(dumpsys_text: str) -> dict[str, str]:
    version: dict[str, str] = {}
    for key in ["versionName", "versionCode", "targetSdk", "minSdk"]:
        match = re.search(rf"\b{key}=([^\s]+)", dumpsys_text)
        if match:
            version[key] = match.group(1)
    return version


def scan_apk(apk_path: Path, work_dir: Path) -> dict[str, Any]:
    extract_dir = work_dir / "apk"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk_path) as archive:
        names = archive.namelist()
        for name in names:
            if name.startswith("assets/") or name.endswith(("AndroidManifest.xml", ".dex")):
                try:
                    archive.extract(name, extract_dir)
                except Exception:
                    pass

    url_pattern = r"https?://[^ \t\r\n\"'<>)]{6,}"
    domain_pattern = r"([a-z0-9_-]+\.)+(meituan|dianping|sjst|xgfe|kuailv|sankuai|maicai)[a-z0-9_.-]*"
    api_pattern = r"[A-Za-z0-9_./-]*(cart|shopcart|sku|spu|product|search|order|purchase|settle|checkout|mall|kmall)[A-Za-z0-9_./?=&%-]*"
    urls = grep_strings(apk_path, url_pattern, 120)
    domains = grep_strings(apk_path, domain_pattern, 220)
    api_words = grep_strings(apk_path, api_pattern, 260)

    asset_files = [name for name in names if name.startswith("assets/")]
    mmp_assets = [name for name in asset_files if "klmall" in name.lower() or "mmp" in name.lower()]
    mmp_scans = []
    for name in mmp_assets[:8]:
        asset_path = extract_dir / name
        entry: dict[str, Any] = {"asset": name, "exists": asset_path.exists()}
        if asset_path.exists():
            entry["size"] = asset_path.stat().st_size
            entry["urls"] = grep_strings(asset_path, url_pattern, 40)
            entry["api_words"] = grep_strings(asset_path, api_pattern, 80)
            if zipfile.is_zipfile(asset_path):
                nested_dir = work_dir / ("nested_" + re.sub(r"[^A-Za-z0-9]+", "_", name))
                nested_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(asset_path) as archive:
                    archive.extractall(nested_dir)
                    nested_files = [p for p in nested_dir.rglob("*") if p.is_file()]
                entry["nested_file_count"] = len(nested_files)
                entry["nested_sample"] = [str(p.relative_to(nested_dir)) for p in nested_files[:20]]
                nested_urls: list[str] = []
                nested_api_words: list[str] = []
                for nested_file in nested_files[:100]:
                    nested_urls.extend(grep_strings(nested_file, url_pattern, 20))
                    nested_api_words.extend(grep_strings(nested_file, api_pattern, 30))
                entry["nested_urls"] = unique_limited(nested_urls, 80)
                entry["nested_api_words"] = unique_limited(nested_api_words, 120)
        mmp_scans.append(entry)

    return {
        "apk_size": apk_path.stat().st_size,
        "urls": urls,
        "domains": domains,
        "api_words": api_words,
        "asset_count": len(asset_files),
        "mmp_assets": mmp_scans,
    }


def research(serial: str, timeout: int, scan_apk_enabled: bool) -> dict[str, Any]:
    base = adb_base(serial)
    devices = run_command([base[0], "devices"], timeout)
    current_focus = run_command(base + ["shell", "dumpsys", "window"], timeout)
    package_path_result = run_command(base + ["shell", "pm", "path", PACKAGE], timeout)
    package_dump = run_command(base + ["shell", "dumpsys", "package", PACKAGE], timeout)
    proxy = run_command(base + ["shell", "settings", "get", "global", "http_proxy"], timeout)

    package_path = first_line(package_path_result["stdout"]).replace("package:", "").strip()
    focus_lines = [
        line.strip()
        for line in current_focus["stdout"].splitlines()
        if "mCurrentFocus" in line or "mFocusedApp" in line
    ][:8]

    payload: dict[str, Any] = {
        "generated_at": now_text(),
        "status": "ready",
        "package": PACKAGE,
        "device": {
            "serial": serial,
            "adb": base[0],
            "devices": devices["stdout"].splitlines(),
            "current_focus": focus_lines,
            "http_proxy": first_line(proxy["stdout"]),
        },
        "app": {
            "package_path": package_path,
            "version": package_version(package_dump["stdout"]),
        },
        "strategy": {
            "recommended_next_step": "用 mitmproxy/系统代理抓 klmall.meituan.com 的搜索、购物车、加购接口；ADB 只保留为登录态维护和购物车只读复核。",
            "why": [
                "坐标点击在购物车减号上已出现 input tap 成功但业务无响应，继续堆规则不具备商业化稳定性。",
                "APK 静态线索显示核心入口为 klmall.meituan.com，说明存在 Web/Hybrid 接口层可侦察。",
                "先建立商品名到平台 SKU/spec 的映射库，接口可用后可以秒级加购并减少每日重复搜索。",
            ],
            "forbidden_actions": ["提交订单", "付款", "切换地址"],
        },
        "commands": {
            "devices": devices,
            "package_path": package_path_result,
            "package_dump_returncode": package_dump["returncode"],
            "proxy": proxy,
        },
    }

    if scan_apk_enabled and package_path:
        with tempfile.TemporaryDirectory(prefix="kuailv-api-research-") as tmp:
            tmp_dir = Path(tmp)
            apk_path = tmp_dir / "base.apk"
            pull = run_command(base + ["pull", package_path, str(apk_path)], max(timeout, 60))
            payload["commands"]["apk_pull"] = pull
            if apk_path.exists():
                payload["apk_scan"] = scan_apk(apk_path, tmp_dir)
            else:
                payload["status"] = "partial"
                payload["apk_scan_error"] = pull["stderr"] or pull["stdout"]

    return payload


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    print(f"快驴接口侦察：{payload['status']}")
    print(f"App：{payload['app'].get('version', {})}")
    print(f"当前页面：{' | '.join(payload['device'].get('current_focus') or [])}")
    scan = payload.get("apk_scan") or {}
    if scan:
        print(f"域名：{', '.join(scan.get('domains') or [])[:240]}")
        print(f"URL：{', '.join(scan.get('urls') or [])[:240]}")
        print(f"离线包线索：{len(scan.get('mmp_assets') or [])} 个")
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="快驴接口化自动化侦察：采集 App/域名/离线包线索，不执行下单动作。")
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""), help="ADB 设备号")
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--no-apk-scan", action="store_true", help="不拉取/扫描 APK")
    args = parser.parse_args()

    payload = research(args.adb_serial.strip(), args.timeout, not args.no_apk_scan)
    write_latest(payload)
    print_summary(payload)
    return 0 if payload.get("status") in {"ready", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
