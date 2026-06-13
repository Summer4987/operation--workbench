# Mac mini 下一步任务

## 当前任务：上午运营改为每天 08:00 执行，并部署防重复锁

目的：

- 正式上午运营任务从每天 09:30 提前到每天 08:00。
- 09:30 正式任务和手动 `上午运营一键采集.command` 共用同一把锁，避免重复启动。

## 执行范围

允许同步到旧生产目录的文件：

```text
morning-ops/run_morning_ops.py
morning-ops/上午运营一键采集.command
morning-ops/run_morning_ops_if_10am.command
scripts/install_macmini_operation_launchd.zsh
```

允许修改的生产侧定时项：

```text
~/Library/LaunchAgents/com.summer.operation.morning.plist
```

允许修改的生产侧外壳脚本：

```text
~/Library/Scripts/xiong-operation/run_morning_ops.zsh
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

- 不要运行上午运营任务。
- 不要运行日报、评价、余额巡检、预算提交或云端发布。
- 不要修改其他 LaunchAgent。
- 不要提交、不要推送。
- 只同步和修改本任务列出的文件/定时项。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp "morning-ops/run_morning_ops.py" "/Users/summer/Documents/New project/morning-ops/run_morning_ops.py"
cp "morning-ops/上午运营一键采集.command" "/Users/summer/Documents/New project/morning-ops/上午运营一键采集.command"
cp "morning-ops/run_morning_ops_if_10am.command" "/Users/summer/Documents/New project/morning-ops/run_morning_ops_if_10am.command"
cp "scripts/install_macmini_operation_launchd.zsh" "/Users/summer/Documents/New project/scripts/install_macmini_operation_launchd.zsh"
chmod +x "/Users/summer/Documents/New project/morning-ops/上午运营一键采集.command"
chmod +x "/Users/summer/Documents/New project/morning-ops/run_morning_ops_if_10am.command"
chmod +x "/Users/summer/Documents/New project/scripts/install_macmini_operation_launchd.zsh"

cd "/Users/summer/Documents/New project"
python3 -m py_compile "morning-ops/run_morning_ops.py"
zsh -n "morning-ops/上午运营一键采集.command"
zsh -n "morning-ops/run_morning_ops_if_10am.command"
zsh -n "scripts/install_macmini_operation_launchd.zsh"
```

## 修改正式定时任务到 08:00

只修改 `com.summer.operation.morning`，不要动其他定时任务。

```zsh
PLIST="$HOME/Library/LaunchAgents/com.summer.operation.morning.plist"
/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:Hour 8" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:Minute 0" "$PLIST"

SCRIPT="$HOME/Library/Scripts/xiong-operation/run_morning_ops.zsh"
python3 - <<'PY' "$SCRIPT"
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace('"$now_hhmm" -lt 900', '"$now_hhmm" -lt 800')
text = text.replace('当前不在 09:00-10:50 窗口内', '当前不在 08:00-10:50 窗口内')
path.write_text(text, encoding="utf-8")
PY
zsh -n "$SCRIPT"

/bin/launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$PLIST"
/bin/launchctl enable "gui/$(id -u)/com.summer.operation.morning" >/dev/null 2>&1 || true
```

## 验证

```zsh
launchctl print "gui/$(id -u)/com.summer.operation.morning" | sed -n '1,140p'
plutil -p "$HOME/Library/LaunchAgents/com.summer.operation.morning.plist"
grep -n "now_hhmm\\|08:00\\|09:00" "$HOME/Library/Scripts/xiong-operation/run_morning_ops.zsh"

cd "/Users/summer/Documents/New project"
git diff -- morning-ops/run_morning_ops.py "morning-ops/上午运营一键采集.command" morning-ops/run_morning_ops_if_10am.command scripts/install_macmini_operation_launchd.zsh
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 四个文件是否已同步；
3. 四个语法检查是否通过；
4. `com.summer.operation.morning` 当前 `StartCalendarInterval`；
5. `run_morning_ops.zsh` 是否已经允许 08:00-10:50 窗口；
6. 旧生产目录四个文件的 `git diff`；
7. 确认没有运行上午运营任务、没有运行日报/评价/余额/预算/发布、没有提交或推送。

## 预期效果

明天开始，正式上午运营任务会在每天 08:00 启动。若任务正在运行，手动入口或重复启动会被锁挡住，不会开启第二轮。
