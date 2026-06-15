from __future__ import annotations

import os
from urllib import parse, request


BASE_URL = os.environ.get("DAILY_ORDER_BASE_URL", "http://127.0.0.1:8010")
TOKEN = os.environ.get("DAILY_ORDER_ADMIN_TOKEN", "daily-order-admin")


def main() -> None:
    query = parse.urlencode({"token": TOKEN})
    url = f"{BASE_URL}/daily-order/api/admin/wechat-digest/send?{query}"
    req = request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=30) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
