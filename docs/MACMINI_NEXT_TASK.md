# Mac mini 下一步任务

## 当前任务：试跑美团 CDP 账户余额 API 重试版

目的：

- 每家美团门店使用独立 CDP 页面，避免 SPA 缓存串门。
- 账户页 URL 增加探针时间戳，尽量强制触发 `/ad/v4/homepage/account/info`。
- 继续只生成旁路测试文件，不覆盖正式 `store-inspection/latest.json`。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
store-inspection/cdp_meituan_balance.py
```

允许运行的只读测试脚本：

```text
store-inspection/cdp_meituan_balance.py
```

允许生成的测试产物：

```text
store-inspection/meituan-cdp-latest.json
store-inspection/meituan-cdp-latest-data.js
store-inspection/meituan-cdp-network-candidates.json
store-inspection/meituan-cdp-network-matches.json
```

## 必须遵守

- 不要运行现有余额巡检。
- 不要截图、不要 OCR。
- 不要点击任何页面按钮。
- 不要运行上午运营任务。
- 不要运行日报、评价、预算提交或云端发布。
- 不要修改或 reload 任何定时任务。
- 不要提交、不要推送。
- 不要覆盖 `store-inspection/latest.json` 或 `store-inspection/latest-data.js`。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp "store-inspection/cdp_meituan_balance.py" "/Users/summer/Documents/New project/store-inspection/cdp_meituan_balance.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile "store-inspection/cdp_meituan_balance.py"

PYTHON="business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" "store-inspection/cdp_meituan_balance.py"

python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("store-inspection/meituan-cdp-latest.json").read_text(encoding="utf-8"))
print("status:", data.get("status"))
print("generated_at:", data.get("generated_at"))
print("summary:", json.dumps(data.get("summary", {}), ensure_ascii=False, indent=2))
print("message:", data.get("message", ""))
api_count = 0
for item in data.get("items", [])[:8]:
    if item.get("source") == "Chrome CDP接口读取":
        api_count += 1
    compact = {
        "store_name": item.get("store_name"),
        "store_id": item.get("store_id"),
        "balance": item.get("balance"),
        "status": item.get("status"),
        "source": item.get("source"),
        "error": item.get("error"),
        "account_response_url": item.get("account_response_url"),
        "page_url": item.get("page_url"),
    }
    print("item:", json.dumps(compact, ensure_ascii=False))
print("api_count:", api_count)
PY

git status --short --ignored -- store-inspection/cdp_meituan_balance.py store-inspection/meituan-cdp-latest.json store-inspection/meituan-cdp-latest-data.js store-inspection/meituan-cdp-network-candidates.json store-inspection/meituan-cdp-network-matches.json
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 脚本是否已同步；
3. Python 语法检查是否通过；
4. 脚本运行是否成功；
5. `meituan-cdp-latest.json` 的 `status`、`summary`、`message`；
6. 前 8 条门店余额样例；
7. `api_count`，也就是明确通过 `/ad/v4/homepage/account/info` 读取的门店数量；
8. `git status --short --ignored`，确认测试产物被忽略；
9. 确认没有运行旧余额巡检、没有截图/OCR、没有点击页面按钮、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

如果 `api_count` 提升到 8，说明美团余额已可以稳定从接口读取。若仍有门店走页面文本兜底或 0 元，再继续定位这些门店的切店/缓存问题。
