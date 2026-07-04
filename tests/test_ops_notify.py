from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import ops_notify  # noqa: E402


class OpsNotifyTests(unittest.TestCase):
    def test_legacy_fallback_disabled_by_default(self) -> None:
        self.assertFalse(ops_notify.legacy_fallback_enabled({}))
        self.assertFalse(ops_notify.legacy_fallback_enabled({"allow_legacy_fallback": False}))

    def test_legacy_fallback_requires_explicit_flag(self) -> None:
        self.assertTrue(ops_notify.legacy_fallback_enabled({"allow_legacy_fallback": True}))
        with mock.patch.dict(os.environ, {"OPS_NOTIFY_ALLOW_LEGACY_FALLBACK": "1"}):
            self.assertTrue(ops_notify.legacy_fallback_enabled({}))

    def test_notify_does_not_call_legacy_without_webhook(self) -> None:
        with mock.patch.object(ops_notify, "load_config", return_value={}), mock.patch.object(
            ops_notify, "notify_via_workbuddy", return_value=True
        ) as workbuddy, mock.patch.object(ops_notify, "notify_via_hermes", return_value=True) as hermes:
            self.assertFalse(ops_notify.notify("测试"))

        workbuddy.assert_not_called()
        hermes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
