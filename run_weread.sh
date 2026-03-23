#!/bin/bash
# 执行微信读书自动化任务，第一个参数为用户名称
# 用法: ./run.sh admin

USER="${1:?用法: $0 <用户名称>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/data/users/${USER}/cron.log"
PYTHON="/home/ubuntu/.pyenv/versions/3.12.3/envs/weread/bin/python3"

cd "$SCRIPT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

# 若 global.json 中 use_xvfb=true 且无显示器，用 xvfb-run 启动有头 Chrome（规避 headless 不统计时长）
USE_XVFB=false
if [ -z "$DISPLAY" ] && [ -f "$SCRIPT_DIR/global.json" ]; then
  if grep -qE '"use_xvfb"[[:space:]]*:[[:space:]]*true' "$SCRIPT_DIR/global.json" 2>/dev/null; then
    USE_XVFB=true
  fi
fi

if [ "$USE_XVFB" = "true" ]; then
  exec xvfb-run -a "$PYTHON" main.py -u "$USER" >> "$LOG_FILE" 2>&1
else
  exec "$PYTHON" main.py -u "$USER" >> "$LOG_FILE" 2>&1
fi
