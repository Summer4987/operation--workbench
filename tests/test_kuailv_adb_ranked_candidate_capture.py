from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_adb_ranked_candidate_capture import (  # noqa: E402
    build_spec_modal_payload,
    find_spec_control_target,
)
from kuailv_adb_ranked_candidate_capture import build_payload  # noqa: E402


class KuailvAdbRankedCandidateCaptureTest(unittest.TestCase):
    def test_overlay_detail_xml_is_blocked(self) -> None:
        xml_text = (ROOT / "tests" / "fixtures" / "kuailv_adb_overlay_detail_window_dump.xml").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        payload = build_payload(xml_text, "洋葱", "default", 1, None, "")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["summary"]["candidate_count"], 0)
        self.assertIn("检测到详情/活动页顶层导航", payload["page_context"]["blocking_reasons"])
        self.assertEqual(payload["items"], [])

    def test_find_spec_control_target_matches_card_title(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="search-page-container" bounds="[0,0][1080,2358]">
    <node text="黄皮洋葱" resource-id="complex-card-goods-1" bounds="[0,330][1080,650]" />
    <node text="黄皮洋葱精选" bounds="[300,360][610,420]" />
    <node text="月售 1200" bounds="[300,430][480,470]" />
    <node text="选规格" bounds="[850,540][1020,620]" />
    <node text="白皮洋葱" resource-id="complex-card-goods-2" bounds="[0,660][1080,970]" />
    <node text="白皮洋葱" bounds="[300,700][560,760]" />
    <node text="选规格" bounds="[850,860][1020,940]" />
  </node>
</hierarchy>"""

        result = find_spec_control_target(xml_text, "黄皮洋葱", None, "", 0)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["target"]["title"], "黄皮洋葱精选")
        self.assertEqual(result["target"]["control_text"], "选规格")

    def test_spec_modal_candidates_are_extracted(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" bounds="[0,0][1080,2400]">
    <node text="玉米粒1kg" bounds="[80,720][260,780]" />
    <node text="¥" bounds="[640,718][680,780]" />
    <node text="3.20" bounds="[690,710][820,786]" />
    <node text="" resource-id="com.sjst.xgfe.android.kmall:id/bottom_layout" bounds="[0,1040][1080,2355]" />
    <node text="黄皮洋葱精选" bounds="[60,1120][460,1190]" />
    <node text="月售 1200" bounds="[60,1200][260,1250]" />
    <node text="20斤/袋" bounds="[80,1420][260,1480]" />
    <node text="¥" bounds="[640,1418][680,1480]" />
    <node text="24.00" bounds="[690,1410][820,1486]" />
    <node text="10斤/袋" bounds="[80,1580][260,1640]" />
    <node text="¥" bounds="[640,1578][680,1640]" />
    <node text="13.00" bounds="[690,1570][820,1646]" />
    <node text="加入购物车" bounds="[780,2200][1060,2320]" />
  </node>
</hierarchy>"""
        tap_result = {"target": {"title": "黄皮洋葱精选", "card_bounds": [0, 330, 1080, 650]}}

        payload = build_spec_modal_payload(xml_text, "黄皮洋葱", "price_asc", 1, None, "洋葱", {}, tap_result)

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["summary"]["candidate_count"], 2)
        self.assertEqual(payload["items"][0]["source"], "adb_xml_spec_modal")
        prices_by_spec = {item["spec"]: item["price"] for item in payload["items"]}
        self.assertEqual(prices_by_spec["20斤/袋"], 24.0)
        self.assertEqual(prices_by_spec["10斤/袋"], 13.0)

    def test_expanded_product_card_emits_each_offer_row(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="search-page-container" bounds="[0,0][1080,2358]">
    <node text="黄皮洋葱" bounds="[120,120][300,210]" />
    <node text="综合排序" bounds="[40,620][210,680]" />
    <node text="销量" bounds="[300,620][390,680]" />
    <node text="价格" bounds="[480,620][570,680]" />
    <node text="黄皮洋葱" resource-id="complex-card-goods-1" bounds="[20,760][1060,1500]" />
    <node text="黄皮洋葱" bounds="[440,820][620,880]" />
    <node text="月售8292" bounds="[440,900][620,950]" />
    <node text="5斤" bounds="[440,1030][510,1090]" />
    <node text="¥" bounds="[590,1030][630,1090]" />
    <node text="1.19" bounds="[640,1025][730,1095]" />
    <node text="/斤" bounds="[735,1030][790,1090]" />
    <node text="10斤" bounds="[440,1160][525,1220]" />
    <node text="¥" bounds="[590,1160][630,1220]" />
    <node text="1.15" bounds="[640,1155][730,1225]" />
    <node text="/斤" bounds="[735,1160][790,1220]" />
    <node text="20斤" bounds="[440,1290][525,1350]" />
    <node text="¥" bounds="[590,1290][630,1350]" />
    <node text="1.17" bounds="[640,1285][730,1355]" />
    <node text="/斤" bounds="[735,1290][790,1350]" />
  </node>
</hierarchy>"""

        payload = build_payload(xml_text, "黄皮洋葱", "price_asc", 1, None, "洋葱")

        offers = [item for item in payload["items"] if item["source"] == "adb_xml_product_card_offer"]
        self.assertEqual(payload["status"], "ready")
        self.assertEqual({item["spec"] for item in offers}, {"5斤", "10斤", "20斤"})
        self.assertEqual({item["price"] for item in offers}, {1.19, 1.15, 1.17})
        self.assertEqual({item["unit_price"] for item in offers}, {1.19, 1.15, 1.17})

    def test_collapsed_product_card_keeps_unit_price(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="search-page-container" bounds="[0,0][1080,2358]">
    <node text="黄皮洋葱" bounds="[120,120][300,210]" />
    <node text="综合排序" bounds="[40,620][210,680]" />
    <node text="销量" bounds="[300,620][390,680]" />
    <node text="价格" bounds="[480,620][570,680]" />
    <node text="黄皮洋葱" resource-id="complex-card-goods-1" bounds="[20,760][1060,1150]" />
    <node text="黄皮洋葱" bounds="[440,820][620,880]" />
    <node text="月售2333" bounds="[440,900][620,950]" />
    <node text="选规格" bounds="[880,990][1030,1060]" />
    <node text="¥" bounds="[440,1030][480,1090]" />
    <node text="1.2-1.32" bounds="[490,1025][650,1095]" />
    <node text="/斤" bounds="[655,1030][710,1090]" />
  </node>
</hierarchy>"""

        payload = build_payload(xml_text, "黄皮洋葱", "price_asc", 1, None, "洋葱")

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["items"][0]["source"], "adb_xml_product_card")
        self.assertEqual(payload["items"][0]["price"], 1.2)

    def test_spec_modal_blocks_checkout_page(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="提交订单" bounds="[800,2200][1060,2320]" />
</hierarchy>"""

        payload = build_spec_modal_payload(xml_text, "黄皮洋葱", "price_asc", 1, None, "洋葱", {}, {})

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["items"], [])
        self.assertIn("识别到高风险页面文本：提交订单", payload["blocking_reasons"])

    def test_shallow_bottom_layout_is_not_treated_as_spec_modal(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" bounds="[0,0][1080,2400]">
    <node text="" resource-id="com.sjst.xgfe.android.kmall:id/bottom_layout" bounds="[0,2213][1080,2355]" />
    <node text="400g" bounds="[264,2300][354,2351]" />
    <node text="¥" bounds="[354,2303][379,2354]" />
    <node text="3.2" bounds="[376,2289][458,2348]" />
  </node>
</hierarchy>"""
        tap_result = {"target": {"title": "黄皮洋葱", "card_bounds": [25, 821, 1054, 1144]}}

        payload = build_spec_modal_payload(xml_text, "黄皮洋葱", "price_asc", 1, None, "洋葱", {}, tap_result)

        self.assertEqual(payload["status"], "needs_review")
        self.assertEqual(payload["summary"]["candidate_count"], 0)
        self.assertEqual(payload["items"], [])


if __name__ == "__main__":
    unittest.main()
