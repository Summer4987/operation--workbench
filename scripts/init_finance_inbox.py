from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config" / "finance_bill_schema.json"
TEMPLATE_DIR = ROOT / "data" / "finance-inbox" / "templates"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_template(path: Path, fields: list[str], overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerow([f"示例{index + 1}" for index, _ in enumerate(fields)])
    path.chmod(0o644)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化财务账单样例接收目录和字段模板；不写入真实账单。")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的模板文件。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    schema = read_json(SCHEMA_PATH)
    inbox = schema.get("sample_inbox") or {}
    created_dirs = []
    template_results = []
    for source in schema.get("required_sources") or []:
        source_id = source.get("id") or ""
        path_text = inbox.get(source_id) or f"data/finance-inbox/{source_id}"
        inbox_dir = ROOT / path_text
        inbox_dir.mkdir(parents=True, exist_ok=True)
        keep = inbox_dir / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
        created_dirs.append(path_text)

        fields = [str(field) for field in source.get("required_fields") or []]
        template_path = TEMPLATE_DIR / f"{source_id}_template.csv"
        wrote = write_template(template_path, fields, args.overwrite)
        template_results.append((str(template_path.relative_to(ROOT)), wrote))

    print("财务账单接收目录已准备：")
    for path_text in created_dirs:
        print(f"- {path_text}")
    print("字段模板：")
    for path_text, wrote in template_results:
        print(f"- {path_text} {'已写入' if wrote else '已存在'}")
    print("下一步运行：python3 scripts/build_finance_center_status.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
