#!/bin/bash
# 打包部署到 /home/ubuntu/deploy/weread（site-packages 安装模式）
# 用法: ./deploy.sh

set -e
DEPLOY_DIR="/home/ubuntu/deploy/weread"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> 部署到 $DEPLOY_DIR"

mkdir -p "$DEPLOY_DIR"
cd "$SCRIPT_DIR"

# 构建 wheel
echo "==> 构建 wheel..."
pip wheel . -q -w dist/
WHEEL=$(ls dist/weread-*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
    echo "错误: 构建 wheel 失败" >&2
    exit 1
fi

# 仅复制 wheel（不复制 global 配置、用户私有配置和 books.txt）
cp "$WHEEL" "$DEPLOY_DIR/"

# 创建 venv 并安装 weread 包（site-packages 方式）
cd "$DEPLOY_DIR"
if [ ! -d venv ]; then
    echo "==> 创建虚拟环境..."
    for py in "$HOME/.pyenv/versions/3.12.3/envs/weread/bin/python3" python3; do
        if [ -x "$py" ] 2>/dev/null; then
            "$py" -m venv venv 2>/dev/null && break
        fi
    done
    if [ ! -f venv/bin/python ]; then
        echo "错误: 无法创建 venv，请安装 python3-venv: sudo apt install python3.12-venv" >&2
        exit 1
    fi
fi
echo "==> 安装 weread 包 (site-packages)..."
./venv/bin/pip install -q --upgrade weread-*.whl
rm -f weread-*.whl

# 生成可执行脚本（设置 WEREAD_HOME 后调用已安装的 weread 命令）
cat > run_weread.sh << 'RUNSCRIPT'
#!/bin/bash
# 执行微信读书自动化任务
# 用法: ./run_weread.sh <用户名称>

USER="${1:?用法: $0 <用户名称>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/data/users/${USER}/cron.log"

cd "$SCRIPT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"
exec env WEREAD_HOME="$SCRIPT_DIR" "${SCRIPT_DIR}/venv/bin/weread" -u "$USER" >> "$LOG_FILE" 2>&1
RUNSCRIPT
chmod +x run_weread.sh

# 部署说明
cat > "$DEPLOY_DIR/README.md" << 'README'
# 微信读书自动化 - 部署目录

## 运行方式

```bash
./run_weread.sh admin                    # 执行阅读任务
WEREAD_HOME=. ./venv/bin/weread -u admin -b 三体   # 直接运行
WEREAD_HOME=. ./venv/bin/weread-add-user 新用户   # 添加用户
```

## 配置

- global.json - 全局配置
- data/users/<用户>/config.json - 用户配置
- data/users/<用户>/books.txt - 读书列表
README

echo "==> 部署完成: $DEPLOY_DIR"
echo ""
echo "目录结构:"
ls -la "$DEPLOY_DIR"
echo ""
echo "运行方式:"
echo "  cd $DEPLOY_DIR"
echo "  ./run_weread.sh admin    # 执行阅读任务"
