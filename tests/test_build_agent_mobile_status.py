from __future__ import annotations

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import build_agent_mobile_status


class AgentMobileStatusTests(unittest.TestCase):
    def test_payload_contains_safe_mobile_answers(self) -> None:
        payload = build_agent_mobile_status.build_payload()

        self.assertFalse(payload["safety"]["mobile_can_execute"])
        self.assertFalse(payload["safety"]["execution_agent_enabled"])
        self.assertEqual({item["id"] for item in payload["answers"]}, {"status", "problems", "rerun", "execution_agent"})


if __name__ == "__main__":
    unittest.main()
