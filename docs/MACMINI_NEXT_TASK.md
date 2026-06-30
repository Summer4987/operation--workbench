# Mac mini 下一步任务

## 当前任务：安装并测试快驴订货 dry-run 脚本

目的：

- 在 Mac mini 生产机从 GitHub `main` 拉取最新脚本。
- 从今天的订货记录里随机抽一个包含“快驴”的订单。
- 生成快驴商品筛选、规格拆包、排除词和购物车核对计划。
- 如果安卓机已通过 ADB 连接，保存一份当前页面截图和控件树，分析是否出现目标商品或风险商品。
- 全程不提交订单、不付款、不自动替换缺货商品、不切换收货地址。

## 执行范围

允许新增/同步的文件：

```text
scripts/kuailv_order_dry_run.py
scripts/run_kuailv_order_dry_run.zsh
docs/MACMINI_NEXT_TASK.md
```

允许运行的验证命令：

```zsh
python3 -m py_compile scripts/kuailv_order_dry_run.py
python3 scripts/kuailv_order_dry_run.py --mode plan-only --date "$(date +%F)"
/bin/zsh scripts/run_kuailv_order_dry_run.zsh
```

允许运行结果写入：

```text
outputs/kuailv_order_dry_run/
```

这些是运行结果和截图证据，不提交 GitHub。

## 必须遵守

- 不要点击“提交订单”。
- 不要付款。
- 不要自动替换缺货商品。
- 不要自动切换收货地址。
- 不要修改或 reload 任何定时任务。
- 不要运行上午运营、日报、评价、预算、推广出价、云端发布。
- 不要提交、不要推送。
- 如果 ADB 未连接或安卓机未解锁，只回报阻塞原因，不要强行继续。

## 建议执行步骤

优先使用干净交接仓库，避免覆盖生产目录本地改动：

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git status --short --branch
git pull --ff-only origin main
git log --oneline -5

chmod +x scripts/run_kuailv_order_dry_run.zsh

python3 -m py_compile scripts/kuailv_order_dry_run.py

python3 scripts/kuailv_order_dry_run.py --mode plan-only --date "$(date +%F)"

adb devices

/bin/zsh scripts/run_kuailv_order_dry_run.zsh

python3 - <<'PY'
import json
from pathlib import Path

path = Path("outputs/kuailv_order_dry_run/latest.json")
data = json.loads(path.read_text(encoding="utf-8"))
plan = data.get("plan", {})
print("status:", data.get("status"))
print("mode:", data.get("mode"))
print("message:", data.get("message"))
print("order:", plan.get("order_id"), plan.get("store_name"), plan.get("submitted_at"))
print("line_count:", plan.get("line_count"), "actionable:", plan.get("actionable_line_count"))
print("adb:", json.dumps(data.get("adb", {}), ensure_ascii=False, indent=2)[:4000])
for line in plan.get("lines", []):
    compact = {
        "name": line.get("name"),
        "requested_quantity": line.get("requested_quantity"),
        "unit": line.get("unit"),
        "search_terms": line.get("search_terms"),
        "required_keywords": line.get("required_keywords"),
        "preferred_spec_keywords": line.get("preferred_spec_keywords"),
        "excluded_keywords": line.get("excluded_keywords"),
        "pack_strategy": line.get("pack_strategy"),
        "learned_lesson": line.get("learned_lesson"),
    }
    print("line:", json.dumps(compact, ensure_ascii=False))
PY

git status --short --ignored -- \
  scripts/kuailv_order_dry_run.py \
  scripts/run_kuailv_order_dry_run.zsh \
  docs/MACMINI_NEXT_TASK.md \
  outputs/kuailv_order_dry_run
```

如果 `/Users/summer/Documents/operation-workbench-clean` 不存在，再只读检查生产目录：

```zsh
cd "/Users/summer/Documents/New project"
git status --short --branch
```

生产目录存在未提交或未跟踪改动时，停止并回报，不要在生产目录执行 `git pull` 或覆盖文件。

如果 `adb devices` 提示 `command not found: adb`，先安装官方 Android platform-tools 到当前用户目录，不改系统目录：

```zsh
mkdir -p "$HOME/Library/Android/sdk"
cd "$HOME/Library/Android/sdk"
curl -fL -o platform-tools-latest-darwin.zip "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
rm -rf platform-tools
/usr/bin/unzip -q platform-tools-latest-darwin.zip
"$HOME/Library/Android/sdk/platform-tools/adb" version
"$HOME/Library/Android/sdk/platform-tools/adb" devices
```

之后重新运行：

```zsh
ANDROID_ADB_BIN="$HOME/Library/Android/sdk/platform-tools/adb" /bin/zsh scripts/run_kuailv_order_dry_run.zsh
```

## 回报内容

请输出：

1. `git status --short --branch` 和 `git log --oneline -5`；
2. 两个脚本是否存在且包装脚本是否可执行；
3. Python 语法检查是否通过；
4. `plan-only` 随机抽中的订单号、门店、订货时间、品项；
5. `adb devices` 是否看到安卓机；
6. `adb-dry-run` 的 `status`、`message`、`session_dir`；
7. 页面截图/控件树是否保存，`plan_match.target_hits` 和 `plan_match.risk_hits`；
8. 确认没有提交订单、没有付款、没有自动替换缺货商品、没有切换收货地址、没有改定时任务、没有运行其他生产任务、没有提交或推送。

## 预期效果

- `plan-only` 应能从今天订单中随机抽到一个快驴订单，并输出每个商品的筛选规则。
- 豆腐规则必须包含强排除词：`嫩豆腐`、`5斤`、`2盒`。
- 圣女果 5 斤需求允许生成 6 斤整件策略。
- 快驴采购决策 dry-run 应输出每个品项的 ranked `top_candidates`，包含排名、候选文本、价格单位、包装折算、风险标记和原因；如果候选明确显示 `/盒`、`/袋` 等价格单位与订单单位不一致，必须标记 `unit_mismatch` 并禁止自动择优。
- ADB 可用时会生成 `outputs/kuailv_order_dry_run/<时间>/screen.png` 和 `window_dump.xml`。
- 即使 ADB 阻塞，也不能影响安全边界：脚本只生成计划或现场证据，不提交订单、不付款。
