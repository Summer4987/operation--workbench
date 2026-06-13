# Mac mini 下一步任务

## 当前任务：试跑美团充值/账户路由 CDP 探针

目的：

- 根据路由发现结果，直接只读打开 `isomor_recharge`、`account`、`activity/recharge` 等候选路由。
- 捕获这些路由下的页面文本、接口响应和疑似余额字段。
- 只生成旁路测试文件，不覆盖正式 `store-inspection/latest.json`。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
.gitignore
store-inspection/cdp_meituan_route_probe.py
store-inspection/cdp_meituan_recharge_probe.py
```

允许运行的只读测试脚本：

```text
store-inspection/cdp_meituan_recharge_probe.py
```

允许生成的测试产物：

```text
store-inspection/meituan-cdp-recharge-probe.json
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

cp ".gitignore" "/Users/summer/Documents/New project/.gitignore"
cp "store-inspection/cdp_meituan_route_probe.py" "/Users/summer/Documents/New project/store-inspection/cdp_meituan_route_probe.py"
cp "store-inspection/cdp_meituan_recharge_probe.py" "/Users/summer/Documents/New project/store-inspection/cdp_meituan_recharge_probe.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile "store-inspection/cdp_meituan_route_probe.py" "store-inspection/cdp_meituan_recharge_probe.py"

PYTHON="business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" "store-inspection/cdp_meituan_recharge_probe.py"

python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("store-inspection/meituan-cdp-recharge-probe.json").read_text(encoding="utf-8"))
print("generated_at:", data.get("generated_at"))
print("base_url:", data.get("base_url"))
for route in data.get("routes", []):
    print("ROUTE:", route.get("route"))
    print("current_url:", route.get("current_url"))
    print("title:", route.get("title"))
    print("body:", route.get("body_text_preview", "")[:1000])
    print("response_count:", len(route.get("responses", [])))
    for response in route.get("responses", [])[:10]:
        compact = {
            "url": response.get("url"),
            "status": response.get("status"),
            "matches": response.get("matches", [])[:15],
            "snippet": response.get("snippet", "")[:800],
        }
        print("response:", json.dumps(compact, ensure_ascii=False))
PY

git status --short --ignored -- store-inspection/cdp_meituan_route_probe.py store-inspection/cdp_meituan_recharge_probe.py store-inspection/meituan-cdp-recharge-probe.json .gitignore
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 脚本是否已同步；
3. Python 语法检查是否通过；
4. 脚本运行是否成功；
5. 每个 ROUTE 的 `current_url`、`title`、页面文本前 1000 字；
6. 每个 ROUTE 的 response_count；
7. 每个 ROUTE 前 10 条 response 摘要；
8. `git status --short --ignored`，确认测试产物被忽略；
9. 确认没有运行旧余额巡检、没有截图/OCR、没有点击页面按钮、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

确认美团账户/充值页真实路由和余额接口。如果某个路由能看到“账户余额/可用余额”或接口金额字段，下一版就把美团余额解析接到该路由。
