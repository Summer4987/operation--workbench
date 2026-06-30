from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_promo_bid_advice as advice_module  # noqa: E402
import build_promo_bid_approval_queue as queue_module  # noqa: E402


class PromoBidAdviceQueueTest(unittest.TestCase):
    def test_advice_outputs_read_only_safety_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            preview_dir = tmp_path / "dianjin_automation"
            preview_dir.mkdir()
            (preview_dir / "execution_preview_20260630.json").write_text(
                json.dumps(
                    {
                        "summary": {"generatedAt": "2026-06-30 10:40:00", "time": "10:40"},
                        "rows": [
                            {
                                "type": "bid-check",
                                "platform": "饿了么",
                                "store": "银泰城店",
                                "period": "午餐",
                                "currentBid": 1.2,
                                "targetBid": 1.5,
                                "bidDelta": 0.3,
                                "currentSpend": 32,
                                "expectedSpend": 80,
                                "currentBudget": 100,
                                "budgetUsage": "32/100",
                                "action": "提高出价",
                                "canExecute": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_preview_dir = advice_module.PREVIEW_DIR
            try:
                advice_module.PREVIEW_DIR = preview_dir

                payload = advice_module.build_payload()
            finally:
                advice_module.PREVIEW_DIR = old_preview_dir

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["safety_gate"]["mode"], "advice_only")
        self.assertIn("自动提交出价", payload["safety_gate"]["forbidden_actions"])
        self.assertEqual(payload["items"][0]["execution_mode"], "advice_only")
        self.assertEqual(payload["items"][0]["approval_gate"], "manual_required")

    def test_approval_queue_adds_manual_gate_per_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            advice_path = tmp_path / "advice.json"
            decisions_path = tmp_path / "decisions.json"
            advice_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-30 10:41:00",
                        "status": "ready",
                        "summary": {
                            "stale_preview_count": 0,
                            "risk_count": 0,
                            "latest_preview_at": "2026-06-30 10:40:00",
                        },
                        "items": [
                            {
                                "platform": "饿了么",
                                "store": "银泰城店",
                                "period": "午餐",
                                "time": "10:40",
                                "current_bid": 1.2,
                                "target_bid": 1.5,
                                "bid_delta": 0.3,
                                "action": "提高出价",
                                "reason": "曝光不足",
                                "can_execute": True,
                                "approval_required": True,
                                "source": "outputs/dianjin_automation/execution_preview_20260630.json",
                                "source_generated_at": "2026-06-30 10:40:00",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_advice_path = queue_module.ADVICE_PATH
            old_decisions_path = queue_module.DECISIONS_PATH
            try:
                queue_module.ADVICE_PATH = advice_path
                queue_module.DECISIONS_PATH = decisions_path

                payload = queue_module.build_payload()
            finally:
                queue_module.ADVICE_PATH = old_advice_path
                queue_module.DECISIONS_PATH = old_decisions_path

        self.assertEqual(payload["status"], "waiting_approval")
        self.assertEqual(payload["approval_gate"]["status"], "manual_required")
        self.assertEqual(payload["approval_gate"]["execution_plan_command"], "python3 scripts/build_promo_bid_execution_plan.py")
        self.assertEqual(payload["items"][0]["status"], "waiting_approval")
        self.assertFalse(payload["items"][0]["approval_gate"]["can_enter_execution_plan"])
        self.assertIn("record_promo_bid_decision.py", payload["items"][0]["decision_command"])


if __name__ == "__main__":
    unittest.main()
