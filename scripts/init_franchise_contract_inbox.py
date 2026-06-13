from __future__ import annotations

import argparse
import csv
from pathlib import Path

from build_tool_warehouse_status import FRANCHISE_REQUIRED_FIELDS, FRANCHISE_TEMPLATE_DIR


ROOT = Path(__file__).resolve().parents[1]
FIELD_TEMPLATE_PATH = FRANCHISE_TEMPLATE_DIR / "templates" / "field_template.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化加盟合同模板接收目录和字段清单；不生成正式合同。")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的字段清单模板。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    FRANCHISE_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    keep = FRANCHISE_TEMPLATE_DIR / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")

    FIELD_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.overwrite or not FIELD_TEMPLATE_PATH.exists():
        with FIELD_TEMPLATE_PATH.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["字段", "示例值", "是否必填", "备注"])
            for field in FRANCHISE_REQUIRED_FIELDS:
                writer.writerow([field, "", "是", ""])
        FIELD_TEMPLATE_PATH.chmod(0o644)

    print("加盟合同模板接收目录已准备：franchise-contract-generator/")
    print(f"字段清单模板：{FIELD_TEMPLATE_PATH.relative_to(ROOT)}")
    print("正式合同模板请放在 franchise-contract-generator/ 根目录，支持 .docx、.pdf、.pages、.txt、.md。")
    print("下一步运行：python3 scripts/build_tool_warehouse_status.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
