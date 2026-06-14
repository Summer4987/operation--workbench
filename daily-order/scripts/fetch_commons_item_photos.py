from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "catalog.json"
IMAGE_DIR = ROOT / "static" / "images"
CREDITS_PATH = ROOT / "static" / "image-credits.json"
API_URL = "https://commons.wikimedia.org/w/api.php"

QUERY_OVERRIDES = {
    "洋葱": "onion vegetable",
    "白玉菇": "beech mushroom",
    "玉米粒": "corn kernels",
    "土豆": "potato",
    "圣女果": "cherry tomato",
    "豆腐": "tofu",
    "胡萝卜": "carrot",
    "大蒜": "garlic bulb",
    "冷冻海藻": "wakame seaweed",
    "樟树椒": "green chili pepper",
    "鸡蛋": "chicken eggs",
    "芝麻": "sesame seeds",
    "焙煎芝麻酱": "tahini jar",
    "鱼露": "fish sauce bottle",
    "鸡粉": "bouillon powder jar",
    "大豆油": "soybean oil bottle",
    "香油": "sesame oil bottle",
    "白糖": "white sugar",
    "袋装盐（大袋）": "salt bag",
    "厨邦酱油": "soy sauce bottle condiment",
    "薄盐生抽": "soy sauce bottle condiment",
    "翠宏辣椒粉": "chili powder",
    "大垃圾袋": "black garbage bags roll",
    "小垃圾袋": "plastic trash bag roll",
    "网帽": "disposable hair net",
    "纸抽": "facial tissue box",
    "洗洁精": "dishwashing liquid bottle",
    "保鲜膜": "plastic wrap roll",
    "味增酱": "miso paste",
    "裙带菜": "wakame seaweed",
    "汤料": "soup base packet",
    "菠萝罐头": "canned pineapple",
    "红酒": "red wine bottle",
    "白葡萄酒": "white wine bottle",
    "黑胡椒粒": "black peppercorns",
    "大粒海盐": "sea salt crystals",
    "牛奶": "milk bottle",
    "黄油": "butter",
    "木鱼精": "katsuobushi package",
    "淡奶油": "cream carton",
    "一次性手套": "disposable gloves",
    "黑手套": "black disposable gloves",
    "塑料袋": "plastic bag roll",
    "订书针": "staples box",
    "打印纸": "printing paper ream",
    "评价卡": "comment card",
    "小牛皮纸碗": "paper bowl disposable",
    "汤碗": "paper soup bowl",
    "大米": "rice bag",
    "黑米/燕麦米": "black rice oats",
    "辣白菜": "kimchi",
    "虾仁": "shrimp",
    "玉米淀粉盒": "corn starch box",
    "小塑料碗": "plastic bowl",
    "餐具": "disposable cutlery",
    "餐盒": "takeaway food container",
    "酱料盒": "plastic sauce cup",
    "打包袋": "paper takeaway bag",
}


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    credits = json.loads(CREDITS_PATH.read_text(encoding="utf-8")) if CREDITS_PATH.exists() else []
    for item in catalog["items"]:
        image = item.get("image", "")
        if image.endswith((".jpg", ".jpeg", ".png")) and (ROOT / image.removeprefix("/daily-order/")).exists():
            continue
        query = QUERY_OVERRIDES.get(item["name"], item["name"])
        result = search_commons(query)
        if not result:
            print(f"MISS {item['sku']} {item['name']} {query}")
            continue
        suffix = ".jpg" if "jpeg" in result["mime"].lower() else ".png"
        filename = f"{item['sku']}{suffix}"
        path = IMAGE_DIR / filename
        download(result["thumburl"] or result["url"], path)
        item["image"] = f"/daily-order/static/images/{filename}"
        credits.append(
            {
                "sku": item["sku"],
                "name": item["name"],
                "source": "Wikimedia Commons",
                "title": result["title"],
                "url": result["descriptionurl"],
                "license": result["license"],
                "artist": clean_html(result["artist"]),
            }
        )
        CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        CREDITS_PATH.write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"OK {item['sku']} {item['name']} <- {result['title']}")
        time.sleep(1.2)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CREDITS_PATH.write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def search_commons(query: str) -> dict | None:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": query,
        "gsrlimit": "8",
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "360",
    }
    data = get_json(f"{API_URL}?{urlencode(params)}")
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime not in {"image/jpeg", "image/png"}:
            continue
        metadata = info.get("extmetadata") or {}
        return {
            "title": page.get("title", ""),
            "url": info.get("url", ""),
            "thumburl": info.get("thumburl", ""),
            "mime": mime,
            "descriptionurl": info.get("descriptionurl", ""),
            "license": (metadata.get("LicenseShortName") or {}).get("value", ""),
            "artist": (metadata.get("Artist") or {}).get("value", ""),
        }
    return None


def get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "daily-order-photo-fetch/1.0"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(6 + attempt * 4)
    raise RuntimeError("unreachable")


def download(url: str, path: Path) -> None:
    request = Request(url, headers={"User-Agent": "daily-order-photo-fetch/1.0"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                path.write_bytes(response.read())
                return
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(6 + attempt * 4)


def clean_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


if __name__ == "__main__":
    main()
