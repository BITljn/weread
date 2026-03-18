#!/usr/bin/env python3
"""
添加用户：创建目录、私有配置、读书列表

用法: python add_user.py <用户名> [选项]

选项:
  -w, --webhook <url>    企业微信 Webhook 地址
  -b, --book <书名>       添加一本书，可多次使用
  -f, --file <文件>       从文件读取图书列表（每行一书名）
  -n, --no-copy          不复制根目录 books.txt

示例:
  python add_user.py user1
  python add_user.py user1 -b 三体 -b 活着
  python add_user.py user1 -f my_books.txt
  python add_user.py user1 -w "https://..." -b 人类简史
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
ROOT_BOOKS = BASE_DIR / "books.txt"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="添加用户：创建目录、私有配置、读书列表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s user1
  %(prog)s user1 -b 三体 -b 活着
  %(prog)s user1 -f my_books.txt
  %(prog)s user1 -w "https://..." -b 人类简史
        """,
    )
    parser.add_argument("user", metavar="用户名", help="用户名称")
    parser.add_argument("-w", "--webhook", metavar="url", help="企业微信 Webhook 地址")
    parser.add_argument("-b", "--book", metavar="书名", action="append", help="添加一本书，可多次使用")
    parser.add_argument("-f", "--file", metavar="文件", help="从文件读取图书列表（每行一书名）")
    parser.add_argument("-n", "--no-copy", action="store_true", help="不复制根目录 books.txt")
    args = parser.parse_args()

    user = args.user
    if user.startswith("-"):
        print("错误: 用户名不能以 - 开头", file=sys.stderr)
        return 1

    books = args.book or []
    book_file = args.file
    no_copy = args.no_copy
    webhook = args.webhook or ""

    user_dir = BASE_DIR / "data" / "users" / user
    config_path = user_dir / "config.json"
    books_path = user_dir / "books.txt"

    # 创建用户目录
    user_dir.mkdir(parents=True, exist_ok=True)
    print(f"已创建目录: {user_dir}")

    # 写入私有配置
    if config_path.exists():
        if webhook:
            try:
                with open(config_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["wechat_webhook_url"] = webhook
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                print(f"已更新配置: {config_path}")
            except Exception as e:
                print(f"警告: 更新配置失败 {e}，请手动编辑 {config_path}", file=sys.stderr)
        else:
            print(f"配置文件已存在: {config_path}")
    else:
        cfg = {
            "use_cookie_login": True,
            "wechat_webhook_url": webhook,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"已创建配置: {config_path}")

    # 处理读书列表
    def read_books(file_path: Path) -> list[str]:
        if not file_path.exists():
            return []
        with open(file_path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    def write_books(file_path: Path, titles: list[str]) -> int:
        seen = set()
        unique = []
        for t in titles:
            if t and t not in seen:
                seen.add(t)
                unique.append(t)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(unique) + "\n" if unique else "")
        return len(unique)

    if books_path.exists() and not books and not book_file:
        print(f"读书列表已存在: {books_path}")
    elif books_path.exists() and (books or book_file):
        existing = read_books(books_path)
        new_from_file = read_books(Path(book_file)) if book_file and Path(book_file).exists() else []
        merged = existing + new_from_file + books
        count = write_books(books_path, merged)
        print(f"已追加图书到: {books_path} ({count} 本书)")
    else:
        titles = []
        if not no_copy and ROOT_BOOKS.exists():
            titles = read_books(ROOT_BOOKS)
            print(f"已复制根目录读书列表到: {books_path}")
        if book_file:
            fp = Path(book_file)
            if fp.exists():
                titles.extend(read_books(fp))
                print(f"已从文件导入: {book_file}")
            else:
                print(f"警告: 文件不存在 {book_file}", file=sys.stderr)
        titles.extend(books)
        count = write_books(books_path, titles)
        if count:
            print(f"读书列表: {books_path} ({count} 本书)")
        else:
            print(f"读书列表为空，请使用 -b 或 -f 添加，或复制 {ROOT_BOOKS} 到 {books_path}")

    print(f"用户 {user} 添加完成。运行: ./run_weread.sh {user}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
