from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "floor-plan-designer"


class FloorPlanDesignerTests(unittest.TestCase):
    def test_tool_is_linked_from_workbench(self) -> None:
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="#floor-plan"', index)
        self.assertIn('src="./floor-plan-designer/index.html"', index)

    def test_all_requested_models_are_available(self) -> None:
        script = (TOOL / "app.js").read_text(encoding="utf-8")
        for model in (
            "普通操作台",
            "冷藏操作台",
            "冷冻操作台",
            "货架",
            "烤箱",
            "烤炉",
            "电磁炉",
            "水池",
            "四门冰箱",
            "柱子",
            "门",
        ):
            with self.subTest(model=model):
                self.assertIn(f'name: "{model}"', script)

    def test_core_precision_features_are_present(self) -> None:
        page = (TOOL / "index.html").read_text(encoding="utf-8")
        script = (TOOL / "app.js").read_text(encoding="utf-8")
        for element_id in (
            "roomTypeInput",
            "roomWidthInput",
            "roomHeightInput",
            "bottomWidthInput",
            "rightDepthInput",
            "roomAlignmentInput",
            "gridSizeInput",
            "itemWidthInput",
            "itemHeightInput",
            "selectedRotationInput",
            "selectedDoorSwingInput",
            "rotateLeftButton",
            "rotateRightButton",
            "planCanvas",
            "exportButton",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("function snap(", script)
        self.assertIn("function roomGeometry(", script)
        self.assertIn("function pointInsideRoom(", script)
        self.assertIn("function itemFits(", script)
        self.assertIn("function adjustRotation(", script)
        self.assertIn("function nudgeSelected(", script)
        self.assertIn("ArrowUp", script)
        self.assertIn("localStorage.setItem", script)
        self.assertIn("function exportImage(", script)


if __name__ == "__main__":
    unittest.main()
