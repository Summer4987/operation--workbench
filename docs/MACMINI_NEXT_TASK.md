# Mac mini 下一步任务

## 当前任务：试跑美团 CDP 接口定位版余额探针

目的：

- 继续定位美团余额接口。
- 脚本会保存候选接口摘要，并递归提取疑似余额/账户/金额字段路径。
- 只生成旁路测试文件，不覆盖正式 `store-inspection/latest.json`。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
.gitignore
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
- 不要点击任何保存、提交、充值、提现、转账、预算设置、确定按钮。
- 不要修改或 reload 任何定时任务。
- 不要提交、不要推送。
- 不要覆盖 `store-inspection/latest.json` 或 `store-inspection/latest-data.js`。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp ".gitignore" "/Users/summer/Documents/New project/.gitignore"
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
    print("item:", json.dumps(item, ensure_ascii=False)[:1000])

candidate_path = Path("store-inspection/meituan-cdp-network-candidates.json")
match_path = Path("store-inspection/meituan-cdp-network-matches.json")
candidates = json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.exists() else []
matches = json.loads(match_path.read_text(encoding="utf-8")) if match_path.exists() else []
print("network_candidate_count:", len(candidates))
print("network_match_count:", len(matches))
for item in matches[:15]:
    compact = {
        "store_name": item.get("store_name"),
        "wm_poi_id": item.get("wm_poi_id"),
        "url": item.get("url"),
        "status": item.get("status"),
        "matches": item.get("matches", [])[:12],
        "snippet": item.get("snippet", "")[:600],
    }
    print("match:", json.dumps(compact, ensure_ascii=False))
PY

git status --short --ignored -- store-inspection/cdp_meituan_balance.py store-inspection/meituan-cdp-latest.json store-inspection/meituan-cdp-latest-data.js store-inspection/meituan-cdp-network-candidates.json store-inspection/meituan-cdp-network-matches.json .gitignore
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 脚本是否已同步；
3. Python 语法检查是否通过；
4. 脚本运行是否成功；
5. `meituan-cdp-latest.json` 的 `status`、`summary`、`message`；
6. 前 8 条门店样例；
7. 候选接口数量、字段命中数量；
8. 前 15 条字段命中摘要；
9. `git status --short --ignored`，确认测试产物被忽略；
10. 确认没有运行旧余额巡检、没有截图/OCR、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

如果字段命中里出现真实账户余额字段，下一步就能把美团余额解析从页面文本改成接口 JSON 字段。
