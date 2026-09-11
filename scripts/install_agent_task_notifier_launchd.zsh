#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_CENTER_ROOT:-/Users/summer/Library/Application Support/xiong-operation/production}"
LABEL="com.summer.operation.agent-task-notifier"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
LOG_DIR="$HOME/Library/Logs/xiong-operation/agent-task-notifier"
RUNNER="$SCRIPT_DIR/run_agent_task_notifier.zsh"
PLIST="$LAUNCH_DIR/${LABEL}.plist"
PYTHON="${PYTHON:-/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

mkdir -p "$LAUNCH_DIR" "$SCRIPT_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/usr/bin/python3"
fi

cat > "$RUNNER" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
PYTHON="${PYTHON}"
LOG_DIR="${LOG_DIR}"
mkdir -p "\$LOG_DIR"
cd "\$ROOT"

OPERATION_CENTER_ROOT="\$ROOT" "\$PYTHON" scripts/agent_task_notifier.py >> "\$LOG_DIR/\$(date +%F).log" 2>&1
EOF
chmod +x "$RUNNER"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${RUNNER}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Minute</key><integer>0</integer></dict>
    <dict><key>Minute</key><integer>1</integer></dict>
    <dict><key>Minute</key><integer>2</integer></dict>
    <dict><key>Minute</key><integer>3</integer></dict>
    <dict><key>Minute</key><integer>4</integer></dict>
    <dict><key>Minute</key><integer>5</integer></dict>
    <dict><key>Minute</key><integer>6</integer></dict>
    <dict><key>Minute</key><integer>7</integer></dict>
    <dict><key>Minute</key><integer>8</integer></dict>
    <dict><key>Minute</key><integer>9</integer></dict>
    <dict><key>Minute</key><integer>10</integer></dict>
    <dict><key>Minute</key><integer>11</integer></dict>
    <dict><key>Minute</key><integer>12</integer></dict>
    <dict><key>Minute</key><integer>13</integer></dict>
    <dict><key>Minute</key><integer>14</integer></dict>
    <dict><key>Minute</key><integer>15</integer></dict>
    <dict><key>Minute</key><integer>16</integer></dict>
    <dict><key>Minute</key><integer>17</integer></dict>
    <dict><key>Minute</key><integer>18</integer></dict>
    <dict><key>Minute</key><integer>19</integer></dict>
    <dict><key>Minute</key><integer>20</integer></dict>
    <dict><key>Minute</key><integer>21</integer></dict>
    <dict><key>Minute</key><integer>22</integer></dict>
    <dict><key>Minute</key><integer>23</integer></dict>
    <dict><key>Minute</key><integer>24</integer></dict>
    <dict><key>Minute</key><integer>25</integer></dict>
    <dict><key>Minute</key><integer>26</integer></dict>
    <dict><key>Minute</key><integer>27</integer></dict>
    <dict><key>Minute</key><integer>28</integer></dict>
    <dict><key>Minute</key><integer>29</integer></dict>
    <dict><key>Minute</key><integer>30</integer></dict>
    <dict><key>Minute</key><integer>31</integer></dict>
    <dict><key>Minute</key><integer>32</integer></dict>
    <dict><key>Minute</key><integer>33</integer></dict>
    <dict><key>Minute</key><integer>34</integer></dict>
    <dict><key>Minute</key><integer>35</integer></dict>
    <dict><key>Minute</key><integer>36</integer></dict>
    <dict><key>Minute</key><integer>37</integer></dict>
    <dict><key>Minute</key><integer>38</integer></dict>
    <dict><key>Minute</key><integer>39</integer></dict>
    <dict><key>Minute</key><integer>40</integer></dict>
    <dict><key>Minute</key><integer>41</integer></dict>
    <dict><key>Minute</key><integer>42</integer></dict>
    <dict><key>Minute</key><integer>43</integer></dict>
    <dict><key>Minute</key><integer>44</integer></dict>
    <dict><key>Minute</key><integer>45</integer></dict>
    <dict><key>Minute</key><integer>46</integer></dict>
    <dict><key>Minute</key><integer>47</integer></dict>
    <dict><key>Minute</key><integer>48</integer></dict>
    <dict><key>Minute</key><integer>49</integer></dict>
    <dict><key>Minute</key><integer>50</integer></dict>
    <dict><key>Minute</key><integer>51</integer></dict>
    <dict><key>Minute</key><integer>52</integer></dict>
    <dict><key>Minute</key><integer>53</integer></dict>
    <dict><key>Minute</key><integer>54</integer></dict>
    <dict><key>Minute</key><integer>55</integer></dict>
    <dict><key>Minute</key><integer>56</integer></dict>
    <dict><key>Minute</key><integer>57</integer></dict>
    <dict><key>Minute</key><integer>58</integer></dict>
    <dict><key>Minute</key><integer>59</integer></dict>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${LABEL}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${LABEL}.err.log</string>
</dict>
</plist>
EOF

cd "$ROOT"
# Preserve pending deliveries on reinstall; never mark them sent with --seed.

/bin/launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$PLIST"
/bin/launchctl enable "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
/bin/launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "Agent 任务通知器已安装。"
echo "标签：${LABEL}"
echo "频率：每分钟整点检查待发送结果"
echo "根目录：${ROOT}"
echo "日志目录：${LOG_DIR}"
