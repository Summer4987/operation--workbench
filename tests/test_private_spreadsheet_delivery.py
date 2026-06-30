#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "private_spreadsheet_delivery.py"


def load_delivery():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("private_spreadsheet_delivery_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrivateSpreadsheetDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.delivery = load_delivery()

    def test_delivery_message_contains_media_path(self) -> None:
        message = self.delivery.build_delivery_message(
            {
                "output_path": "/tmp/易代仓预约_已处理.xlsx",
                "date": "2026-07-01",
                "name": "熊小小牛排饭-冷冻西兰花（冻）",
                "quantity": 100,
                "unit": "件",
                "sku": "LDXXX0005",
            }
        )

        self.assertIn("MEDIA:/tmp/易代仓预约_已处理.xlsx", message)
        self.assertIn("文件路径：/tmp/易代仓预约_已处理.xlsx", message)


if __name__ == "__main__":
    unittest.main()
