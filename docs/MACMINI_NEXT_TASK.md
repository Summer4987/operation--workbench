# Mac mini 下一步任务

## 当前任务：试跑美团 CDP 路由发现探针

目的：

- 不再继续盲点账户入口。
- 只读扫描当前美团推广页的可见元素、链接、localStorage/sessionStorage、已加载 JS 资源。
- 从前端代码里寻找 `account / balance / wallet / recharge / withdraw / fund / asset / finance / 账户 / 余额 / 充值 / 提现` 相关路由或接口线索。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
.gitignore
store-inspection/cdp_meituan_route_probe.py
```

允许运行的只读测试脚本：

```text
store-inspection/cdp_meituan_route_probe.py
```

允许生成的测试产物：

```text
store-inspection/meituan-cdp-route-probe.json
```

## 必须遵守

- 不要运行现有余额巡检。
- 不要截图、不要 OCR。
- 不要运行上午运营任务。
- 不要运行日报、评价、预算提交或云端发布。
- 不要点击任何页面按钮。
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

cd "/Users/summer/Documents/New project"
python3 -m py_compile "store-inspection/cdp_meituan_route_probe.py"

PYTHON="business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" "store-inspection/cdp_meituan_route_probe.py"

python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("store-inspection/meituan-cdp-route-probe.json").read_text(encoding="utf-8"))
dom = data.get("dom", {})
print("generated_at:", data.get("generated_at"))
print("base_url:", data.get("base_url"))
print("current_url:", data.get("current_url"))
print("title:", dom.get("title"))
print("bodyTextPreview:", dom.get("bodyTextPreview", "")[:1000])
print("candidate_count:", len(dom.get("candidates", [])))
for item in dom.get("candidates", [])[:30]:
    compact = {
        "tag": item.get("tag"),
        "text": item.get("text"),
        "href": item.get("href"),
        "id": item.get("id"),
        "className": item.get("className"),
        "attrs": item.get("attrs"),
        "visible": item.get("visible"),
        "rect": item.get("rect"),
    }
    print("candidate:", json.dumps(compact, ensure_ascii=False)[:1200])

storage = dom.get("storage", {})
for name in ["localStorage", "sessionStorage"]:
    values = storage.get(name, [])
    print(f"{name}_match_count:", len(values))
    for item in values[:20]:
        print(name + ":", json.dumps(item, ensure_ascii=False)[:1200])

print("resource_count:", len(dom.get("resources", [])))
print("route_match_resource_count:", len(data.get("route_matches", [])))
for item in data.get("route_matches", [])[:20]:
    compact = {
        "url": item.get("url"),
        "matches": item.get("matches", [])[:10],
    }
    print("route_match:", json.dumps(compact, ensure_ascii=False)[:1500])
PY

git status --short --ignored -- store-inspection/cdp_meituan_route_probe.py store-inspection/meituan-cdp-route-probe.json .gitignore
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 脚本是否已同步；
3. Python 语法检查是否通过；
4. 脚本运行是否成功；
5. `current_url`、页面标题、页面文本前 1000 字；
6. 前 30 条 candidate；
7. localStorage/sessionStorage 命中；
8. route match 前 20 条；
9. `git status --short --ignored`，确认测试产物被忽略；
10. 确认没有运行旧余额巡检、没有截图/OCR、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

从页面元素、存储或前端 JS 资源中找到美团账户页真实路由或接口名称，供下一版 CDP 余额读取脚本使用。
