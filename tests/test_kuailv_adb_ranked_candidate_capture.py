from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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


if __name__ == "__main__":
    unittest.main()
