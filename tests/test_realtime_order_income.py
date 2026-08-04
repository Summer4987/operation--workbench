from scripts.realtime_order_income import (
    apply_account_out_platform_rules,
    apply_closed_store_rules,
    build_api_record,
    build_dom_record,
    build_payload,
    meituan_all_stores_active,
    meituan_realtime_active,
    meituan_realtime_switch_diagnostics,
    merge_records,
    parse_meituan_dom_across_scroll,
    page_requires_login,
    realtime_validation_errors,
)


def test_meituan_api_ignores_valid_order_amount_as_income():
    record = build_api_record(
        {
            "shopName": "熊小小牛排饭POKEBEAR（双井店）",
            "valid_ord_cnt": 83,
            "valid_ord_amt": 5162.8,
        },
        "美团",
        "https://waimaieapp.meituan.com/gw/bizdata/chain/business/rank",
    )

    assert record is not None
    assert record["store"] == "双井"
    assert record["orders"] == 83
    assert record["income"] == 0
    assert record["income_status"] == "missing"


def test_meituan_api_accepts_business_income_labels():
    record = build_api_record(
        {
            "shopName": "熊小小牛排饭POKEBEAR（双井店）",
            "valid_ord_cnt": 83,
            "营业收入": 2820.5,
        },
        "美团",
        "https://waimaieapp.meituan.com/gw/bizdata/chain/business/rank",
    )

    assert record is not None
    assert record["income"] == 2820.5
    assert record["income_status"] == "trusted"


def test_trusted_page_income_wins_over_missing_api_income():
    records = [
        {
            "platform": "美团",
            "store": "双井",
            "source_store": "熊小小牛排饭POKEBEAR（双井店）",
            "orders": 83,
            "income": 0,
            "income_status": "missing",
            "source": "api",
        },
        {
            "platform": "美团",
            "store": "双井",
            "source_store": "熊小小牛排饭POKEBEAR（双井店）",
            "orders": 83,
            "income": 2820.5,
            "income_status": "trusted",
            "source": "page",
        },
    ]

    merged = merge_records(records)

    assert len(merged) == 1
    assert merged[0]["source"] == "page"
    assert merged[0]["income"] == 2820.5


def test_meituan_realtime_dom_row_uses_current_table_columns():
    record = build_dom_record(
        "1 熊小小牛排饭POKEBEAR（第3档口吉祥美食城店） 553.18 1,337.28 1,022.20 2,496.00 715.20 1,695.50 17 43 42.07 1.89",
        "美团",
    )

    assert record is not None
    assert record["store"] == "中关村"
    assert record["orders"] == 17
    assert record["income"] == 553.18


def test_meituan_realtime_dom_row_handles_zero_middle_metrics():
    record = build_dom_record(
        "9 熊小小牛排饭POKEBEAR（五一广场店） 0.00 305.14 0.00 603.80 0.00 396.10 0 9 0.00 44.01",
        "美团",
    )

    assert record is not None
    assert record["store"] == "五一广场"
    assert record["orders"] == 0
    assert record["income"] == 0


def test_meituan_realtime_dom_row_handles_trend_text_in_metric_columns():
    record = build_dom_record(
        "8 熊小小牛排饭POKEBEAR（丽泽门店） 1,055.76 93.31 1,911.70 持平 1,364.60 98.70 29 3 47.06 7.50",
        "美团",
    )

    assert record is not None
    assert record["store"] == "丽泽"
    assert record["orders"] == 29
    assert record["income"] == 1055.76


def test_new_wangjing_store_maps_from_platform_rows():
    record = build_dom_record(
        "4 熊小小牛排饭POKEBEAR（望京店） 128.60 340.10 44.00 520.30 20.00 410.20 5 13 25.72 31.55",
        "美团",
    )

    assert record is not None
    assert record["store"] == "望京"
    assert record["orders"] == 5
    assert record["income"] == 128.6


def test_new_binjiang_store_maps_from_both_platform_rows():
    meituan = build_dom_record(
        "4 熊小小牛排饭POKEBEAR（滨江店） 128.60 340.10 44.00 520.30 20.00 410.20 5 13 25.72 31.55",
        "美团",
    )
    eleme = build_api_record(
        {
            "shopName": "熊小小牛排饭POKEBEAR（滨江店）",
            "valid_ord_cnt": 8,
            "valid_ord_amt": 236.5,
        },
        "饿了么",
        "https://melody.shop.ele.me/proteinStandardQuery/TG3gM96",
    )

    assert meituan is not None
    assert meituan["store"] == "滨江"
    assert eleme is not None
    assert eleme["store"] == "滨江"


def test_closed_store_rule_forces_realtime_zero():
    record = build_dom_record(
        "9 熊小小牛排饭POKEBEAR（五一广场店） 0.00 383.42 0.00 764.30 0.00 498.20 0 12 0.00 41.52",
        "美团",
    )
    record["orders"] = 12
    record["income"] = 383.42

    normalized = apply_closed_store_rules(
        [record],
        {
            "closed_stores": {
                "五一广场": {
                    "platforms": ["美团"],
                    "reason": "门店未开业，实时订单和营业额应为 0。",
                }
            }
        },
    )

    assert normalized[0]["orders"] == 0
    assert normalized[0]["income"] == 0
    assert normalized[0]["original_orders"] == 12
    assert normalized[0]["original_income"] == 383.42


def test_closed_store_rule_adds_missing_platform_zero_record():
    normalized = apply_closed_store_rules(
        [],
        {
            "closed_stores": {
                "五一广场": {
                    "platforms": ["美团"],
                    "reason": "美团账号已不展示该门店。",
                }
            }
        },
    )

    assert normalized == [
        {
            "platform": "美团",
            "store": "五一广场",
            "source_store": "五一广场",
            "orders": 0,
            "income": 0,
            "income_status": "trusted",
            "source": "rule",
            "validation_note": "美团账号已不展示该门店。",
        }
    ]


def test_account_out_platform_rule_adds_missing_only():
    wuyi = build_dom_record(
        "9 熊小小牛排饭POKEBEAR（五一广场店） 574.06 542.95 1,110.50 902.00 739.20 602.10 19 12 38.91 4.36",
        "美团",
    )
    normalized = apply_account_out_platform_rules(
        [wuyi],
        {
            "account_out_platforms": {
                "五一广场": {"platforms": ["美团"], "reason": "不应覆盖真实行"},
                "滨江": {"platforms": ["美团"], "reason": "美团未展示滨江"},
            }
        },
    )
    by_key = {(item["platform"], item["store"]): item for item in normalized}

    assert by_key[("美团", "五一广场")]["source"] == "page"
    assert by_key[("美团", "五一广场")]["orders"] == 19
    assert by_key[("美团", "五一广场")]["income"] == 574.06
    assert by_key[("美团", "滨江")]["income_status"] == "account_out"
    assert by_key[("美团", "滨江")]["validation_note"] == "美团未展示滨江"


def test_payload_tracks_account_out_without_income_missing():
    records = apply_account_out_platform_rules(
        [],
        {"account_out_platforms": {"滨江": {"platforms": ["美团"], "reason": "美团未展示滨江"}}},
    )

    payload = build_payload(records, [])

    assert payload["status"] == "partial"
    assert payload["summary"]["account_out_count"] == 1
    assert payload["summary"]["income_missing_count"] == 0
    assert payload["account_out"] == [
        {"platform": "美团", "store": "滨江", "source": "account_scope", "reason": "美团未展示滨江"}
    ]


def test_meituan_page_row_validation_flags_bad_ticket():
    errors = realtime_validation_errors(
        [
            {
                "platform": "美团",
                "store": "中关村",
                "orders": 500,
                "income": 100,
                "source": "page",
                "raw": "bad row",
            }
        ],
        {"meituan_page_row_validation": {"min_ticket": 8, "max_ticket": 120}},
    )

    assert errors
    assert "客单价异常" in errors[0]


def test_payload_marks_missing_income_as_partial():
    record = build_api_record(
        {
            "shopName": "熊小小牛排饭POKEBEAR（双井店）",
            "valid_ord_cnt": 83,
            "valid_ord_amt": 5162.8,
        },
        "美团",
        "https://waimaieapp.meituan.com/gw/bizdata/chain/business/rank",
    )

    payload = build_payload([record], [])

    assert payload["status"] == "partial"
    assert payload["summary"]["income_missing_count"] == 1
    assert payload["income_missing"] == [{"platform": "美团", "store": "双井", "source": "api"}]


class FakeTarget:
    def __init__(self, text: str, url: str = ""):
        self._text = text
        self.url = url

    def evaluate(self, _script: str) -> str:
        return self._text


class FakePage(FakeTarget):
    frames = []


class FakeMouse:
    def wheel(self, _x: int, _y: int) -> None:
        return None


class FakeScrollingPage:
    frames = []

    def __init__(self):
        self.scrolls = 0
        self.mouse = FakeMouse()

    def evaluate(self, _script: str, *args):
        if args:
            rows = [
                "1 熊小小牛排饭POKEBEAR（第3档口吉祥美食城店） 553.18 1,337.28 1,022.20 2,496.00 715.20 1,695.50 17 43 42.07 1.89"
            ]
            if self.scrolls > 0:
                rows = [
                    "10 熊小小牛排饭POKEBEAR(滨江店) 325.60 325.60 572.20 572.20 403.30 403.30 10 10 40.33 40.33"
                ]
            return rows
        if "scrollTop +" in _script or "window.scrollBy" in _script:
            self.scrolls += 1
        return None

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


def test_meituan_dom_collection_accumulates_virtual_scroll_rows():
    page = FakeScrollingPage()

    records = parse_meituan_dom_across_scroll(page, steps=1)

    assert {record["store"] for record in records} == {"中关村", "滨江"}


def test_meituan_login_page_is_detected_before_realtime_switch():
    page = FakePage("美团外卖商家版 账号登录 验证码登录 忘记密码 登录", "https://e.waimai.meituan.com/new_fe/login_gw#/login")

    assert page_requires_login(page, "美团")


def test_meituan_verify_slider_page_is_detected_before_store_switch():
    page = FakePage("身份核实 请按照说明拖动滑块", "https://verify.meituan.com/v2/app/general_page?requestCode=abc")

    assert page_requires_login(page, "美团")


class FakeRealtimeTarget:
    def __init__(self, result, url: str = "https://e.waimai.meituan.com/"):
        self.result = result
        self.url = url

    def evaluate(self, _script: str):
        return self.result


class FakeRealtimePage(FakeRealtimeTarget):
    def __init__(self, result, frames=None):
        super().__init__(result)
        self.frames = frames or []


def test_meituan_realtime_active_accepts_active_frame_state():
    page = FakeRealtimePage(False, frames=[FakeRealtimeTarget(True)])

    assert meituan_realtime_active(page)


def test_meituan_all_stores_active_accepts_frame_state():
    page = FakeRealtimePage(False, frames=[FakeRealtimeTarget(True)])

    assert meituan_all_stores_active(page)


def test_meituan_realtime_switch_diagnostics_includes_control_state():
    page = FakeRealtimePage(
        [
            {
                "text": "今日实时",
                "className": "ant-radio-button-wrapper-checked",
                "ariaSelected": "true",
                "ariaPressed": "",
                "dataSelected": "",
                "dataActive": "",
            }
        ]
    )

    diagnostics = meituan_realtime_switch_diagnostics(page)

    assert "今日实时" in diagnostics
    assert "ant-radio-button-wrapper-checked" in diagnostics
