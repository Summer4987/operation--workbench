#!/bin/zsh
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
echo "请给 Terminal 或 Codex 开启“屏幕录制”和“辅助功能”权限。"
echo "开启后重新双击“一键饿了么余额巡检.command”。"
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
