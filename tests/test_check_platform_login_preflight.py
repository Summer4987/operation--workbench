from scripts.check_platform_login_preflight import ELEME_BUDGET_URL, ELEME_REALTIME_URL, classify_page


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
