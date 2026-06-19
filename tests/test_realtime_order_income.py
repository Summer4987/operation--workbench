from scripts.realtime_order_income import (
    apply_closed_store_rules,
    build_api_record,
    build_dom_record,
    build_payload,
    merge_records,
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
