from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchFrontendTests(unittest.TestCase):
    def test_realtime_store_cards_are_not_limited_to_eight(self) -> None:
        script = (ROOT / "workbench.js").read_text(encoding="utf-8")
        realtime_section = script.split('rows(\n    "realtimeStoreRows"', 1)[1].split("function renderDaily()", 1)[0]

        self.assertNotIn(".slice(0, 8)", realtime_section)

    def test_realtime_missing_period_renders_two_snapshot_comparison_area(self) -> None:
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "workbench.js").read_text(encoding="utf-8")

        self.assertIn('id="realtimeSnapshotComparison"', page)
        self.assertIn('realtimeComparison?.status !== "time_missing"', script)
        self.assertIn("当前较该快照", script)
        self.assertIn("仅供人工比对", script)


if __name__ == "__main__":
    unittest.main()
