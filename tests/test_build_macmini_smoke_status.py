from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_macmini_smoke_status as smoke_module  # noqa: E402


class BuildMacminiSmokeStatusTest(unittest.TestCase):
    def test_completed_production_smoke_allows_business_failure_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "latest.log"
            log_path.write_text(
                "\n".join(
                    [
                        "环境：production",
                        "库存云端健康检查失败：Expecting value: line 1 column 1 (char 0)",
                        "订货建议生成失败：Expecting value: line 1 column 1 (char 0)",
                        "== 4. 冒烟结论 ==",
                        "Mac mini 只读冒烟检查完成。",
                    ]
                ),
                encoding="utf-8",
            )
            old_log_path = smoke_module.LOG_PATH
            try:
                smoke_module.LOG_PATH = log_path

                payload = smoke_module.build_payload()
            finally:
                smoke_module.LOG_PATH = old_log_path

        self.assertEqual(payload["status"], "ready")
        self.assertFalse(payload["summary"]["failed"])
        self.assertEqual(payload["summary"]["fatal_line_count"], 0)
        self.assertEqual(payload["fatal_lines"], [])

    def test_traceback_still_marks_smoke_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "latest.log"
            log_path.write_text(
                "\n".join(
                    [
                        "环境：production",
                        "Traceback (most recent call last):",
                        "Mac mini 只读冒烟检查完成。",
                    ]
                ),
                encoding="utf-8",
            )
            old_log_path = smoke_module.LOG_PATH
            try:
                smoke_module.LOG_PATH = log_path

                payload = smoke_module.build_payload()
            finally:
                smoke_module.LOG_PATH = old_log_path

        self.assertEqual(payload["status"], "failed")
        self.assertTrue(payload["summary"]["failed"])
        self.assertEqual(payload["summary"]["fatal_line_count"], 1)
        self.assertIn("Traceback", payload["fatal_lines"][0])


if __name__ == "__main__":
    unittest.main()
