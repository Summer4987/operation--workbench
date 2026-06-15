from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "catalog.json"
IMAGE_DIR = ROOT / "static" / "images"

PALETTES = [
    ("#f7fbf3", "#4f9d55", "#2f6f38", "#d9efcf"),
    ("#fff8ec", "#d4872f", "#8a4f18", "#f4d49b"),
    ("#f2fbff", "#3d8ec7", "#1e5b82", "#cce8f8"),
    ("#fff1f3", "#d95b68", "#87313b", "#f5bdc5"),
    ("#f7f4ff", "#8064c9", "#493785", "#ddd2fa"),
    ("#f4fbf8", "#2f9b83", "#1d6658", "#c9eee4"),
    ("#fff7df", "#c7a233", "#725b17", "#f1dfa0"),
    ("#f6f8fb", "#6e7f91", "#34465c", "#dce5ee"),
]


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for index, item in enumerate(catalog["items"]):
        filename = f"{item['sku']}.svg"
        (IMAGE_DIR / filename).write_text(render_icon(item, index), encoding="utf-8")
        item["image"] = f"/daily-order/static/images/{filename}"
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_icon(item: dict, index: int) -> str:
    name = item["name"]
    bg, main, dark, pale = colors_for(item, index)
    body = shape_for(item, index, main, dark, pale)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" role="img" aria-label="{escape(name)}">
  <rect width="240" height="240" rx="30" fill="#fff"/>
  <rect x="8" y="8" width="224" height="224" rx="26" fill="{bg}" stroke="#e3ebf3" stroke-width="2"/>
  <circle cx="196" cy="42" r="18" fill="{main}" opacity=".12"/>
  <ellipse cx="120" cy="196" rx="62" ry="12" fill="#17202a" opacity=".08"/>
  {body}
</svg>
"""


def colors_for(item: dict, index: int) -> tuple[str, str, str, str]:
    digest = int(hashlib.sha1((item["sku"] + item["name"]).encode("utf-8")).hexdigest()[:8], 16)
    bg, main, dark, pale = PALETTES[(digest + index) % len(PALETTES)]
    return bg, main, dark, pale


def shape_for(item: dict, index: int, main: str, dark: str, pale: str) -> str:
    name = item["name"]
    if name == "洋葱":
        return onion(main, dark, pale)
    if name == "白玉菇":
        return mushroom(main, dark, pale)
    if name == "玉米粒":
        return corn(main, dark, pale)
    if name == "土豆":
        return potato(main, dark, pale)
    if name == "圣女果":
        return tomato(main, dark, pale)
    if name == "豆腐":
        return cube(main, dark, pale, diagonal=True)
    if name == "胡萝卜":
        return carrot(main, dark, pale)
    if name == "大蒜":
        return garlic(main, dark, pale)
    if name in {"冷冻海藻", "裙带菜"}:
        return seaweed(main, dark, pale, dense=name == "裙带菜")
    if name == "樟树椒":
        return pepper(main, dark, pale)
    if name == "鸡蛋":
        return eggs(main, dark, pale)
    if name == "芝麻":
        return sesame(main, dark, pale)
    if name in {"大米", "黑米", "燕麦米", "黑米/燕麦米", "白糖", "袋装盐（大袋）"}:
        return bag(main, dark, pale, seed=index)
    if name in {"味增酱", "焙煎芝麻酱", "鸡粉", "木鱼精", "翠宏辣椒粉", "黑胡椒粒", "大粒海盐", "汤料"}:
        return jar(main, dark, pale, seed=index)
    if name in {"鱼露", "厨邦酱油", "薄盐生抽", "大豆油", "香油"}:
        return bottle(main, dark, pale, seed=index)
    if name == "菠萝罐头":
        return can(main, dark, pale)
    if name in {"红酒", "白葡萄酒"}:
        return wine(main, dark, pale, white=name == "白葡萄酒")
    if name in {"牛奶", "淡奶油"}:
        return carton(main, dark, pale, cream=name == "淡奶油")
    if name == "黄油":
        return butter(main, dark, pale)
    if name == "辣白菜":
        return kimchi(main, dark, pale)
    if name == "虾仁":
        return shrimp(main, dark, pale)
    if name in {"一次性手套", "黑手套"}:
        return glove(main, dark, pale, black=name == "黑手套")
    if name == "餐具":
        return cutlery(main, dark, pale)
    if name in {"小塑料碗", "小牛皮纸碗", "汤碗"}:
        return bowl(main, dark, pale, seed=index)
    if name in {"塑料袋", "打包袋"}:
        return carry_bag(main, dark, pale, seed=index)
    if name in {"餐盒", "酱料盒", "玉米淀粉盒"}:
        return container(main, dark, pale, seed=index)
    if name == "订书针":
        return staples(main, dark, pale)
    if name == "打印纸":
        return paper(main, dark, pale)
    if name == "评价卡":
        return cards(main, dark, pale)
    if name in {"大垃圾袋", "小垃圾袋"}:
        return trash_bag(main, dark, pale, small=name == "小垃圾袋")
    if name == "网帽":
        return hairnet(main, dark, pale)
    if name == "纸抽":
        return tissue(main, dark, pale)
    if name == "洗洁精":
        return detergent(main, dark, pale)
    if name == "保鲜膜":
        return wrap(main, dark, pale)
    if name in {"海绵百洁布", "绿色百洁布"}:
        return sponge(main, dark, pale, green=name == "绿色百洁布")
    if name == "火碱":
        return caustic_soda(main, dark, pale)
    if name == "84消毒液":
        return disinfectant(main, dark, pale)
    if name == "抹布":
        return rag(main, dark, pale)
    if name == "围裙":
        return apron(main, dark, pale)
    if name == "拖把":
        return mop(main, dark, pale)
    return cube(main, dark, pale, diagonal=False)


def onion(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M126 49c13 17 9 36-5 47-13-12-17-30-4-47 3-5 6-5 9 0Z" fill="{dark}"/>
  <circle cx="104" cy="130" r="44" fill="#efe4b3" stroke="{dark}" stroke-width="5"/>
  <circle cx="139" cy="130" r="48" fill="#f9efc4" stroke="{dark}" stroke-width="5"/>
  <path d="M90 107c29-18 62-16 89 1M86 134c31 15 70 13 99-2" fill="none" stroke="#fff" stroke-width="8" opacity=".68" stroke-linecap="round"/>
  <path d="M111 173c24 7 47 4 67-7" fill="none" stroke="{main}" stroke-width="5" opacity=".45" stroke-linecap="round"/>"""


def mushroom(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M71 105c12-39 85-56 112 0 4 10-3 21-14 21H85c-11 0-18-11-14-21Z" fill="#f6eee3" stroke="{dark}" stroke-width="5"/>
  <path d="M99 124h55l13 59H86l13-59Z" fill="#fff8ee" stroke="{dark}" stroke-width="5"/>
  <path d="M91 126c18 13 55 17 80 0" fill="none" stroke="{main}" stroke-width="5" opacity=".45" stroke-linecap="round"/>
  <circle cx="104" cy="95" r="7" fill="{pale}"/><circle cx="140" cy="88" r="6" fill="{pale}"/><circle cx="130" cy="110" r="5" fill="{pale}"/>"""


def corn(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M84 70c52 4 84 40 78 104-50 0-86-37-78-104Z" fill="#ffd35c" stroke="{dark}" stroke-width="5"/>
  <path d="M88 106c21-9 48-8 71 5M94 136c18-7 42-6 63 4M112 83c-4 31 2 62 22 90M138 96c-9 28-8 54 4 76" fill="none" stroke="#fff5b2" stroke-width="6" stroke-linecap="round"/>
  <path d="M78 157c22 3 43 14 57 31-27 6-53-4-57-31Z" fill="{main}"/>"""


def potato(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M74 126c7-40 41-67 82-54 34 11 46 48 23 81-24 35-82 43-103 8-6-10-6-22-2-35Z" fill="#c99a5b" stroke="{dark}" stroke-width="5"/>
  <circle cx="113" cy="111" r="5" fill="{dark}" opacity=".45"/><circle cx="149" cy="132" r="5" fill="{dark}" opacity=".45"/><circle cx="113" cy="154" r="4" fill="{dark}" opacity=".45"/>
  <path d="M93 101c20-20 54-26 77-2" fill="none" stroke="{pale}" stroke-width="8" opacity=".55" stroke-linecap="round"/>"""


def tomato(main: str, dark: str, pale: str) -> str:
    return f"""<circle cx="119" cy="132" r="58" fill="#e94f45" stroke="{dark}" stroke-width="5"/>
  <path d="M119 75l10 24 26-12-14 24 27 8-29 5 12 25-23-17-16 23-1-29-28 8 22-18-22-18 29 5 7-28Z" fill="{main}"/>
  <path d="M91 111c19-20 51-25 77-9" fill="none" stroke="#ffaaa2" stroke-width="9" opacity=".65" stroke-linecap="round"/>"""


def cube(main: str, dark: str, pale: str, diagonal: bool) -> str:
    extra = f'<path d="M91 151h58" stroke="{main}" stroke-width="10" opacity=".55" stroke-linecap="round"/>' if diagonal else ""
    return f"""<path d="M76 98l54-27 55 27v73l-55 28-54-28V98Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M76 98l54 28 55-28M130 126v73" fill="none" stroke="{dark}" stroke-width="5" opacity=".65"/>
  <path d="M96 104l54-27" stroke="#fff" stroke-width="8" opacity=".7" stroke-linecap="round"/>{extra}"""


def carrot(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M110 69c-7 39-22 78-45 121 48-20 82-47 109-87-25-7-43-17-64-34Z" fill="#f28a2e" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M111 66c-18-22-32-28-51-22 13 17 25 25 49 30M122 65c20-21 36-26 54-17-15 15-31 23-53 25" fill="none" stroke="{main}" stroke-width="8" stroke-linecap="round"/>
  <path d="M96 111l30 10M83 139l28 10M70 166l24 7" stroke="{pale}" stroke-width="5" opacity=".75" stroke-linecap="round"/>"""


def garlic(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M120 61c11 21 17 44 14 66h-28c-2-23 3-45 14-66Z" fill="{main}"/>
  <path d="M72 129c4-37 25-58 48-58s44 21 48 58c4 43-18 68-48 68s-52-25-48-68Z" fill="#f6eee0" stroke="{dark}" stroke-width="5"/>
  <path d="M98 93c-12 23-14 64 0 92M121 85c-7 32-7 69 0 104M144 94c10 24 12 63-1 91" fill="none" stroke="{pale}" stroke-width="5" stroke-linecap="round"/>"""


def seaweed(main: str, dark: str, pale: str, dense: bool) -> str:
    extra = f'<path d="M101 178c10-42 51-55 50-105" fill="none" stroke="{pale}" stroke-width="9" stroke-linecap="round"/>' if dense else ""
    return f"""<path d="M81 181c16-33 1-70 22-111 27 34 5 72 21 111" fill="none" stroke="{dark}" stroke-width="15" stroke-linecap="round"/>
  <path d="M124 184c8-39 39-61 37-111 25 33 9 78-7 111" fill="none" stroke="{main}" stroke-width="14" stroke-linecap="round"/>{extra}
  <path d="M67 179c22 10 75 14 111 0" fill="none" stroke="{dark}" stroke-width="9" opacity=".5" stroke-linecap="round"/>"""


def pepper(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M84 83c34-10 72 14 85 50 10 30-4 57-32 65-33-45-54-80-53-115Z" fill="{main}" stroke="{dark}" stroke-width="5"/>
  <path d="M89 82c-17-12-26-25-21-39 23 5 38 16 47 37" fill="none" stroke="{dark}" stroke-width="8" stroke-linecap="round"/>
  <path d="M103 108c21 17 35 42 40 71" fill="none" stroke="{pale}" stroke-width="7" opacity=".6" stroke-linecap="round"/>"""


def eggs(main: str, dark: str, pale: str) -> str:
    return f"""<ellipse cx="92" cy="139" rx="34" ry="49" fill="#f6ead4" stroke="{dark}" stroke-width="5"/>
  <ellipse cx="143" cy="132" rx="36" ry="55" fill="#fff6df" stroke="{dark}" stroke-width="5"/>
  <path d="M72 172c33 20 82 20 113 0" fill="none" stroke="{main}" stroke-width="9" opacity=".55" stroke-linecap="round"/>"""


def sesame(main: str, dark: str, pale: str) -> str:
    seeds = "".join(
        f'<ellipse cx="{x}" cy="{y}" rx="7" ry="11" fill="{pale}" stroke="{dark}" stroke-width="2" transform="rotate({r} {x} {y})"/>'
        for x, y, r in [(89, 99, -30), (117, 91, 20), (145, 102, 55), (103, 128, 45), (134, 134, -25), (84, 151, 10), (160, 154, 35), (121, 167, -45)]
    )
    return seeds + f'<path d="M73 183c36 13 76 13 113 0" stroke="{main}" stroke-width="8" opacity=".45" stroke-linecap="round"/>'


def bag(main: str, dark: str, pale: str, seed: int) -> str:
    band_y = 116 + (seed % 3) * 12
    return f"""<path d="M76 78h88l16 111H60L76 78Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M87 78c7-22 59-22 66 0" fill="none" stroke="{dark}" stroke-width="7" stroke-linecap="round"/>
  <path d="M84 {band_y}h74M80 {band_y + 27}h82" stroke="{main}" stroke-width="9" opacity=".62" stroke-linecap="round"/>
  <circle cx="{101 + seed % 16}" cy="169" r="6" fill="{dark}" opacity=".32"/><circle cx="{130 + seed % 12}" cy="169" r="6" fill="{dark}" opacity=".32"/>"""


def jar(main: str, dark: str, pale: str, seed: int) -> str:
    level = 123 + seed % 12
    return f"""<rect x="84" y="53" width="73" height="24" rx="7" fill="{dark}"/>
  <rect x="74" y="76" width="92" height="111" rx="23" fill="#fff7eb" stroke="{dark}" stroke-width="5"/>
  <path d="M82 {level}c24-14 52-14 76 0v{166-level}H82v-{166-level}Z" fill="{main}" opacity=".82"/>
  <path d="M94 98h52" stroke="#fff" stroke-width="8" opacity=".65" stroke-linecap="round"/>
  <circle cx="{104 + seed % 34}" cy="148" r="6" fill="#fff" opacity=".6"/>"""


def bottle(main: str, dark: str, pale: str, seed: int) -> str:
    return f"""<rect x="101" y="45" width="38" height="34" rx="7" fill="{dark}"/>
  <path d="M90 78h60l13 28v73c0 12-9 21-21 21H98c-12 0-21-9-21-21v-73l13-28Z" fill="#eef5fb" stroke="{dark}" stroke-width="5"/>
  <path d="M82 {124 + seed % 10}h76v45H82z" fill="{main}" opacity=".85"/>
  <path d="M99 96h42" stroke="#fff" stroke-width="8" opacity=".65" stroke-linecap="round"/>"""


def can(main: str, dark: str, pale: str) -> str:
    return f"""<ellipse cx="120" cy="73" rx="46" ry="15" fill="#d9e3ec" stroke="{dark}" stroke-width="5"/>
  <path d="M74 73v103c0 9 21 17 46 17s46-8 46-17V73" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <ellipse cx="120" cy="176" rx="46" ry="15" fill="{main}" opacity=".55" stroke="{dark}" stroke-width="5"/>
  <path d="M89 116h62v36H89z" fill="#ffffff" opacity=".75"/>"""


def wine(main: str, dark: str, pale: str, white: bool) -> str:
    liquid = "#e6d37c" if white else "#7d2030"
    return f"""<rect x="104" y="44" width="32" height="42" rx="7" fill="{dark}"/>
  <path d="M92 83h56l13 27v70c0 12-9 20-20 20H99c-11 0-20-8-20-20v-70l13-27Z" fill="#dae6ef" stroke="{dark}" stroke-width="5"/>
  <path d="M84 131h72v43H84z" fill="{liquid}" opacity=".92"/>
  <path d="M103 101h34" stroke="#fff" stroke-width="8" opacity=".65" stroke-linecap="round"/>"""


def carton(main: str, dark: str, pale: str, cream: bool) -> str:
    color = "#f8df9a" if cream else "#9ed0f2"
    return f"""<path d="M82 76l38-28 39 28v112H82V76Z" fill="#edf6ff" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M82 76h77M120 48v140" fill="none" stroke="{dark}" stroke-width="5" opacity=".55"/>
  <path d="M91 120h59v44H91z" fill="{color}" opacity=".9"/>"""


def butter(main: str, dark: str, pale: str) -> str:
    return cube("#f1c84c", dark, "#ffe9a5", True)


def kimchi(main: str, dark: str, pale: str) -> str:
    return jar("#e24a35", dark, "#ffd8cb", 4)


def shrimp(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M73 137c13-45 79-64 107-21 20 31-5 62-37 56-19-4-28-19-25-36" fill="none" stroke="#f08a78" stroke-width="22" stroke-linecap="round"/>
  <path d="M88 122c16 20 40 29 70 27" fill="none" stroke="#fff" stroke-width="5" opacity=".7" stroke-linecap="round"/>
  <circle cx="170" cy="108" r="5" fill="{dark}"/><path d="M177 116l24-12M174 127l27 8" stroke="{dark}" stroke-width="5" stroke-linecap="round"/>"""


def glove(main: str, dark: str, pale: str, black: bool) -> str:
    color = "#111827" if black else "#dce8f2"
    return f"""<path d="M82 164V87c0-12 16-12 16 0v49h8V67c0-12 17-12 17 0v69h8V73c0-12 17-12 17 0v65h7V92c0-11 16-11 16 0v68c0 25-20 42-45 42h-4c-25 0-40-14-40-38Z" fill="{color}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M91 173c22 10 45 10 66 0" stroke="#ffffff" stroke-width="6" opacity=".25" stroke-linecap="round"/>"""


def cutlery(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M87 55v123M75 55v42M99 55v42" stroke="{dark}" stroke-width="8" stroke-linecap="round"/>
  <path d="M75 97c0 18 24 18 24 0" fill="none" stroke="{dark}" stroke-width="8"/>
  <path d="M143 56c24 18 24 48 0 66v58" fill="none" stroke="{main}" stroke-width="10" stroke-linecap="round"/>"""


def bowl(main: str, dark: str, pale: str, seed: int) -> str:
    return f"""<path d="M67 112h106l-18 67H85L67 112Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <ellipse cx="120" cy="112" rx="56" ry="17" fill="#fff" stroke="{dark}" stroke-width="5"/>
  <path d="M83 {135 + seed % 8}c25 14 52 14 78 0" fill="none" stroke="{main}" stroke-width="7" stroke-linecap="round"/>"""


def carry_bag(main: str, dark: str, pale: str, seed: int) -> str:
    return f"""<path d="M78 87h84l13 96H65L78 87Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M94 88c4-26 48-26 52 0" fill="none" stroke="{dark}" stroke-width="7" stroke-linecap="round"/>
  <path d="M84 {127 + seed % 18}h72" stroke="{main}" stroke-width="11" opacity=".55" stroke-linecap="round"/>"""


def container(main: str, dark: str, pale: str, seed: int) -> str:
    return f"""<path d="M72 91h96l14 35-15 57H73l-15-57 14-35Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M72 91c20 18 73 18 96 0M61 126h119" fill="none" stroke="{dark}" stroke-width="5" opacity=".5"/>
  <path d="M88 {150 + seed % 10}h65" stroke="{main}" stroke-width="10" opacity=".6" stroke-linecap="round"/>"""


def staples(main: str, dark: str, pale: str) -> str:
    return f"""<rect x="71" y="85" width="98" height="82" rx="12" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <path d="M91 116h58M91 137h58" stroke="{main}" stroke-width="8" stroke-linecap="round"/>
  <path d="M83 180c25 10 54 10 79 0" stroke="{dark}" stroke-width="6" opacity=".35" stroke-linecap="round"/>"""


def paper(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M82 69h84v112H74V77l8-8Z" fill="#fff" stroke="{dark}" stroke-width="5"/>
  <path d="M82 69v17H65" fill="none" stroke="{dark}" stroke-width="5"/>
  <path d="M96 111h50M96 134h50M96 157h38" stroke="{main}" stroke-width="7" opacity=".7" stroke-linecap="round"/>"""


def cards(main: str, dark: str, pale: str) -> str:
    return f"""<rect x="75" y="80" width="90" height="110" rx="10" fill="{pale}" stroke="{dark}" stroke-width="5" transform="rotate(-7 120 135)"/>
  <rect x="91" y="65" width="84" height="108" rx="10" fill="#fff" stroke="{dark}" stroke-width="5" transform="rotate(8 133 119)"/>
  <path d="M105 105h48M110 129h42" stroke="{main}" stroke-width="8" stroke-linecap="round"/>"""


def trash_bag(main: str, dark: str, pale: str, small: bool) -> str:
    height = 78 if small else 105
    return f"""<path d="M94 {185-height}c-14 24-20 52-16 {height}h84c5-31-2-62-17-{height}l-12 18-13-25-14 25-12-18Z" fill="#2d3745" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M91 151c25 11 55 10 82-2" stroke="#fff" stroke-width="7" opacity=".2" stroke-linecap="round"/>"""


def hairnet(main: str, dark: str, pale: str) -> str:
    return f"""<ellipse cx="120" cy="132" rx="62" ry="45" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <path d="M67 132h106M80 107c27 22 53 45 80 73M160 107c-27 22-53 45-80 73M120 88v89" stroke="{main}" stroke-width="5" opacity=".65" stroke-linecap="round"/>"""


def tissue(main: str, dark: str, pale: str) -> str:
    return f"""<rect x="67" y="105" width="106" height="73" rx="12" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <path d="M96 106c7-28 41-28 48 0" fill="#fff" stroke="{dark}" stroke-width="5"/>
  <path d="M90 141h60" stroke="{main}" stroke-width="8" opacity=".6" stroke-linecap="round"/>"""


def detergent(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M95 62h50l11 36v82c0 12-10 22-22 22h-29c-12 0-22-10-22-22V98l12-36Z" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <rect x="101" y="44" width="38" height="22" rx="7" fill="{main}"/>
  <path d="M88 127h64v46H88z" fill="{main}" opacity=".65"/>
  <circle cx="107" cy="111" r="6" fill="#fff" opacity=".7"/><circle cx="132" cy="102" r="5" fill="#fff" opacity=".7"/>"""


def wrap(main: str, dark: str, pale: str) -> str:
    return f"""<ellipse cx="120" cy="84" rx="47" ry="22" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <path d="M73 84v82c0 12 21 23 47 23s47-11 47-23V84" fill="{pale}" stroke="{dark}" stroke-width="5"/>
  <ellipse cx="120" cy="166" rx="47" ry="22" fill="#fff" stroke="{dark}" stroke-width="5"/>
  <ellipse cx="120" cy="166" rx="18" ry="8" fill="{main}" opacity=".45"/>"""


def sponge(main: str, dark: str, pale: str, green: bool) -> str:
    scrub = "#278f5a" if green else "#2f6f38"
    foam = "#f0c94a" if not green else "#b7df69"
    return f"""<path d="M69 104l94-31 31 49-95 31-30-49Z" fill="{foam}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M99 153l95-31v43l-95 32-30-43v-50l30 49Z" fill="{scrub}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M88 107l27 40M115 98l27 40M142 89l27 40M97 174l82-27" stroke="#fff" stroke-width="5" opacity=".42" stroke-linecap="round"/>
  <circle cx="100" cy="122" r="5" fill="#fff" opacity=".55"/><circle cx="135" cy="112" r="4" fill="#fff" opacity=".55"/><circle cx="160" cy="139" r="5" fill="#fff" opacity=".5"/>"""


def caustic_soda(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M82 88h76l15 95H67l15-95Z" fill="#f7f7ee" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M92 64h56l10 24H82l10-24Z" fill="{main}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M120 112l33 55H87l33-55Z" fill="#fff4b8" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M120 130v18" stroke="{dark}" stroke-width="7" stroke-linecap="round"/><circle cx="120" cy="158" r="5" fill="{dark}"/>
  <path d="M93 183c25 9 54 9 79 0" stroke="{main}" stroke-width="7" opacity=".55" stroke-linecap="round"/>"""


def disinfectant(main: str, dark: str, pale: str) -> str:
    return f"""<rect x="93" y="51" width="54" height="30" rx="8" fill="{dark}"/>
  <path d="M84 80h72l14 28v74c0 12-10 21-22 21h-56c-12 0-22-9-22-21v-74l14-28Z" fill="#eef8fb" stroke="{dark}" stroke-width="5"/>
  <path d="M81 128h78v43H81z" fill="{main}" opacity=".75"/>
  <path d="M120 107v64M96 139h48" stroke="#fff" stroke-width="10" opacity=".78" stroke-linecap="round"/>
  <path d="M100 94h40" stroke="{pale}" stroke-width="7" opacity=".8" stroke-linecap="round"/>"""


def rag(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M69 101c30-25 72 11 103-12 11 30-7 58 1 92-35-11-69 14-105-5 16-23-7-48 1-75Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M83 121c26 11 54 6 80-10M82 151c27 11 57 7 84-6M98 97c-6 25-4 54 8 84M133 102c-4 23-3 46 8 69" fill="none" stroke="{main}" stroke-width="6" opacity=".62" stroke-linecap="round"/>
  <circle cx="91" cy="170" r="5" fill="#fff" opacity=".65"/>"""


def apron(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M101 61h39c0 27 15 45 28 58l-14 78H86l-14-78c14-13 29-31 29-58Z" fill="{pale}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M104 62c4 27 28 27 33 0M77 122c-18 4-28 17-33 34M163 122c18 4 28 17 33 34" fill="none" stroke="{dark}" stroke-width="7" stroke-linecap="round"/>
  <path d="M95 138h50v39H95z" fill="{main}" opacity=".65" stroke="{dark}" stroke-width="4"/>
  <path d="M96 101h49" stroke="#fff" stroke-width="8" opacity=".55" stroke-linecap="round"/>"""


def mop(main: str, dark: str, pale: str) -> str:
    return f"""<path d="M150 52L96 155" stroke="{dark}" stroke-width="10" stroke-linecap="round"/>
  <path d="M97 150l44 23-19 28-50-26 25-25Z" fill="{main}" stroke="{dark}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M79 177l-18 25M94 183l-12 27M110 188l-5 25M126 188l8 22M138 179l18 20" stroke="{pale}" stroke-width="8" stroke-linecap="round"/>
  <path d="M144 62l19-15" stroke="#fff" stroke-width="5" opacity=".55" stroke-linecap="round"/>"""


def escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
