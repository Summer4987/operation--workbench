import subprocess
from unittest import mock

import scripts.check_platform_login_preflight as preflight
from scripts.check_platform_login_preflight import (
    ELEME_BUDGET_URL,
    ELEME_REALTIME_URL,
    MEITUAN_BUDGET_URL,
    build_notice,
    check_direct_meituan_accounts,
    classify_page,
    direct_failures_can_be_isolated,
)


def test_eleme_security_center_menu_is_not_auth_block():
    result = classify_page(
        "饿了么",
        "淘宝闪购商家版",
        "https://melody.shop.ele.me/app/chain/93331264/downloadCenter#app.chainshop.downloadCenter",
        "数据下载 报表下载 下载管理 金融保险 安全中心",
        ["数据下载", "报表下载", "下载管理", "商家版"],
    )

    assert result["status"] == "ok"
    assert result["blocking_texts"] == []


def test_real_verification_text_still_blocks():
    result = classify_page(
        "饿了么",
        "安全验证",
        "https://melody.shop.ele.me/",
        "请完成验证码 安全验证后继续",
        ["数据下载"],
    )

    assert result["status"] == "auth_block"
    assert "验证码" in result["blocking_texts"]


def test_invalid_legacy_chain_store_is_blocked():
    result = classify_page(
        "饿了么",
        "淘宝闪购商家版",
        "https://melody.shop.ele.me/app/chain/93331264/store-analysis",
        "集团主体账号 无效店铺，无法访问 当前账号无法访问该店铺",
        ["商家版"],
    )

    assert result["status"] == "auth_block"
    assert "无效店铺" in result["blocking_texts"]


def test_eleme_group_account_routes_do_not_use_legacy_chain_path():
    assert "/app/unit/" in ELEME_REALTIME_URL
    assert "/app/unit/" in ELEME_BUDGET_URL
    assert "/app/chain/" not in ELEME_REALTIME_URL
    assert "/app/chain/" not in ELEME_BUDGET_URL


def test_meituan_budget_preflight_uses_real_promo_route():
    assert "ad/v1/rpc" in MEITUAN_BUDGET_URL


def test_direct_meituan_preflight_checks_promo_page_and_isolates_timeout():
    with mock.patch.object(preflight, "direct_accounts_enabled", return_value=["direct_test"]):
        with mock.patch.object(
            preflight.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["checker"], 45),
        ) as run:
            results = check_direct_meituan_accounts(1200)

    assert "home,promo_balance" in run.call_args.args[0]
    assert results[0]["account_id"] == "direct_test"
    assert results[0]["status"] == "auth_block"
    assert "登录态检查超过" in results[0]["message"]
    assert "已按掉线/页面异常处理" in results[0]["message"]


def test_login_notice_identifies_direct_account_and_reason():
    notice = build_notice(
        "budget",
        [
            {
                "platform": "直营美团",
                "account_id": "direct_wanxiangcheng",
                "status": "auth_block",
                "message": "推广页要求扫码登录",
            }
        ],
        True,
    )

    assert "直营美团（direct_wanxiangcheng）" in notice
    assert "推广页要求扫码登录" in notice


def test_only_direct_meituan_login_failures_can_continue_to_store_isolation():
    direct_failed = [{"platform": "直营美团", "status": "auth_block"}]
    mixed_failed = direct_failed + [{"platform": "美团", "status": "auth_block"}]

    assert direct_failures_can_be_isolated(direct_failed, True)
    assert not direct_failures_can_be_isolated(direct_failed, False)
    assert not direct_failures_can_be_isolated(mixed_failed, True)
