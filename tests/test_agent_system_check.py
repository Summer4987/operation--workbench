from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_system_check  # noqa: E402


class AgentSystemCheckTests(unittest.TestCase):
    def test_system_message_has_conclusion_and_feature_status(self) -> None:
        payload = agent_system_check.build_result(
            "system_check",
            [
                agent_system_check.item("功能验收：加盟店实时采集", True, "平台门店 18；缺失 0"),
                agent_system_check.item("GitHub main 部署版本", True, "HEAD=abc；origin/main=abc"),
            ],
        )

        self.assertEqual(payload["status"], "ok")
        self.assertIn("结论：所有核心功能可用", payload["message"])
        self.assertIn("功能验收状态", payload["message"])
        self.assertIn("加盟店实时采集", payload["message"])
        self.assertNotIn("store", payload)


if __name__ == "__main__":
    unittest.main()
