#!/bin/bash
# 执行微信读书自动化任务，第一个参数为用户名称
# 用法: ./run.sh admin

USER="${1:?用法: $0 <用户名称>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/data/users/${USER}/cron.log"
PYTHON="/home/ubuntu/.pyenv/versions/3.12.3/envs/weread/bin/python3"

cd "$SCRIPT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"
exec "$PYTHON" main.py -u "$USER" >> "$LOG_FILE" 2>&1
