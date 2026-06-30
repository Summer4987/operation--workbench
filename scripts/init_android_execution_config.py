from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "config" / "android_execution.example.json"
CONFIG_PATH = ROOT / "config" / "android_execution.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_channel(value: str) -> dict[str, Any]:
    parts = [item.strip() for item in value.split("|")]
    while len(parts) < 4:
        parts.append("")
    channel, target_app, account_hint, address_hint = parts[:4]
    return {
        "channel": channel or "未命名供应渠道",
        "target_app": target_app or "对应供应渠道 App 或小程序",
        "account_hint": account_hint,
        "delivery_address_hint": address_hint,
        "enabled": True,
    }


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(EXAMPLE_PATH)
    config["updated_at"] = now_text()
    config["environment"] = args.environment
    config["device"] = {
        "name": args.device_name,
        "connection": args.connection,
        "adb_serial": args.adb_serial,
        "remote_control_app": args.remote_control_app,
        "screen_unlock_required": not args.no_screen_unlock,
    }
    config["operator"] = {
        "name": args.operator_name,
        "contact": args.operator_contact,
        "must_be_online": True,
    }
    config["payment"] = {
        "confirmation_contact": args.payment_contact,
        "confirmation_channel": args.payment_channel,
        "auto_payment_allowed": False,
    }
    channels = [parse_channel(item) for item in args.channel]
    if channels:
        config["channels"] = channels
    forbidden_actions = split_csv(args.forbidden_actions) or [
        "自动提交订单",
        "自动付款",
        "自动替换缺货商品",
        "自动切换收货地址",
    ]
    config["safety"] = {
        "dry_run": True,
        "allow_auto_add_to_cart": args.allow_auto_add_to_cart,
        "forbidden_actions": forbidden_actions,
    }
    return config


def missing_fields(config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    device = config.get("device") or {}
    operator = config.get("operator") or {}
    payment = config.get("payment") or {}
    channels = config.get("channels") or []
    if not (device.get("adb_serial") or device.get("remote_control_app")):
        missing.append("device.adb_serial 或 device.remote_control_app")
    if not operator.get("name"):
        missing.append("operator.name")
    if not operator.get("contact"):
        missing.append("operator.contact")
    if not payment.get("confirmation_contact"):
        missing.append("payment.confirmation_contact")
    if not payment.get("confirmation_channel"):
        missing.append("payment.confirmation_channel")
    if not any(item.get("enabled") for item in channels if isinstance(item, dict)):
        missing.append("至少 1 个启用供应渠道")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="生成远控安卓真实执行配置。默认只预览，必须加 --write 才写入 config/android_execution.json。")
    parser.add_argument("--environment", default="production", choices=["production", "development"], help="配置所属环境")
    parser.add_argument("--device-name", default="订货远控安卓手机", help="设备名称")
    parser.add_argument("--connection", default="adb", choices=["adb", "remote_app", "manual"], help="连接方式")
    parser.add_argument("--adb-serial", default="", help="adb devices 显示的设备序列号")
    parser.add_argument("--remote-control-app", default="", help="远控软件或替代连接方式说明")
    parser.add_argument("--operator-name", default="", help="人工操作员姓名")
    parser.add_argument("--operator-contact", default="", help="人工操作员联系方式")
    parser.add_argument("--payment-contact", default="", help="付款确认联系人")
    parser.add_argument("--payment-channel", default="", help="付款确认渠道，例如 微信/电话/企业微信")
    parser.add_argument(
        "--channel",
        action="append",
        default=[],
        help="供应渠道，格式：渠道名|目标App|账号提示|地址提示。可重复传多个。",
    )
    parser.add_argument("--forbidden-actions", default="", help="逗号分隔的禁止动作；默认包含自动提交订单、自动付款等")
    parser.add_argument("--allow-auto-add-to-cart", action="store_true", help="允许整单自动加购到购物车；仍禁止提交订单和付款")
    parser.add_argument("--no-screen-unlock", action="store_true", help="设备执行前不要求解锁屏幕")
    parser.add_argument("--write", action="store_true", help="写入 config/android_execution.json")
    parser.add_argument("--force", action="store_true", help="覆盖已有 config/android_execution.json")
    args = parser.parse_args()

    config = build_config(args)
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    missing = missing_fields(config)

    if args.write:
        if CONFIG_PATH.exists() and not args.force:
            print(f"{CONFIG_PATH} 已存在；如需覆盖请加 --force。")
            return 1
        CONFIG_PATH.write_text(text, encoding="utf-8")
        CONFIG_PATH.chmod(0o600)
        print(f"已写入：{CONFIG_PATH}")
    else:
        print(text)
        print("预览模式：未写入文件。确认无误后加 --write。")

    if missing:
        print("仍缺少：" + "；".join(missing))
    else:
        print("配置字段已齐全。下一步运行：python3 scripts/check_android_execution_config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
