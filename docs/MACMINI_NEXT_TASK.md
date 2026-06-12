# Mac mini 下一步任务

## 任务：让生产目录知晓推广余额 200 元提醒阈值

目标：

- 让旧生产目录 `/Users/summer/Documents/New project` 使用最新的推广余额阈值规则：低于 200 元提醒。
- 现在不运行余额巡检。
- 现在不发布云端看板。
- 不触碰已有定时任务。
- 不提交、不推送。

## 执行脚本

请在 Mac mini 上执行：

```zsh
cat > /tmp/apply_balance_threshold_200.zsh <<'ZSH'
#!/bin/zsh
set -euo pipefail

CLEAN="/Users/summer/Documents/operation-workbench-clean"
PROD="/Users/summer/Documents/New project"

cd "$CLEAN"
git pull --ff-only origin main

FILES=(
  "store-inspection/config.json"
  "store-inspection/app.js"
  "store-inspection/index.html"
  "store-inspection/parse_balance_ocr.py"
  "store-inspection/one_click_meituan_balance.py"
  "store-inspection/one_click_eleme_balance.py"
)

for file in "${FILES[@]}"; do
  cp "$CLEAN/$file" "$PROD/$file"
  echo "已同步：$file"
done

cd "$PROD"

python3 -m py_compile \
  store-inspection/parse_balance_ocr.py \
  store-inspection/one_click_meituan_balance.py \
  store-inspection/one_click_eleme_balance.py

python3 - <<'PY'
import json
from pathlib import Path

config = json.loads(Path("store-inspection/config.json").read_text(encoding="utf-8"))
threshold = config["rules"]["promotion_balance_warning"]
if threshold != 200:
    raise SystemExit(f"阈值未生效：{threshold}")

print("推广余额提醒阈值已设为 200 元。")
print("本次只同步规则，不运行巡检，不发布云端。")
PY

cd "$CLEAN"
OPERATION_CENTER_ROOT="$PROD" python3 ai-business-center/guardian.py

echo
echo "完成：明早正常巡检会按 200 元阈值生成结果。"
ZSH

zsh /tmp/apply_balance_threshold_200.zsh
```

## 输出要求

执行后请输出：

1. 脚本完整输出。
2. `/Users/summer/Documents/New project/store-inspection/config.json` 里的 `promotion_balance_warning`。
3. clean 仓库 `git status --short --branch`。
4. 旧生产目录中以下文件的 diff：

```zsh
cd "/Users/summer/Documents/New project"
git diff -- \
  store-inspection/config.json \
  store-inspection/app.js \
  store-inspection/index.html \
  store-inspection/parse_balance_ocr.py \
  store-inspection/one_click_meituan_balance.py \
  store-inspection/one_click_eleme_balance.py
```

## 成功标准

- `promotion_balance_warning` 等于 `200`。
- Python 语法检查通过。
- 没有运行余额巡检。
- 没有发布云端。
- 没有触碰已有定时任务。
