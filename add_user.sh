#!/bin/bash
# 添加用户：创建目录、私有配置、读书列表
# 用法: ./add_user.sh <用户名> [选项]
#
# 选项:
#   -w, --webhook <url>    企业微信 Webhook 地址
#   -b, --book <书名>       添加一本书，可多次使用
#   -f, --file <文件>       从文件读取图书列表（每行一书名）
#   -n, --no-copy          不复制根目录 books.txt
#
# 示例:
#   ./add_user.sh user1
#   ./add_user.sh user1 -b 三体 -b 活着
#   ./add_user.sh user1 -f my_books.txt
#   ./add_user.sh user1 -w "https://..." -b 人类简史

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER=""
WEBHOOK=""
BOOKS=()
BOOK_FILE=""
NO_COPY=false

usage() {
    echo "用法: $0 <用户名> [选项]"
    echo ""
    echo "选项:"
    echo "  -w, --webhook <url>    企业微信 Webhook 地址"
    echo "  -b, --book <书名>       添加一本书，可多次使用"
    echo "  -f, --file <文件>       从文件读取图书列表（每行一书名）"
    echo "  -n, --no-copy          不复制根目录 books.txt"
    echo ""
    echo "示例:"
    echo "  $0 user1"
    echo "  $0 user1 -b 三体 -b 活着"
    echo "  $0 user1 -f my_books.txt"
    echo "  $0 user1 -w 'https://...' -b 人类简史"
    exit 1
}

[[ $# -eq 0 ]] && usage
USER="$1"
shift
[[ "$USER" == "-h" ]] || [[ "$USER" == "--help" ]] && usage
[[ "$USER" == -* ]] && { echo "错误: 用户名不能以 - 开头"; usage; }

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        -w|--webhook)
            WEBHOOK="$2"
            shift 2
            ;;
        -b|--book)
            BOOKS+=("$2")
            shift 2
            ;;
        -f|--file)
            BOOK_FILE="$2"
            shift 2
            ;;
        -n|--no-copy)
            NO_COPY=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "未知参数: $1"
            usage
            ;;
    esac
done

USER_DIR="${SCRIPT_DIR}/data/users/${USER}"
CONFIG_FILE="${USER_DIR}/config.json"
BOOKS_FILE="${USER_DIR}/books.txt"
ROOT_BOOKS="${SCRIPT_DIR}/books.txt"

# 创建用户目录
mkdir -p "$USER_DIR"
echo "已创建目录: $USER_DIR"

# 写入私有配置
if [[ -f "$CONFIG_FILE" ]]; then
    echo "警告: 配置文件已存在，将合并 wechat_webhook_url"
    # 若已有配置，仅更新 webhook（若指定）
    if [[ -n "$WEBHOOK" ]]; then
        if command -v jq &>/dev/null; then
            jq --arg url "$WEBHOOK" '.wechat_webhook_url = $url' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp"
            mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"
        else
            echo "提示: 安装 jq 可自动更新 webhook，或手动编辑 $CONFIG_FILE"
        fi
    fi
else
    cat > "$CONFIG_FILE" << EOF
{
  "use_cookie_login": true,
  "wechat_webhook_url": "${WEBHOOK}"
}
EOF
    echo "已创建配置: $CONFIG_FILE"
fi

# 处理读书列表
if [[ -f "$BOOKS_FILE" ]] && [[ ${#BOOKS[@]} -eq 0 ]] && [[ -z "$BOOK_FILE" ]]; then
    echo "读书列表已存在: $BOOKS_FILE"
elif [[ -f "$BOOKS_FILE" ]] && ( [[ ${#BOOKS[@]} -gt 0 ]] || [[ -n "$BOOK_FILE" ]] ); then
    # 已有列表，追加 -b 或 -f 的内容
    {
        cat "$BOOKS_FILE"
        [[ -n "$BOOK_FILE" ]] && [[ -f "$BOOK_FILE" ]] && cat "$BOOK_FILE"
        for b in "${BOOKS[@]}"; do
            echo "$b"
        done
    } | grep -v '^[[:space:]]*$' | sort -u > "${BOOKS_FILE}.tmp"
    mv "${BOOKS_FILE}.tmp" "$BOOKS_FILE"
    echo "已追加图书到: $BOOKS_FILE ($(wc -l < "$BOOKS_FILE") 本书)"
else
    # 新建读书列表
    : > "$BOOKS_FILE"
    if [[ "$NO_COPY" != true ]] && [[ -f "$ROOT_BOOKS" ]]; then
        cat "$ROOT_BOOKS" >> "$BOOKS_FILE"
        echo "已复制根目录读书列表到: $BOOKS_FILE"
    fi
    if [[ -n "$BOOK_FILE" ]] && [[ -f "$BOOK_FILE" ]]; then
        cat "$BOOK_FILE" >> "$BOOKS_FILE"
        echo "已从文件导入: $BOOK_FILE"
    fi
    for b in "${BOOKS[@]}"; do
        echo "$b" >> "$BOOKS_FILE"
    done
    # 去重、去空行
    if [[ -s "$BOOKS_FILE" ]]; then
        sort -u "$BOOKS_FILE" | grep -v '^[[:space:]]*$' > "${BOOKS_FILE}.tmp"
        mv "${BOOKS_FILE}.tmp" "$BOOKS_FILE"
        echo "读书列表: $BOOKS_FILE ($(wc -l < "$BOOKS_FILE") 本书)"
    else
        echo "读书列表为空，请使用 -b 或 -f 添加，或复制 $ROOT_BOOKS 到 $BOOKS_FILE"
    fi
fi

echo "用户 $USER 添加完成。运行: ./run_weread.sh $USER"
