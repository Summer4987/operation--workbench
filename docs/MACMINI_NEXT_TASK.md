# Mac mini 下一步任务

## 当前任务：部署余额失败不阻断，并尝试后台权限授权探针

目的：

- 08:00 定时任务里，如果推广余额巡检因为屏幕录制/辅助功能失败，不再把整套上午运营判失败，而是跳过余额并继续日报、评价、预算配置、看板发布等后续业务。
- 再运行一次临时 LaunchAgent 权限探针，尝试触发 macOS 屏幕录制/辅助功能授权提示。执行时请盯着 Mac mini 屏幕，如果出现权限弹窗，请点击允许。

## 执行范围

允许从 clean 仓库同步到旧生产目录的文件：

```text
morning-ops/run_morning_ops.py
```

允许创建并清理的临时文件：

```text
/tmp/codex_launchd_permission_probe.zsh
/tmp/com.summer.codex.permission-probe.plist
/tmp/codex_launchd_permission_probe.*
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
- 不要修改或 reload 任何现有生产 LaunchAgent。
- 不要修改 `com.summer.operation.morning`。
- 不要提交、不要推送。
- 只同步本任务列出的一个文件。
- 临时权限探针执行后必须清理临时 plist、脚本、截图和日志。

## 第一步：同步余额失败不阻断逻辑

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp "morning-ops/run_morning_ops.py" "/Users/summer/Documents/New project/morning-ops/run_morning_ops.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile "morning-ops/run_morning_ops.py"
grep -n "推广余额总巡检失败，定时任务已跳过该项并继续后续业务" "morning-ops/run_morning_ops.py"
git diff -- morning-ops/run_morning_ops.py
```

## 第二步：临时 LaunchAgent 权限探针

执行前请确保有人在 Mac mini 屏幕前观察。如果出现权限弹窗，请点击允许。

```zsh
PROBE_SCRIPT="/tmp/codex_launchd_permission_probe.zsh"
PROBE_PLIST="/tmp/com.summer.codex.permission-probe.plist"
PROBE_LOG="/tmp/codex_launchd_permission_probe.log"
PROBE_OUT="/tmp/codex_launchd_permission_probe.stdout.log"
PROBE_ERR="/tmp/codex_launchd_permission_probe.stderr.log"
PROBE_IMG="/tmp/codex_launchd_permission_probe.png"
PROBE_LABEL="com.summer.codex.permission-probe"

cat > "$PROBE_SCRIPT" <<'EOF'
#!/bin/zsh
{
  echo "BEGIN $(date '+%F %T')"
  echo "user=$(id -un) uid=$(id -u)"
  echo "console=$(stat -f %Su /dev/console 2>/dev/null || true)"
  echo "PATH=$PATH"
  echo "PWD=$PWD"
  echo "SHELL=$SHELL"
  /usr/sbin/screencapture -x /tmp/codex_launchd_permission_probe.png >/tmp/codex_launchd_permission_probe.screencapture.out 2>&1
  code=$?
  if [ "$code" -eq 0 ]; then
    echo "screencapture=success size=$(stat -f %z /tmp/codex_launchd_permission_probe.png 2>/dev/null || echo 0)"
  else
    echo "screencapture=failed code=$code output=$(cat /tmp/codex_launchd_permission_probe.screencapture.out 2>/dev/null)"
  fi
  /usr/bin/osascript -e 'tell application "System Events" to get UI elements enabled' >/tmp/codex_launchd_permission_probe.accessibility.out 2>&1
  code=$?
  echo "accessibility_code=$code output=$(cat /tmp/codex_launchd_permission_probe.accessibility.out 2>/dev/null)"
  echo "END $(date '+%F %T')"
} > /tmp/codex_launchd_permission_probe.log 2>&1
EOF
chmod +x "$PROBE_SCRIPT"

cat > "$PROBE_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$PROBE_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$PROBE_SCRIPT</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/tmp</string>
  <key>StandardOutPath</key>
  <string>$PROBE_OUT</string>
  <key>StandardErrorPath</key>
  <string>$PROBE_ERR</string>
</dict>
</plist>
EOF

/bin/launchctl bootout "gui/$(id -u)" "$PROBE_PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$PROBE_PLIST"
/bin/launchctl kickstart -k "gui/$(id -u)/$PROBE_LABEL"

for i in {1..30}; do
  if grep -q "^END " "$PROBE_LOG" 2>/dev/null; then
    break
  fi
  sleep 1
done

cat "$PROBE_LOG" 2>/dev/null || true
/bin/launchctl bootout "gui/$(id -u)" "$PROBE_PLIST" >/dev/null 2>&1 || true
rm -f "$PROBE_SCRIPT" "$PROBE_PLIST" "$PROBE_IMG" "$PROBE_LOG" "$PROBE_OUT" "$PROBE_ERR" \
  /tmp/codex_launchd_permission_probe.screencapture.out \
  /tmp/codex_launchd_permission_probe.accessibility.out
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. `run_morning_ops.py` 是否已同步；
3. Python 语法检查是否通过；
4. grep 是否能看到“推广余额总巡检失败，定时任务已跳过该项并继续后续业务”；
5. 临时权限探针日志；
6. 探针期间是否出现权限弹窗，是否点击了允许；
7. 确认没有运行上午运营任务、没有运行日报/评价/余额/预算/发布、没有修改或 reload 任何现有生产定时任务、没有提交或推送。

## 预期效果

如果 macOS 弹出权限提示并允许成功，后续 launchd 后台链路可能获得截图能力。如果仍失败，明早余额巡检会被跳过并清楚记录原因，不会影响其他上午业务继续执行。
