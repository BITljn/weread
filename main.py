#!/usr/bin/env python3
"""
微信读书自动化阅读程序

打开 Chrome 访问微信读书网页版，扫码登录后根据书名搜索并打开书籍，
模拟用户阅读指定时长后关闭浏览器。
"""

import argparse
import sys

# 提前解析 -h，避免未安装 selenium 时无法查看帮助
if "-h" in sys.argv or "--help" in sys.argv:
    _p = argparse.ArgumentParser(
        description="微信读书自动化阅读程序。未指定书名时，从读书列表中随机选取一本。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    从读书列表随机选书
  %(prog)s -b 三体            指定阅读《三体》
  %(prog)s --book 活着        指定阅读《活着》
  %(prog)s -u user1           使用 user1 用户
  %(prog)s -H                 无头模式（测试用）
  %(prog)s -h                 查看使用说明
        """,
    )
    _p.add_argument("-b", "--book", metavar="书名", help="指定要阅读的书名")
    _p.add_argument("-u", "--user", metavar="用户", default="admin", help="指定用户，默认 admin")
    _p.add_argument("-H", "--headless", action="store_true", help="强制无头模式（测试用）")
    _p.parse_args()
    sys.exit(0)

import json
import logging
import os
import platform
import random
import shutil
import signal
import sys
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import quote

from wechat_notify import (
    notify_error,
    notify_login_required,
    notify_login_success,
    notify_task_start,
    notify_task_summary,
)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

def _get_base_dir() -> Path:
    """安装模式下通过 WEREAD_HOME 指定数据目录，否则使用脚本所在目录"""
    if os.environ.get("WEREAD_HOME"):
        return Path(os.environ["WEREAD_HOME"])
    return Path(__file__).parent


BASE_DIR = _get_base_dir()
WEREAD_URL = "https://weread.qq.com"
SEARCH_URL_TEMPLATE = "https://weread.qq.com/web/search/books?keyword={keyword}"
LOGIN_TIMEOUT = 300  # 单次扫码等待超时（秒）
LOGIN_MAX_RETRIES = 2  # 超时后重试次数（共 1 + 2 = 3 次尝试）
PAGE_LOAD_TIMEOUT = 60  # 页面加载超时（秒），防止 driver.get() 无限阻塞
SCRIPT_TIMEOUT = 30  # 脚本执行超时（秒）
DRIVER_QUIT_TIMEOUT = 10  # driver.quit() 超时（秒），防止退出时卡死
GLOBAL_CONFIG_FILE = BASE_DIR / "global.json"  # 全局配置（根目录）
USER_CONFIG_ONLY_KEYS = ("wechat_webhook_url",)  # 仅能从用户私有配置读取，公共配置不可覆盖

DEFAULT_GLOBAL = {
    "book_list_file": "books.txt",
    "reading_duration": 60,
    "headless": False,
    "use_xvfb": False,
    "use_cookie_login": True,
}

DEFAULT_USER = {
    "wechat_webhook_url": "",
}

log = logging.getLogger(__name__)

# 用于 SIGTERM 时优雅退出（SIGINT/Ctrl+C 由 Python 默认转为 KeyboardInterrupt，已有处理）
_shutdown_requested = False


def _sigterm_handler(signum, frame):
    """处理 SIGTERM（kill、systemd stop 等），触发优雅退出"""
    global _shutdown_requested
    if _shutdown_requested:
        return
    _shutdown_requested = True
    log.warning("收到 SIGTERM，正在优雅退出...")
    sys.exit(143)  # 128 + 15


def get_user_paths(user: str) -> dict:
    """获取用户专属文件路径：cookies、二维码、阅读记录、读书列表、日志"""
    user_dir = BASE_DIR / "data" / "users" / user
    return {
        "user_dir": user_dir,
        "cookie_file": user_dir / "cookies.json",
        "qr_file": user_dir / "login.png",
        "last_read_file": user_dir / "last_read.json",
        "log_file": user_dir / "weread.log",
    }


def load_config(user: str = "admin") -> dict:
    """
    加载配置：全局配置 + 用户私有配置，用户配置覆盖全局配置。
    - 全局配置：根目录 global.json
    - 用户私有配置：data/users/{用户}/config.json（必须存在）
    - wechat_webhook_url 仅能从用户私有配置读取，全局配置不可覆盖
    """
    user_config_path = BASE_DIR / "data" / "users" / user / "config.json"
    if not user_config_path.exists():
        print(f"错误：用户配置文件不存在: {user_config_path}\n执行时必须提供用户私有配置，请创建该文件。", file=sys.stderr)
        sys.exit(1)

    # 全局配置（排除仅用户可配置项）
    public_config = DEFAULT_GLOBAL.copy()
    if GLOBAL_CONFIG_FILE.exists():
        try:
            with open(GLOBAL_CONFIG_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            for k, v in loaded.items():
                if k not in USER_CONFIG_ONLY_KEYS:
                    public_config[k] = v
        except Exception as e:
            logging.warning("加载全局配置失败 %s: %s", GLOBAL_CONFIG_FILE, e)

    # 用户私有配置（所有项均可覆盖公共配置）
    user_config = DEFAULT_USER.copy()
    try:
        with open(user_config_path, encoding="utf-8") as f:
            user_config.update(json.load(f))
    except Exception as e:
        logging.warning("加载用户配置失败 %s: %s", user_config_path, e)

    merged = {**public_config, **user_config}
    merged["_user"] = user
    merged["_paths"] = get_user_paths(user)
    return merged


def get_recent_log_lines(log_file: Path, lines: int = 50) -> str:
    """读取日志文件最后 N 行，用于错误通知"""
    if not log_file.exists():
        return ""
    try:
        with open(log_file, encoding="utf-8") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:]).strip()
    except Exception:
        return ""


def setup_logging(log_file: Path) -> None:
    """配置日志：同时输出到控制台和指定日志文件"""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # 清除已有的 handlers，避免重复
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    # 控制台
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(sh)

    # 文件
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(fh)


def should_use_headless(config: dict) -> bool:
    """
    判断是否使用无头模式，支持有/无图形界面的 Ubuntu 与 Mac。
    - 配置 use_xvfb=true：强制有头（通过 Xvfb 虚拟显示器），用于规避 headless 不统计时长的问题
    - 配置 headless=true：强制无头
    - Linux 且无 DISPLAY：自动无头（Ubuntu Server）
    - 否则：有头模式（Ubuntu 桌面 / Mac）
    """
    if config.get("use_xvfb", False):
        # 使用 Xvfb 虚拟显示器运行有头 Chrome，避免被检测为 headless 导致阅读时长不统计
        return False
    if config.get("headless", False):
        return True
    if platform.system() == "Linux" and not os.environ.get("DISPLAY"):
        return True  # 无图形界面，自动切换无头
    return False


def save_last_read(book_name: str, completed: bool, last_read_file: Path) -> None:
    """记录本次阅读的书名及是否读完，供下次选书时参考"""
    last_read_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(last_read_file, "w", encoding="utf-8") as f:
            json.dump({"book": book_name, "completed": completed}, f, ensure_ascii=False, indent=2)
        log.info("已记录阅读: %s，读完=%s", book_name, completed)
    except Exception as e:
        log.warning("保存阅读记录失败: %s", e)


def load_last_read(last_read_file: Path) -> dict | None:
    """加载上次阅读记录，返回 {book, completed} 或 None"""
    if not last_read_file.exists():
        return None
    try:
        with open(last_read_file, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "book" in data:
            return data
    except Exception as e:
        log.warning("加载阅读记录失败: %s", e)
    return None


def get_book_from_list(config: dict, exclude_completed: str | None = None) -> str | None:
    """
    从读书列表文件随机选取一本书。
    文件格式：每行一个书名。
    优先级：用户目录下存在 books.txt 时，直接使用（book_list_file 不生效）；否则按 book_list_file 解析。
    若 exclude_completed 非空，则排除该书（用于上次已读完时换新书）。
    """
    user_dir = config["_paths"]["user_dir"]
    default_user_books = user_dir / "books.txt"

    # 用户目录下有 books.txt 时，直接使用，book_list_file 不生效
    if default_user_books.exists():
        book_file = default_user_books
    else:
        book_file = Path(config["book_list_file"])
        if not book_file.is_absolute():
            book_file = user_dir / book_file
        # 兼容：用户目录下不存在时，尝试项目根目录（旧版位置）
        if not book_file.exists():
            fallback = BASE_DIR / Path(config["book_list_file"]).name
            if fallback.exists():
                book_file = fallback
                log.info("使用项目根目录的读书列表 %s（建议复制到 %s）", fallback, user_dir / config["book_list_file"])
            else:
                log.warning("读书列表文件不存在: %s", book_file)
                return None
    with open(book_file, encoding="utf-8") as f:
        books = [line.strip() for line in f if line.strip()]
    if not books:
        log.warning("读书列表为空")
        return None
    if exclude_completed:
        books = [b for b in books if b != exclude_completed]
        if not books:
            log.warning("读书列表中仅剩已读完的书 %s，将从中随机选取", exclude_completed)
            with open(book_file, encoding="utf-8") as f:
                books = [line.strip() for line in f if line.strip()]
    return random.choice(books) if books else None


def load_cookies(driver: webdriver.Chrome, cookie_file: Path) -> bool:
    """加载已保存的 cookies，返回是否成功加载。兼容旧版 weread_cookies.json"""
    to_load = cookie_file
    if not to_load.exists() and cookie_file.name == "cookies.json":
        legacy = BASE_DIR / "weread_cookies.json"
        if legacy.exists():
            to_load = legacy
            log.info("使用旧版 cookies 文件 %s（建议迁移到 %s）", legacy, cookie_file)
    if not to_load.exists():
        log.info("未找到已保存的 cookies 文件")
        return False
    try:
        with open(to_load, encoding="utf-8") as f:
            cookies = json.load(f)
        for cookie in cookies:
            if "expiry" in cookie:
                cookie["expiry"] = int(cookie["expiry"])
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        log.info("已从 %s 加载 %d 个 cookies", to_load, len(cookies))
        return True
    except Exception as e:
        log.warning("加载 cookies 失败: %s", e)
        return False


def save_cookies(driver: webdriver.Chrome, cookie_file: Path) -> None:
    """保存 cookies 到文件"""
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        cookies = driver.get_cookies()
        with open(cookie_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        log.info("登录状态已保存至 %s", cookie_file)
    except Exception as e:
        log.warning("保存 cookies 失败: %s", e)


def is_logged_in(driver: webdriver.Chrome) -> bool:
    """检测当前是否已登录"""
    try:
        # 有「书架」链接或没有「登录」按钮表示已登录
        nav = driver.find_elements(By.XPATH, "//a[contains(@href,'/web/shelf')]")
        if nav:
            return True
        login_btns = driver.find_elements(By.LINK_TEXT, "登录")
        if not login_btns:
            return True
        return False
    except Exception:
        return False


def get_chrome_path() -> str | None:
    """
    根据操作系统返回 Chrome/Chromium 可执行文件路径，便于跨平台支持。
    返回 None 时由 webdriver-manager 使用默认检测。
    """
    system = platform.system()
    # 优先使用 PATH 中的 chrome
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    # 常见安装路径
    if system == "Darwin":  # macOS
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
    else:
        return None
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def create_driver(headless: bool = False) -> webdriver.Chrome:
    """创建 Chrome WebDriver，支持有头/无头模式，适用于 Linux 与 macOS"""
    options = Options()
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,800")
    if headless:
        options.add_argument("--headless=new")  # Chrome 112+ 使用新无头模式；旧版可改为 --headless
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-software-rasterizer")
        # 伪装 User-Agent，降低 HeadlessChrome 指纹被检测概率（部分网站如微信读书会据此不统计时长）
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        log.info("无头模式：Chrome 在后台运行，截图将保存到 data/login.png 供扫码")
    # 跨平台：显式指定 Chrome 路径（若检测到），避免 Linux/Ubuntu 下找不到
    chrome_path = get_chrome_path()
    if chrome_path:
        options.binary_location = chrome_path
        log.info("检测到 Chrome: %s", chrome_path)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    # 反检测：在页面加载前注入脚本，降低自动化指纹被识别的概率
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """
        },
    )
    return driver


def quit_driver_safe(driver: webdriver.Chrome | None) -> None:
    """安全关闭浏览器，带超时，防止 quit() 卡死导致程序无法退出"""
    if not driver:
        return
    result = {"done": False, "error": None}

    def _quit():
        try:
            driver.quit()
            result["done"] = True
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_quit, daemon=True)
    t.start()
    t.join(timeout=DRIVER_QUIT_TIMEOUT)
    if t.is_alive():
        log.warning("driver.quit() 超时（%d 秒），Chrome 进程可能仍在运行，程序继续退出", DRIVER_QUIT_TIMEOUT)
    elif result.get("error"):
        log.warning("driver.quit() 异常: %s", result["error"])


def wait_for_login(driver: webdriver.Chrome) -> bool:
    """
    等待用户扫码登录完成。
    通过检测 URL 变化或登录后可见元素判断。
    """
    log.info("等待扫码登录：请使用微信扫描页面上的二维码")
    log.info("若出现双重验证码，请在网页上输入验证码后继续等待")

    wait = WebDriverWait(driver, LOGIN_TIMEOUT, poll_frequency=1)

    try:
        # 登录成功后可能跳转到书架、首页或停留在当前页但二维码消失
        # 检测：当前 URL 包含 /web/shelf 或 /web/reader，或二维码容器消失
        def login_success(d):
            if _shutdown_requested:
                raise KeyboardInterrupt("收到退出信号")
            url = d.current_url
            # 已跳转到书架或阅读页
            if "/web/shelf" in url or "/web/reader/" in url:
                return True
            # 仍在首页，检查是否还有登录弹窗（二维码）
            try:
                # 二维码/登录弹窗消失即表示已登录
                qr = d.find_elements(By.CSS_SELECTOR, "[class*='login']")
                if not qr:
                    return True
                # 检查是否有「书架」等登录后可见的导航
                nav = d.find_elements(By.XPATH, "//a[contains(@href,'/web/shelf')]")
                if nav:
                    return True
            except Exception:
                pass
            return False

        wait.until(login_success)
        log.info("登录成功")
        return True
    except Exception as e:
        log.error("登录超时或失败: %s", e)
        return False


def save_qr_code(driver: webdriver.Chrome, qr_file: Path) -> bool:
    """将登录二维码保存到指定路径"""
    qr_file.parent.mkdir(parents=True, exist_ok=True)
    qr_selectors = [
        "img[src*='qrcode']",
        "canvas",
        "[class*='qrcode'] img",
        "[class*='login'] img",
        "[class*='qr']",
    ]
    for sel in qr_selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in els:
                if e.is_displayed():
                    try:
                        w = e.size["width"] if isinstance(e.size, dict) else e.size.width
                    except Exception:
                        w = 100
                    if w > 50:
                        e.screenshot(str(qr_file))
                        log.info("二维码已保存至 %s", qr_file)
                        return True
        except Exception:
            continue
    # 备选：截取整个页面（登录弹窗通常居中）
    try:
        driver.save_screenshot(str(qr_file))
        log.info("已保存页面截图至 %s（若二维码不清晰可手动查看）", qr_file)
        return True
    except Exception as e:
        log.warning("保存二维码失败: %s", e)
    return False


def click_login(driver: webdriver.Chrome, qr_file: Path, save_qr: bool = True, headless: bool = False) -> bool:
    """点击登录按钮，打开二维码，保存到指定路径。无头模式下用户需下载该图扫码"""
    wait = WebDriverWait(driver, 15)
    login_selectors = [
        (By.LINK_TEXT, "登录"),
        (By.XPATH, "//a[contains(text(),'登录')]"),
        (By.XPATH, "//span[contains(text(),'登录')]"),
        (By.CSS_SELECTOR, "a.navBar_link"),
    ]
    for by, value in login_selectors:
        try:
            btn = wait.until(EC.element_to_be_clickable((by, value)))
            log.info("点击登录按钮，打开二维码")
            btn.click()
            time.sleep(3 if headless else 2)  # 无头模式多等 1 秒确保二维码渲染
            if save_qr:
                save_qr_code(driver, qr_file)
                if headless:
                    log.info("无头模式：请下载 %s 到本地，用微信扫码登录", qr_file)
            return True
        except Exception:
            continue
    log.warning("未找到登录按钮")
    return False


def search_and_open_book(driver: webdriver.Chrome, book_name: str) -> bool:
    """搜索书名并打开第一本书"""
    url = SEARCH_URL_TEMPLATE.format(keyword=quote(book_name))
    log.info("搜索书籍: %s", book_name)
    driver.get(url)
    time.sleep(3)

    wait = WebDriverWait(driver, 15)
    # 书籍链接格式: /web/reader/{bookId}
    book_link_selectors = [
        (By.CSS_SELECTOR, "a[href*='/web/reader/']"),
        (By.XPATH, "//a[contains(@href,'/web/reader/')]"),
    ]
    for by, value in book_link_selectors:
        try:
            links = wait.until(EC.presence_of_all_elements_located((by, value)))
            if links:
                # 取第一个有效书籍链接（排除可能混入的其他链接）
                for link in links:
                    href = link.get_attribute("href") or ""
                    if "/web/reader/" in href and "search" not in href:
                        link.click()
                        time.sleep(3)
                        log.info("已打开书籍: %s", book_name)
                        return True
        except Exception:
            continue

    log.error("未找到匹配的书籍，请检查书名或网络")
    return False


def get_reading_progress(driver: webdriver.Chrome) -> str:
    """尝试从页面获取阅读进度（如 已读到 12%）"""
    for sel in [".readerFooter_progress", "[class*='readerFooter'][class*='progress']", ".readerTopBar_title"]:
        try:
            el = driver.find_elements(By.CSS_SELECTOR, sel)
            if el and el[0].text:
                return (el[0].text or "").strip()[:40]
        except Exception:
            pass
    return ""


def turn_page(driver: webdriver.Chrome, page_num: int = 0) -> bool:
    """
    模拟翻页：点击网页中的「下一页」虚拟按钮。
    微信读书的下一页按钮需用 dispatchEvent 模拟带坐标的鼠标事件才能生效。
    """
    # 定位「下一页」按钮的多种选择器
    next_page_selectors = [
        (By.XPATH, "//*[contains(text(),'下一页')]"),
        (By.XPATH, "//*[@class='readerFooter_button' and contains(text(),'下一页')]"),
        (By.CSS_SELECTOR, ".readerFooter_button"),
    ]
    for by, value in next_page_selectors:
        try:
            elements = driver.find_elements(by, value)
            btn = None
            for el in elements:
                if "下一页" in (el.text or ""):
                    btn = el
                    break
            if btn is None and elements:
                # readerFooter_button 可能有两个，取最后一个（通常是下一页）
                btn = elements[-1]
            if btn:
                # 滚动到按钮可见
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.3)
                # 使用 dispatchEvent 模拟带坐标的点击（普通 click 可能无效）
                driver.execute_script("""
                    var el = arguments[0];
                    var rect = el.getBoundingClientRect();
                    var evt = new MouseEvent('click', {
                        view: window, bubbles: true, cancelable: true,
                        clientX: rect.left + rect.width/2,
                        clientY: rect.top + rect.height/2
                    });
                    el.dispatchEvent(evt);
                """, btn)
                log.info("翻页成功，当前第 %d 页", page_num)
                return True
        except Exception:
            continue
    log.warning("翻页失败，未找到「下一页」按钮")
    return False


def simulate_reading(driver: webdriver.Chrome, duration: int) -> dict:
    """
    模拟用户阅读：随机滚动、翻页、停顿。当「下一页」消失时不再尝试翻页，仅滚动或等待至耗时结束。
    返回摘要 dict: {book_ended, scroll_count, turn_count, duration_sec}。
    """
    log.info("开始模拟阅读，目标时长 %d 秒", duration)
    start = time.time()
    page_num = 1
    scroll_count = 0
    turn_count = 0
    book_ended = False  # 书籍读完（下一页消失）后不再尝试翻页

    # 聚焦阅读区域
    try:
        reader = driver.find_element(By.CSS_SELECTOR, ".readerContent, .wr_canvasContainer, .reader_container")
        reader.click()
        time.sleep(0.5)
        log.info("已聚焦阅读区域")
    except Exception:
        log.debug("未找到阅读区域，继续执行")

    while time.time() - start < duration and not _shutdown_requested:
        elapsed = int(time.time() - start)
        remaining = max(0, duration - elapsed)

        # 随机选择：滚动 或 翻页（书籍读完则只做滚动）
        if random.random() < 0.5 or book_ended:
            scroll_amount = random.randint(300, 600)
            driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            scroll_count += 1
            if book_ended:
                log.info("已读完本书，继续滚动浏览最后一页，已阅读 %d 秒，剩余 %d 秒", elapsed, remaining)
            else:
                log.info("滚动阅读 (第 %d 次)，已阅读 %d 秒，剩余 %d 秒", scroll_count, elapsed, remaining)
        else:
            if turn_page(driver, page_num):
                page_num += 1
                turn_count += 1
            else:
                book_ended = True
                log.info("已到达本书末尾（下一页消失），不再翻页，等待阅读时长结束")
            progress = get_reading_progress(driver)
            if progress:
                log.info("阅读进度: %s，已阅读 %d 秒，剩余 %d 秒", progress, elapsed, remaining)
            else:
                log.info("已阅读 %d 秒，剩余 %d 秒，累计翻页 %d 次", elapsed, remaining, turn_count)

        # 随机停顿 3-8 秒（可被 Ctrl+C 中断）
        pause = random.uniform(3, 8)
        try:
            time.sleep(min(pause, remaining))
        except KeyboardInterrupt:
            log.info("阅读被中断，正在退出...")
            raise  # 交由 main 的 except 处理，确保 finally 执行

    duration_sec = time.time() - start
    log.info("阅读完成，共滚动 %d 次、翻页 %d 次，总耗时 %.1f 秒", scroll_count, turn_count, duration_sec)
    return {
        "book_ended": book_ended,
        "scroll_count": scroll_count,
        "turn_count": turn_count,
        "duration_sec": duration_sec,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="微信读书自动化阅读程序。未指定书名时，从读书列表中随机选取一本。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    从读书列表随机选书
  %(prog)s -b 三体            指定阅读《三体》
  %(prog)s --book 活着        指定阅读《活着》
  %(prog)s -h                 查看使用说明
        """,
    )
    parser.add_argument(
        "-b", "--book",
        metavar="书名",
        help="指定要阅读的书名。不指定则从读书列表随机选取",
    )
    parser.add_argument(
        "-H", "--headless",
        action="store_true",
        help="强制无头模式，用于在 Mac/Ubuntu 桌面测试无头行为",
    )
    parser.add_argument(
        "-u", "--user",
        metavar="用户",
        default="admin",
        help="指定用户，加载对应用户配置和独立数据（cookies、阅读记录等），默认 admin",
    )
    args = parser.parse_args()

    # 注册 SIGTERM 处理器，支持 kill、systemd stop 等场景下的优雅退出
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sigterm_handler)

    user = args.user or "admin"
    config = load_config(user)
    paths = config["_paths"]
    setup_logging(paths["log_file"])
    headless = args.headless or should_use_headless(config)
    if headless and not config.get("headless", False):
        log.info("检测到无图形界面（Linux 无 DISPLAY），自动启用无头模式")
    log.info("用户: %s | 配置: 读书列表=%s, 阅读时长=%d秒, 使用Cookie登录=%s, 无头模式=%s",
             user, config["book_list_file"], config["reading_duration"], config["use_cookie_login"], headless)
    log.info("========== 微信读书自动化阅读程序启动 ==========")

    book_name = args.book
    if not book_name:
        last = load_last_read(paths["last_read_file"])
        exclude = last["book"] if (last and last.get("completed")) else None
        if exclude:
            log.info("上次已读完《%s》，本次将选取新书", exclude)
        book_name = get_book_from_list(config, exclude_completed=exclude)
        if book_name:
            log.info("未指定书名，从读书列表随机选取: %s", book_name)
    if not book_name:
        log.error("未指定书名且读书列表为空或不存在，程序退出。请使用 -b 指定书名或配置 books.txt")
        return 1

    log.info("目标书籍: %s", book_name)
    driver = None
    exit_code = 0
    use_cookie = config.get("use_cookie_login", True)
    reading_duration = config.get("reading_duration") or config.get("duration", 60)
    webhook_url = config.get("wechat_webhook_url", "")

    # 任务开始通知
    if webhook_url:
        notify_task_start(webhook_url, book_name, user)

    try:
        log.info("步骤 1/5: 启动 Chrome 浏览器")
        driver = create_driver(headless=headless)
        log.info("步骤 2/5: 访问微信读书 %s", WEREAD_URL)
        driver.get(WEREAD_URL)
        time.sleep(2)

        # 尝试加载已保存的 cookies（仅当配置启用时）
        if use_cookie and load_cookies(driver, paths["cookie_file"]):
            log.info("已加载本地 cookies，刷新页面验证")
            driver.refresh()
            time.sleep(3)
            if is_logged_in(driver):
                log.info("使用已保存的登录状态，跳过扫码")

        # 未登录则扫码（登录过期场景），超时后重试 2 次
        if not is_logged_in(driver):
            log.info("步骤 3/5: 需要登录，进入扫码流程（超时 %d 秒，最多重试 %d 次）", LOGIN_TIMEOUT, LOGIN_MAX_RETRIES)
            if not click_login(driver, paths["qr_file"], save_qr=True, headless=headless):
                log.warning("未找到登录按钮，假定已登录，继续执行")
            else:
                login_success_flag = False
                for attempt in range(1, 1 + LOGIN_MAX_RETRIES + 1):
                    if attempt > 1:
                        log.info("第 %d 次尝试：刷新页面并重新获取二维码", attempt)
                        driver.get(WEREAD_URL)
                        time.sleep(2)
                        if not click_login(driver, paths["qr_file"], save_qr=True, headless=headless):
                            log.warning("重试时未找到登录按钮")
                            break
                    # 登录过期：发送二维码和扫码说明
                    if webhook_url and paths["qr_file"].exists():
                        notify_login_required(webhook_url, paths["qr_file"], user)
                    if wait_for_login(driver):
                        login_success_flag = True
                        save_cookies(driver, paths["cookie_file"])
                        if webhook_url:
                            notify_login_success(webhook_url, user)
                        break
                    log.warning("第 %d 次扫码超时（%d 秒），剩余重试 %d 次", attempt, LOGIN_TIMEOUT, 1 + LOGIN_MAX_RETRIES - attempt)
                if not login_success_flag:
                    err_msg = f"扫码登录失败：在 {1 + LOGIN_MAX_RETRIES} 次尝试内均未完成扫码（每次等待 {LOGIN_TIMEOUT} 秒）"
                    log.error("%s，程序退出", err_msg)
                    if webhook_url:
                        notify_error(webhook_url, err_msg, get_recent_log_lines(paths["log_file"], 30), user)
                    return 1
        else:
            log.info("步骤 3/5: 登录状态有效，跳过")

        # 回到首页或直接搜索（登录后可能在确认页）
        if "/web/confirm" in driver.current_url:
            log.info("检测到确认页，返回首页")
            driver.get(WEREAD_URL)
            time.sleep(2)

        log.info("步骤 4/5: 搜索并打开书籍")
        if not search_and_open_book(driver, book_name):
            log.error("打开书籍失败，程序退出")
            return 1

        log.info("步骤 5/5: 模拟阅读（时长 %d 秒）", reading_duration)
        summary = simulate_reading(driver, duration=reading_duration)
        save_last_read(book_name, summary["book_ended"], paths["last_read_file"])
        log.info("========== 所有步骤执行完成 ==========")
        exit_code = 0

        # 任务完成摘要通知
        if webhook_url:
            notify_task_summary(
                webhook_url,
                book_name,
                scroll_count=summary["scroll_count"],
                turn_count=summary["turn_count"],
                duration_sec=summary["duration_sec"],
                book_ended=summary["book_ended"],
                user=user,
            )

    except KeyboardInterrupt:
        log.warning("用户中断 (Ctrl+C)，正在退出...")
        exit_code = 130
    except Exception as e:
        log.exception("发生错误: %s", e)
        exit_code = 1
        # 错误通知：发送错误信息和最近日志
        if webhook_url:
            for h in logging.getLogger().handlers:
                h.flush()
            err_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            log_snippet = get_recent_log_lines(paths["log_file"], 50)
            notify_error(webhook_url, err_msg, log_snippet, user)
    finally:
        if driver:
            log.info("正在关闭 Chrome 浏览器...")
            quit_driver_safe(driver)
            log.info("浏览器已关闭")
        log.info("程序退出，退出码: %d", exit_code)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
