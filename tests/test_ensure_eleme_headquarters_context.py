import json
import tempfile
import unittest
from pathlib import Path

from scripts.ensure_eleme_headquarters_context import expected_shop_ids


class ExpectedShopIdsTest(unittest.TestCase):
    def test_expected_shop_ids_are_unique_and_sorted(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = Path(directory) / "preview.json"
            preview.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"shopId": 524321320},
                            {"shopId": "166525463"},
                            {"shopId": 524321320},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(expected_shop_ids(preview), ["166525463", "524321320"])

    def test_expected_shop_ids_reject_empty_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = Path(directory) / "preview.json"
            preview.write_text('{"rows": []}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "没有 shopId"):
                expected_shop_ids(preview)


if __name__ == "__main__":
    unittest.main()
