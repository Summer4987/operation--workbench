from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InventoryWarningNginxTests(unittest.TestCase):
    def test_token_protected_daily_warning_endpoint_bypasses_login_redirect(self):
        config = (ROOT / "inventory-board" / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        location = "location = /api/inventory/warnings/notify"

        self.assertIn(location, config)
        block = config.split(location, 1)[1].split("}", 1)[0]
        self.assertIn("proxy_pass http://127.0.0.1:8000;", block)
        self.assertNotIn("auth_request", block)


if __name__ == "__main__":
    unittest.main()
