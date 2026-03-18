"""
企业微信机器人通知模块

通过 Webhook 向企业微信群发送文本、图片等消息。
用于 crontab 定时任务场景下的任务状态通知。
"""

import base64
import hashlib
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# 企业微信机器人 Webhook 地址格式: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx


def _send(webhook_url: str, payload: dict) -> bool:
    """发送消息到企业微信机器人"""
    try:
        import requests

        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        result = resp.json()
        if result.get("errcode") == 0:
            log.debug("企业微信通知发送成功")
            return True
        log.warning("企业微信通知发送失败: %s", result)
        return False
    except ImportError:
        log.warning("未安装 requests，无法发送企业微信通知。请执行: pip install requests")
        return False
    except Exception as e:
        log.warning("企业微信通知发送异常: %s", e)
        return False


def send_text(webhook_url: str, content: str) -> bool:
    """发送文本消息"""
    if not webhook_url or not webhook_url.strip():
        return False
    payload = {"msgtype": "text", "text": {"content": content}}
    return _send(webhook_url.strip(), payload)


def send_image(webhook_url: str, image_path: str | Path) -> bool:
    """
    发送图片消息。
    图片需 base64 编码，且 base64 编码前最大 2M，支持 JPG/PNG。
    """
    if not webhook_url or not webhook_url.strip():
        return False
    path = Path(image_path)
    if not path.exists():
        log.warning("图片不存在: %s", path)
        return False
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > 2 * 1024 * 1024:  # 2MB
            log.warning("图片超过 2MB，无法发送")
            return False
        b64 = base64.b64encode(data).decode("utf-8")
        md5_val = hashlib.md5(data).hexdigest()
        payload = {"msgtype": "image", "image": {"base64": b64, "md5": md5_val}}
        return _send(webhook_url.strip(), payload)
    except Exception as e:
        log.warning("发送图片失败: %s", e)
        return False


def send_text_and_image(webhook_url: str, text: str, image_path: str | Path) -> bool:
    """
    先发文本说明，再发图片。
    企业微信机器人不支持一条消息同时包含文本和图片，需分两条发送。
    """
    ok1 = send_text(webhook_url, text)
    ok2 = send_image(webhook_url, image_path)
    return ok1 or ok2  # 至少成功一条即算部分成功


def notify_task_start(webhook_url: str, book_name: str) -> bool:
    """通知：任务开始"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"📖 微信读书任务已启动\n\n启动时间：{now}\n目标书籍：《{book_name}》\n请留意后续登录或完成通知。"
    return send_text(webhook_url, content)


def notify_login_required(webhook_url: str, qr_path: str | Path) -> bool:
    """
    通知：登录已过期，需要扫码。
    发送二维码图片 + 文字说明。
    """
    text = (
        "⚠️ 微信读书登录已过期\n\n"
        "请使用微信扫描下方二维码完成登录。\n"
        "二维码已保存在 data 目录下，也可从本消息中的图片扫码。\n"
        "完成扫码后程序将自动继续执行阅读任务。"
    )
    return send_text_and_image(webhook_url, text, qr_path)


def notify_login_success(webhook_url: str) -> bool:
    """通知：登录成功"""
    content = "✅ 微信读书登录成功\n\n已保存登录状态，正在执行阅读任务..."
    return send_text(webhook_url, content)


def notify_task_summary(
    webhook_url: str,
    book_name: str,
    scroll_count: int,
    turn_count: int,
    duration_sec: float,
    book_ended: bool,
) -> bool:
    """通知：任务完成摘要"""
    status = "已读完" if book_ended else "阅读中"
    content = (
        f"📚 微信读书任务完成\n\n"
        f"书籍：《{book_name}》\n"
        f"状态：{status}\n"
        f"阅读时长：{duration_sec:.1f} 秒\n"
        f"滚动次数：{scroll_count}\n"
        f"翻页次数：{turn_count}\n\n"
        f"本次任务已结束。"
    )
    return send_text(webhook_url, content)


def notify_error(webhook_url: str, error_msg: str, log_snippet: str = "") -> bool:
    """通知：任务执行出错，附带错误信息和日志片段"""
    content = f"❌ 微信读书任务执行出错\n\n错误信息：\n{error_msg}"
    if log_snippet:
        content += f"\n\n--- 最近日志 ---\n{log_snippet}"
    return send_text(webhook_url, content)
