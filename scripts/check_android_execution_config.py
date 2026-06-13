from __future__ import annotations

import json
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "android_execution.json"
EXAMPLE_PATH = ROOT / "config" / "android_execution.example.json"
OUTPUT_DIR = ROOT / "outputs" / "android_execution_config"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def runtime_environment() -> str:
    hostname = socket.gethostname().lower()
    if "mini" in hostname:
        return "production"
    return "development"


def missing_if_blank(items: list[str], value: Any, missing: list[str]) -> None:
    if not str(value or "").strip():
        missing.extend(items)


def setup_checklist(missing: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    checklist = [
        {
            "label": "确认设备序列号",
            "command": "adb devices",
            "detail": "在 Mac mini 连接并解锁远控安卓手机，记录在线设备序列号。",
            "blocked": any("adb_serial" in item or "adb" in item.lower() for item in missing + warnings),
        },
        {
            "label": "预览配置",
            "command": (
                "python3 scripts/init_android_execution_config.py "
                "--adb-serial <adb设备号> --operator-name <操作员> --operator-contact <联系方式> "
                "--payment-contact <付款确认人> --payment-channel <微信/电话> "
                "--channel '<渠道名>|<目标App>|<账号提示>|<地址提示>'"
            ),
            "detail": "先预览 config/android_execution.json 内容，不写入文件。",
            "blocked": bool(missing),
        },
        {
            "label": "写入配置",
            "command": (
                "python3 scripts/init_android_execution_config.py --write "
                "--adb-serial <adb设备号> --operator-name <操作员> --operator-contact <联系方式> "
                "--payment-contact <付款确认人> --payment-channel <微信/电话> "
                "--channel '<渠道名>|<目标App>|<账号提示>|<地址提示>'"
            ),
            "detail": "确认预览无误后写入本机私有配置；真实付款仍必须人工确认。",
            "blocked": bool(missing),
        },
        {
            "label": "复查安全项",
            "command": "python3 scripts/check_android_execution_config.py",
            "detail": "确认 dry_run、安全禁止动作、付款确认人和至少一个供应渠道启用。",
            "blocked": bool(missing or warnings),
        },
    ]
    return checklist


def build_payload() -> dict[str, Any]:
    config_exists = CONFIG_PATH.exists()
    config = read_json(CONFIG_PATH if config_exists else EXAMPLE_PATH)
    device = config.get("device") or {}
    operator = config.get("operator") or {}
    payment = config.get("payment") or {}
    channels = config.get("channels") or []
    safety = config.get("safety") or {}

    missing: list[str] = []
    if not config_exists:
        missing.append("config/android_execution.json 尚未创建，请从 config/android_execution.example.json 复制后填写。")
    missing_if_blank(["device.adb_serial 或远控连接标识"], device.get("adb_serial") or device.get("remote_control_app"), missing)
    missing_if_blank(["operator.name"], operator.get("name"), missing)
    missing_if_blank(["operator.contact"], operator.get("contact"), missing)
    missing_if_blank(["payment.confirmation_contact"], payment.get("confirmation_contact"), missing)
    missing_if_blank(["payment.confirmation_channel"], payment.get("confirmation_channel"), missing)
    if not any(bool(item.get("enabled")) for item in channels if isinstance(item, dict)):
        missing.append("至少启用 1 个供应渠道 channels[].enabled=true。")
    if payment.get("auto_payment_allowed"):
        missing.append("payment.auto_payment_allowed 必须保持 false。")
    forbidden = set(safety.get("forbidden_actions") or [])
    for action in ("自动提交订单", "自动付款"):
        if action not in forbidden:
            missing.append(f"safety.forbidden_actions 缺少 {action}。")

    tools = {
        "adb": bool(shutil.which("adb")),
        "scrcpy": bool(shutil.which("scrcpy")),
    }
    warnings: list[str] = []
    if not tools["adb"]:
        warnings.append("当前机器未找到 adb；Mac mini 真实连接前需要安装 Android platform-tools。")
    if not tools["scrcpy"]:
        warnings.append("当前机器未找到 scrcpy；如使用屏幕远控，Mac mini 真实连接前需要安装或确认替代远控工具。")

    status = "ready" if not missing else "missing_config"
    checklist = setup_checklist(missing, warnings)
    return {
        "generated_at": now_text(),
        "status": status,
        "environment": runtime_environment(),
        "config_path": "config/android_execution.json" if config_exists else "",
        "example_path": "config/android_execution.example.json",
        "summary": {
            "missing_count": len(missing),
            "warning_count": len(warnings),
            "enabled_channel_count": sum(1 for item in channels if isinstance(item, dict) and item.get("enabled")),
        },
        "missing": missing,
        "warnings": warnings,
        "setup_checklist": checklist,
        "next_action": "；".join(
            f"{item['label']}：{item['command']}"
            for item in checklist
            if item.get("blocked")
        )
        or "远控安卓配置已齐全；真实执行前仍需人工接管并确认付款。",
        "tools": tools,
        "safety": {
            "dry_run": bool(safety.get("dry_run", True)),
            "auto_payment_allowed": bool(payment.get("auto_payment_allowed", False)),
            "forbidden_actions": safety.get("forbidden_actions") or [],
        },
        "message": "远控安卓连接配置可用。" if status == "ready" else "远控安卓连接配置缺少必要信息。",
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    if payload["missing"]:
        print("缺少：" + "；".join(payload["missing"]))
    if payload["warnings"]:
        print("提示：" + "；".join(payload["warnings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
