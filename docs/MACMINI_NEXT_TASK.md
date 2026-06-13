# Mac mini 下一步任务

## 当前任务：试跑 CDP 余额总巡检旁路脚本

目的：

- 使用饿了么 CDP 接口读取 10 家门店余额。
- 使用美团 CDP 接口读取 8 家门店余额。
- 合并生成一份旁路总结果 `store-inspection/cdp-latest.json`。
- 继续只验证 CDP 方案，不覆盖正式 `store-inspection/latest.json`。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
store-inspection/cdp_eleme_balance.py
store-inspection/cdp_meituan_balance.py
store-inspection/cdp_all_balances.py
```

允许运行的只读测试脚本：

```text
store-inspection/cdp_all_balances.py
```

允许生成的测试产物：

```text
store-inspection/cdp-latest.json
store-inspection/cdp-latest-data.js
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

cp "store-inspection/cdp_eleme_balance.py" "/Users/summer/Documents/New project/store-inspection/cdp_eleme_balance.py"
cp "store-inspection/cdp_meituan_balance.py" "/Users/summer/Documents/New project/store-inspection/cdp_meituan_balance.py"
cp "store-inspection/cdp_all_balances.py" "/Users/summer/Documents/New project/store-inspection/cdp_all_balances.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile \
  "store-inspection/cdp_eleme_balance.py" \
  "store-inspection/cdp_meituan_balance.py" \
  "store-inspection/cdp_all_balances.py"

before_latest="$(shasum -a 256 store-inspection/latest.json store-inspection/latest-data.js 2>/dev/null || true)"

PYTHON="business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" "store-inspection/cdp_all_balances.py"

after_latest="$(shasum -a 256 store-inspection/latest.json store-inspection/latest-data.js 2>/dev/null || true)"

python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("store-inspection/cdp-latest.json").read_text(encoding="utf-8"))
print("status:", data.get("status"))
print("generated_at:", data.get("generated_at"))
print("summary:", json.dumps(data.get("summary", {}), ensure_ascii=False, indent=2))
print("message:", data.get("message", ""))
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
if [ "$before_latest" = "$after_latest" ]; then
  echo "正式 latest 文件未被覆盖。"
else
  echo "警告：正式 latest 文件校验值发生变化。"
fi

git status --short --ignored -- \
  store-inspection/cdp_eleme_balance.py \
  store-inspection/cdp_meituan_balance.py \
  store-inspection/cdp_all_balances.py \
  store-inspection/cdp-latest.json \
  store-inspection/cdp-latest-data.js \
  store-inspection/latest.json \
  store-inspection/latest-data.js
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 三个脚本是否已同步；
3. Python 语法检查是否通过；
4. 脚本运行是否成功；
5. `cdp-latest.json` 的 `status`、`summary`、`message`、`source_urls`；
6. 全部门店余额明细；
7. 正式 `latest.json` / `latest-data.js` 的运行前后校验值是否一致；
8. `git status --short --ignored`，确认测试产物被忽略；
9. 确认没有运行旧余额巡检、没有截图/OCR、没有点击页面按钮、没有覆盖正式 `latest.json`、没有运行日报/评价/预算/发布、没有提交或推送。

## 预期效果

理想结果是 2 个平台、18 条门店余额、全部来源为 CDP 接口读取，正式 `latest.json` 不变。若结果稳定，下一步再把正式 `run_all_balances.py` 切换到 CDP 方案。
