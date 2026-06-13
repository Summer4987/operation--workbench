# Mac mini 下一步任务

## 当前任务：把正式余额巡检切到 CDP，并单独验证一次

目的：

- 让正式 `store-inspection/run_all_balances.py` 改为调用 CDP 余额总巡检。
- 明早上午运营走到余额环节时，不再使用截图/OCR。
- 单独运行一次新的余额巡检，只更新本地正式 `store-inspection/latest.json` 和 `latest-data.js`。
- 不运行日报、评价、预算、发布，也不触碰定时任务。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
.gitignore
store-inspection/cdp_eleme_balance.py
store-inspection/cdp_meituan_balance.py
store-inspection/cdp_all_balances.py
store-inspection/run_all_balances.py
```

允许运行的验证脚本：

```text
store-inspection/run_all_balances.py
```

这次允许该脚本更新：

```text
store-inspection/latest.json
store-inspection/latest-data.js
```

## 必须遵守

- 不要运行上午运营任务。
- 不要运行日报、评价、预算提交或云端发布。
- 不要截图、不要 OCR。
- 不要点击任何页面按钮。
- 不要修改或 reload 任何定时任务。
- 不要提交、不要推送。
- 不要修改任务列出范围以外的源码文件。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp ".gitignore" "/Users/summer/Documents/New project/.gitignore"
cp "store-inspection/cdp_eleme_balance.py" "/Users/summer/Documents/New project/store-inspection/cdp_eleme_balance.py"
cp "store-inspection/cdp_meituan_balance.py" "/Users/summer/Documents/New project/store-inspection/cdp_meituan_balance.py"
cp "store-inspection/cdp_all_balances.py" "/Users/summer/Documents/New project/store-inspection/cdp_all_balances.py"
cp "store-inspection/run_all_balances.py" "/Users/summer/Documents/New project/store-inspection/run_all_balances.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile \
  "store-inspection/cdp_eleme_balance.py" \
  "store-inspection/cdp_meituan_balance.py" \
  "store-inspection/cdp_all_balances.py" \
  "store-inspection/run_all_balances.py"

before_latest="$(shasum -a 256 store-inspection/latest.json store-inspection/latest-data.js 2>/dev/null || true)"

PYTHON="business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" "store-inspection/run_all_balances.py"

after_latest="$(shasum -a 256 store-inspection/latest.json store-inspection/latest-data.js 2>/dev/null || true)"

python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("store-inspection/latest.json").read_text(encoding="utf-8"))
print("status:", data.get("status"))
print("generated_at:", data.get("generated_at"))
print("summary:", json.dumps(data.get("summary", {}), ensure_ascii=False, indent=2))
print("message:", data.get("message", ""))
print("source:", data.get("source"))
print("source_urls:", json.dumps(data.get("source_urls", {}), ensure_ascii=False, indent=2))
for item in data.get("items", []):
    compact = {
        "platform": item.get("platform"),
        "store_name": item.get("store_name"),
        "store_id": item.get("store_id"),
        "balance": item.get("balance"),
        "status": item.get("status"),
        "source": item.get("source"),
        "api_seen": item.get("api_seen"),
        "error": item.get("error"),
    }
    print("item:", json.dumps(compact, ensure_ascii=False))
PY

echo "latest checksum before:"
printf '%s\n' "$before_latest"
echo "latest checksum after:"
printf '%s\n' "$after_latest"

git status --short --ignored -- \
  .gitignore \
  store-inspection/cdp_eleme_balance.py \
  store-inspection/cdp_meituan_balance.py \
  store-inspection/cdp_all_balances.py \
  store-inspection/run_all_balances.py \
  store-inspection/latest.json \
  store-inspection/latest-data.js \
  store-inspection/cdp-latest.json \
  store-inspection/cdp-latest-data.js
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 5 个文件是否已同步；
3. Python 语法检查是否通过；
4. `run_all_balances.py` 是否运行成功；
5. `latest.json` 的 `status`、`summary`、`message`、`source`、`source_urls`；
6. 全部门店余额明细；
7. `latest.json` / `latest-data.js` 的运行前后校验值；
8. `git status --short --ignored`，确认 `cdp-latest*` 已被忽略；
9. 确认没有运行上午运营、日报、评价、预算、发布，没有截图/OCR，没有点击页面按钮，没有修改或 reload 定时任务，没有提交或推送。

## 预期效果

`latest.json` 应显示：

- `source = cdp_all_balances`
- `summary.platform_count = 2`
- `summary.store_count = 18`
- 门店来源均为 `Chrome CDP接口读取`

如果这一步成功，明早 08:00 的上午运营余额环节就会走 CDP，不再依赖后台 LaunchAgent 的屏幕录制权限。
