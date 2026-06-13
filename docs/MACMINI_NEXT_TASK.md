# Mac mini 下一步任务

## 当前任务：试跑饿了么 CDP 余额读取旁路脚本

目的：

- 验证饿了么余额是否可以通过 Chrome CDP 接口读取，不依赖截图/OCR。
- 只生成旁路测试文件，不覆盖正式 `store-inspection/latest.json`。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
.gitignore
store-inspection/cdp_eleme_balance.py
```

允许运行的只读测试脚本：

```text
store-inspection/cdp_eleme_balance.py
```

允许生成的测试产物：

```text
store-inspection/eleme-cdp-latest.json
store-inspection/eleme-cdp-latest-data.js
```

旧生产目录：

```text
/Users/summer/Documents/New project
```

clean 仓库：

```text
/Users/summer/Documents/operation-workbench-clean
```

## 必须遵守

- 不要运行现有余额巡检。
- 不要截图、不要 OCR。
- 不要运行上午运营任务。
- 不要运行日报、评价、预算提交或云端发布。
- 不要点击任何保存、提交、充值、提现、转账、批量转入按钮。
- 不要修改或 reload 任何定时任务。
- 不要提交、不要推送。
- 不要覆盖 `store-inspection/latest.json` 或 `store-inspection/latest-data.js`。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp ".gitignore" "/Users/summer/Documents/New project/.gitignore"
cp "store-inspection/cdp_eleme_balance.py" "/Users/summer/Documents/New project/store-inspection/cdp_eleme_balance.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile "store-inspection/cdp_eleme_balance.py"

PYTHON="business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" "store-inspection/cdp_eleme_balance.py"

python3 - <<'PY'
import json
from pathlib import Path

path = Path("store-inspection/eleme-cdp-latest.json")
data = json.loads(path.read_text(encoding="utf-8"))
print("status:", data.get("status"))
print("generated_at:", data.get("generated_at"))
print("summary:", json.dumps(data.get("summary", {}), ensure_ascii=False, indent=2))
print("response_url:", data.get("response_url", ""))
for item in data.get("items", [])[:5]:
    print(json.dumps(item, ensure_ascii=False))
PY

git status --short --ignored -- store-inspection/cdp_eleme_balance.py store-inspection/eleme-cdp-latest.json store-inspection/eleme-cdp-latest-data.js .gitignore
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 脚本是否已同步；
3. Python 语法检查是否通过；
4. 脚本运行是否成功；
5. `eleme-cdp-latest.json` 的 `status`、`summary`、`response_url`；
6. 前 5 条门店余额样例；
7. `git status --short --ignored`，确认测试产物被忽略；
8. 确认没有运行旧余额巡检、没有截图/OCR、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

如果脚本读取成功，饿了么余额就可以先从截图 OCR 迁移到 CDP 接口读取。确认稳定后，再把它接入正式余额巡检流程。
