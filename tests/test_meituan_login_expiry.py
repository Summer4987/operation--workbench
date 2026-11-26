import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import meituan_login_expiry as m  # noqa: E402


class LoginExpiryMessageTests(unittest.TestCase):
    def test_message_lists_expired_and_days_left(self):
        text = m.build_message([
            {"name": "总部账号", "days_left": None, "expires": None},
            {"name": "龙虾店长·滨江店", "days_left": 2.4, "expires": "2026-11-28 18:35"},
        ])
        self.assertIn("总部账号：已失效", text)
        self.assertIn("龙虾店长·滨江店：剩 2 天（11月28日到期）", text)
        self.assertIn("14:30–15:30", text)
        self.assertNotIn("/", text)


if __name__ == "__main__":
    unittest.main()
