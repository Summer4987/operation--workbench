from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "config" / "promo_budget_overrides.json"
URL = os.environ.get("PROMO_BUDGET_OVERRIDES_URL", "http://139.155.148.169/api/promo-budget-overrides?token=xiongxiaoxiao-order")


def main() -> int:
    try:
        with urlopen(URL, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"云端预算配置读取失败，继续使用本地配置：{exc}")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已同步云端预算配置：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
