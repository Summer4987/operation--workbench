from scripts.realtime_order_income import build_api_record, build_payload, merge_records


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
