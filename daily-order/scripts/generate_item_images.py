from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "catalog.json"
IMAGE_DIR = ROOT / "static" / "images"

PALETTES = {
    "veg": ("#f4fbf1", "#4f9d55", "#d7ead1", "#2e6b37"),
    "grain": ("#fff8e7", "#d2a84b", "#f2dc9b", "#8a6422"),
    "sauce": ("#fff3ec", "#b85c38", "#f1b08b", "#6d3521"),
    "drink": ("#eef7ff", "#3a86c8", "#a8d4f5", "#1f4f78"),
    "meat": ("#fff0f2", "#c75665", "#f1a4ad", "#7d2e39"),
    "pack": ("#f2f6fb", "#6d7f93", "#dbe4ee", "#34465c"),
}


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for item in catalog["items"]:
        sku = item["sku"]
        name = item["name"]
        filename = f"{sku}.svg"
        (IMAGE_DIR / filename).write_text(render_svg(name), encoding="utf-8")
        item["image"] = f"/daily-order/static/images/{filename}"
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_svg(name: str) -> str:
    kind = classify(name)
    bg, main, pale, dark = PALETTES[kind]
    shape = shape_for(kind, name, main, pale, dark)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" role="img" aria-label="{escape(name)}">
  <rect width="240" height="240" rx="28" fill="{bg}"/>
  <ellipse cx="120" cy="194" rx="68" ry="13" fill="#000" opacity=".08"/>
  {shape}
</svg>
"""


def classify(name: str) -> str:
    if re.search(r"洋葱|菇|玉米|土豆|圣女果|豆腐|胡萝卜|大蒜|海藻|椒|辣白菜|裙带菜|芝麻", name):
        return "veg"
    if re.search(r"大米|黑米|燕麦|白糖|盐|淀粉", name):
        return "grain"
    if re.search(r"酱|汤料|罐头|黑胡椒|海盐|木鱼精|鱼露|鸡粉|油|生抽|辣椒粉", name):
        return "sauce"
    if re.search(r"红酒|葡萄酒|牛奶|黄油|淡奶油", name):
        return "drink"
    if re.search(r"鸡蛋|虾仁", name):
        return "meat"
    return "pack"


def shape_for(kind: str, name: str, main: str, pale: str, dark: str) -> str:
    if "鸡蛋" in name:
        return eggs(main, pale, dark)
    if "虾仁" in name:
        return shrimp(main, pale, dark)
    if kind == "veg":
        return produce(main, pale, dark)
    if kind == "grain":
        return bag(main, pale, dark)
    if kind == "sauce":
        return jar(main, pale, dark)
    if kind == "drink":
        return bottle(main, pale, dark)
    return package(main, pale, dark)


def produce(main: str, pale: str, dark: str) -> str:
    return f"""
  <path d="M123 47c13 16 10 35-4 48-14-13-18-32-4-48 3-4 5-4 8 0Z" fill="{dark}"/>
  <circle cx="102" cy="124" r="46" fill="{main}"/>
  <circle cx="137" cy="130" r="51" fill="{pale}"/>
  <path d="M78 119c19-19 54-28 90-10" fill="none" stroke="#fff" stroke-width="7" opacity=".55" stroke-linecap="round"/>
  <path d="M91 154c22 12 51 12 77-2" fill="none" stroke="{dark}" stroke-width="6" opacity=".22" stroke-linecap="round"/>
"""


def bag(main: str, pale: str, dark: str) -> str:
    return f"""
  <path d="M78 74h84l15 110H63L78 74Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M86 74c5-20 62-20 68 0" fill="none" stroke="{dark}" stroke-width="7" stroke-linecap="round"/>
  <path d="M82 116h76M78 142h84" stroke="{main}" stroke-width="10" opacity=".7" stroke-linecap="round"/>
  <circle cx="103" cy="166" r="6" fill="{dark}" opacity=".45"/>
  <circle cx="124" cy="166" r="6" fill="{dark}" opacity=".45"/>
  <circle cx="145" cy="166" r="6" fill="{dark}" opacity=".45"/>
"""


def jar(main: str, pale: str, dark: str) -> str:
    return f"""
  <rect x="83" y="52" width="74" height="25" rx="7" fill="{dark}"/>
  <rect x="74" y="75" width="92" height="111" rx="23" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <path d="M82 122c22-15 54-15 76 0v42H82v-42Z" fill="{main}" opacity=".82"/>
  <path d="M93 98h54" stroke="#fff" stroke-width="8" opacity=".55" stroke-linecap="round"/>
"""


def bottle(main: str, pale: str, dark: str) -> str:
    return f"""
  <rect x="101" y="43" width="38" height="35" rx="8" fill="{dark}"/>
  <path d="M92 75h56l13 27v76c0 11-9 20-20 20H99c-11 0-20-9-20-20v-76l13-27Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M83 126h74v45H83z" fill="{main}" opacity=".75"/>
  <path d="M101 92h38" stroke="#fff" stroke-width="8" opacity=".6" stroke-linecap="round"/>
"""


def eggs(main: str, pale: str, dark: str) -> str:
    return f"""
  <ellipse cx="91" cy="139" rx="32" ry="48" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <ellipse cx="139" cy="132" rx="35" ry="54" fill="#fff7df" stroke="{dark}" stroke-width="5"/>
  <path d="M72 171c33 20 77 21 108 0" fill="none" stroke="{main}" stroke-width="10" opacity=".45" stroke-linecap="round"/>
"""


def shrimp(main: str, pale: str, dark: str) -> str:
    return f"""
  <path d="M73 137c13-45 79-64 107-21 20 31-5 62-37 56-19-4-28-19-25-36" fill="none" stroke="{main}" stroke-width="22" stroke-linecap="round"/>
  <path d="M88 122c16 20 40 29 70 27" fill="none" stroke="#fff" stroke-width="5" opacity=".65" stroke-linecap="round"/>
  <circle cx="170" cy="108" r="5" fill="{dark}"/>
  <path d="M177 116l24-12M174 127l27 8" stroke="{dark}" stroke-width="5" stroke-linecap="round"/>
"""


def package(main: str, pale: str, dark: str) -> str:
    return f"""
  <path d="M68 88l52-28 52 28v84l-52 28-52-28V88Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M68 88l52 29 52-29M120 117v83" fill="none" stroke="{dark}" stroke-width="5" opacity=".5"/>
  <path d="M92 102l52-28" stroke="#fff" stroke-width="8" opacity=".55" stroke-linecap="round"/>
  <path d="M82 151h76" stroke="{main}" stroke-width="12" opacity=".65" stroke-linecap="round"/>
"""


def escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
