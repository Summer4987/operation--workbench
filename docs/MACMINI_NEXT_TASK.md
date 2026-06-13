# Mac mini 下一步任务

## 当前任务：试跑美团 CDP 账户页余额探针

目的：

- 在美团推广页内只尝试进入“我的账户 / 账户余额 / 账户管理 / 充值”这类只读入口。
- 重新捕获页面文本、候选接口和疑似余额字段。
- 只生成旁路测试文件，不覆盖正式 `store-inspection/latest.json`。

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
- 不要运行上午运营任务。
- 不要运行日报、评价、预算提交或云端发布。
- 只允许点击这些只读入口文字：`我的账户`、`账户余额`、`账户管理`、`账户中心`、`充值`。
- 不要点击任何保存、提交、确定、提现、转账、预算设置、批量类按钮。
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

latest = json.loads(Path("store-inspection/meituan-cdp-latest.json").read_text(encoding="utf-8"))
print("status:", latest.get("status"))
print("summary:", json.dumps(latest.get("summary", {}), ensure_ascii=False, indent=2))
print("message:", latest.get("message", ""))
for item in latest.get("items", [])[:8]:
    compact = {
        "store_name": item.get("store_name"),
        "balance": item.get("balance"),
        "error": item.get("error"),
        "account_link_clicked": item.get("account_link_clicked"),
        "page_url": item.get("page_url"),
        "page_text_preview": item.get("page_text_preview", "")[:500],
    }
    print("item:", json.dumps(compact, ensure_ascii=False))

match_path = Path("store-inspection/meituan-cdp-network-matches.json")
matches = json.loads(match_path.read_text(encoding="utf-8")) if match_path.exists() else []
print("network_match_count:", len(matches))
for item in matches[:20]:
    compact = {
        "store_name": item.get("store_name"),
        "wm_poi_id": item.get("wm_poi_id"),
        "url": item.get("url"),
        "status": item.get("status"),
        "matches": item.get("matches", [])[:15],
        "snippet": item.get("snippet", "")[:700],
    }
    print("match:", json.dumps(compact, ensure_ascii=False))
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
6. 前 8 条门店样例，尤其是 `account_link_clicked`、`page_url`、`page_text_preview`；
7. 字段命中数量和前 20 条字段命中摘要；
8. `git status --short --ignored`，确认测试产物被忽略；
9. 确认没有运行旧余额巡检、没有截图/OCR、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

如果“账户页”暴露余额字段，下一步就把美团解析改成接口/页面数据读取。如果仍没有余额字段，则需要继续定位美团账户页真实路由或接口。
