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
    <node text="黄皮洋葱精选" bounds="[60,520][460,590]" />
    <node text="月售 1200" bounds="[60,600][260,650]" />
    <node text="20斤/袋" bounds="[80,820][260,880]" />
    <node text="¥" bounds="[640,818][680,880]" />
    <node text="24.00" bounds="[690,810][820,886]" />
    <node text="10斤/袋" bounds="[80,980][260,1040]" />
    <node text="¥" bounds="[640,978][680,1040]" />
    <node text="13.00" bounds="[690,970][820,1046]" />
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

    def test_spec_modal_blocks_checkout_page(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="提交订单" bounds="[800,2200][1060,2320]" />
</hierarchy>"""

        payload = build_spec_modal_payload(xml_text, "黄皮洋葱", "price_asc", 1, None, "洋葱", {}, {})

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["items"], [])
        self.assertIn("识别到高风险页面文本：提交订单", payload["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
