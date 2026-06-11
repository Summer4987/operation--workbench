#!/bin/zsh
PORT="9223"
URL="https://e.ele.me/#/iframe/home"

if curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  open -a "Google Chrome" "$URL"
  echo "日常 Chrome 巡检模式已可用，已打开饿了么余额页。"
else
  if pgrep -x "Google Chrome" >/dev/null 2>&1; then
    echo "Chrome 已经在运行，但还不是巡检模式。"
    echo "请先完全退出 Chrome，再双击这个入口。"
    echo ""
    echo "退出方式：Chrome 菜单栏 -> Chrome -> 退出 Google Chrome"
  else
    open -na "Google Chrome" --args \
      "--remote-debugging-port=${PORT}" \
      "--profile-directory=Default" \
      "--no-first-run" \
      "--no-default-browser-check" \
      "$URL"
    sleep 3
    if curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
      echo "已用日常 Chrome 启动巡检模式，并打开饿了么余额页。"
    else
      echo "已打开日常 Chrome，但 Chrome 没有开放脚本读取端口。"
      echo "这是新版 Chrome 对默认日常资料夹的保护，不是账号问题。"
      echo "余额页可以正常人工查看；自动读取需要改用 Chrome 插件读取或其它方案。"
    fi
  fi
fi

if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
