# 微信读书自动化阅读程序

使用 Chrome 浏览器自动化访问微信读书网页版，扫码登录后根据书名搜索并打开书籍，模拟用户阅读指定时长后关闭浏览器。

**支持平台**：Linux (Ubuntu) / macOS

## 环境要求

- Python 3.8+
- Chrome 或 Chromium 浏览器
- 网络连接
- 有图形界面：直接运行；无图形界面（如 Ubuntu Server）：设置 `headless: true`，二维码保存到 `data/users/{用户}/login.png` 供下载扫码

## 安装

```bash
pip install -r requirements.txt
```

## 平台说明

### Ubuntu / Linux

1. **安装 Chrome 或 Chromium**（二选一）：

   ```bash
   # 方式一：Google Chrome
   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
   sudo dpkg -i google-chrome-stable_current_amd64.deb
   sudo apt-get install -f

   # 方式二：Chromium（系统自带源）
   sudo apt update
   sudo apt install chromium-browser
   ```

2. **依赖**（Chromium 可能需要）：

   ```bash
   sudo apt install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
   ```

3. **无图形界面（Ubuntu Server / SSH）**：在 `global.json` 中设置 `"headless": true` 即可直接运行，无需 Xvfb：

   - Chrome 在后台运行，不依赖显示器
   - 截图、翻页等操作均可正常执行
   - 首次登录时二维码会保存到 `data/users/{用户}/login.png`，用 `scp` 等方式下载到本地后用微信扫码
   - 建议同时设置 `"use_cookie_login": true`，登录一次后后续可免扫码

### Ubuntu Server（无图形界面）

在无显示器的服务器上运行，需在 `global.json` 中设置 `"headless": true`：

```json
{
  "headless": true,
  "use_cookie_login": true
}
```

**首次登录流程**：
1. 运行程序，点击登录后二维码会保存到 `data/users/{用户}/login.png`
2. 用 `scp user@server:/path/to/weread/data/users/admin/login.png .` 下载到本地（admin 为默认用户）
3. 用微信扫描该图片完成登录
4. 登录成功后 cookies 会保存，下次可免扫码

**截图**：无头模式下 `driver.save_screenshot()` 和 `element.screenshot()` 均可正常使用，二维码保存到 `data/users/{用户}/login.png` 即依赖此能力。

### macOS

1. **安装 Chrome**：

   ```bash
   # 使用 Homebrew
   brew install --cask google-chrome
   ```

   或从 [Chrome 官网](https://www.google.com/chrome/) 下载安装。

2. 首次运行若提示「无法验证开发者」，请在 **系统设置 → 隐私与安全性** 中允许运行。

## 命令行参数

| 参数 | 说明 |
|------|------|
| `-h`, `--help` | 显示程序使用说明并退出 |
| `-b 书名`, `--book 书名` | 指定要阅读的书名。不指定则从读书列表中随机选取一本 |
| `-u 用户`, `--user 用户` | 指定用户，默认 admin。不同用户有独立的 cookies、阅读记录和部分配置 |
| `-H`, `--headless` | 强制无头模式，用于在 Mac/Ubuntu 桌面测试无头行为 |

### 使用示例

```bash
# 查看使用说明
python main.py -h

# 从读书列表随机选书（需先配置 books.txt）
python main.py

# 指定阅读《三体》
python main.py -b 三体
python main.py --book 三体

# 在 Mac/Ubuntu 桌面模拟无头模式测试
python main.py -H -b 三体

# 使用指定用户（默认 admin）
python main.py -u admin -b 三体
python main.py -u user1
```

### 运行环境与模式

| 环境 | 行为 | 说明 |
|------|------|------|
| Ubuntu 有图形 | 有头模式 | 弹出 Chrome 窗口，二维码直接显示 |
| Ubuntu 无图形 (Server) | **自动**无头 | 检测无 DISPLAY 时自动切换，二维码保存到 `data/users/{用户}/login.png` |
| Mac | 有头模式 | 弹出 Chrome 窗口；加 `-H` 可测试无头 |
| 任意环境 | 强制无头 | `global.json` 中 `"headless": true` 或命令行 `-H` |

同一份代码和配置可在三种环境下运行，无需修改。

## 配置

### 公共配置与用户私有配置

- **全局配置**：根目录 `global.json`，扁平结构，**不含 `users` 键**
- **用户私有配置**：`data/users/{用户}/config.json`，**执行时必须存在**
- 用户私有配置中的任意项均可覆盖公共配置
- **`wechat_webhook_url` 仅能从用户私有配置读取**，公共配置中即使填写也会被忽略

### 用户私有配置结构 (data/users/{用户}/config.json)

**必须存在**，否则程序拒绝执行。私有配置中所有项均可覆盖公共配置。

| 字段 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| book_list_file | string | 读书列表文件名；用户目录有 books.txt 时不生效 | 使用全局配置 |
| reading_duration | number | 每次阅读时长（秒），也支持 `duration` | 使用公共配置 |
| use_cookie_login | boolean | 是否使用 Cookie 登录（免扫码），默认来自全局 | 使用全局配置 |
| wechat_webhook_url | string | 企业微信机器人 Webhook（**仅能在此配置**） | "" |

**读书列表路径**：`book_list_file` 为相对路径时，解析为 `data/users/{用户}/{book_list_file}`。

**示例**（`data/users/admin/config.json`）：

```json
{
  "book_list_file": "books.txt",
  "reading_duration": 90,
  "wechat_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
}
```

### global.json 示例（全局配置）

```json
{
  "execution_time": "",
  "book_list_file": "books.txt",
  "reading_duration": 60,
  "headless": true,
  "use_cookie_login": true
}
```

### 配置项说明

| 配置项 | 作用域 | 说明 | 默认值 |
|--------|--------|------|--------|
| book_list_file | 公共/用户 | 读书列表文件名，用户私有目录下解析为 `data/users/{用户}/` | books.txt |
| reading_duration | 公共/用户 | 每次阅读时长（秒） | 60 |
| headless | 公共/用户 | 无头模式 | false |
| use_cookie_login | 全局/用户 | 是否使用 Cookie 登录（免扫码） | true |
| wechat_webhook_url | **仅用户** | 企业微信机器人 Webhook，公共配置不可覆盖 | "" |

### 用户数据目录

每个用户的数据存放在 `data/users/{用户}/`：
- `config.json`：用户私有配置（**必须**）
- `books.txt`：读书列表（每行一书名，与 `book_list_file` 对应）
- `cookies.json`：登录 cookies
- `login.png`：登录二维码（扫码时生成）
- `last_read.json`：上次阅读记录
- `weread.log`：执行日志（指定用户时写入该目录）

### 添加用户 (add_user.py)

使用 `add_user.py` 创建新用户，自动创建目录、私有配置和读书列表。默认会复制根目录的 `books.txt` 到用户目录。

```bash
# 查看帮助
python add_user.py -h

# 添加用户（默认复制根目录读书列表）
python add_user.py user1

# 添加用户并指定 Webhook
python add_user.py user1 -w "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"

# 添加用户并指定图书（可多次 -b）
python add_user.py user1 -b 三体 -b 活着 -b 人类简史

# 从文件导入图书列表
python add_user.py user1 -f my_books.txt

# 不复制根目录，仅使用指定的书
python add_user.py user1 -n -b 三体 -b 活着

# 组合使用
python add_user.py user1 -w "https://..." -b 三体 -f shared_books.txt
```

| 选项 | 说明 |
|------|------|
| `-w`, `--webhook <url>` | 企业微信 Webhook 地址 |
| `-b`, `--book <书名>` | 添加一本书，可多次使用 |
| `-f`, `--file <文件>` | 从文件读取图书列表（每行一书名） |
| `-n`, `--no-copy` | 不复制根目录 books.txt |

### 企业微信通知（crontab 场景）

当配置 `wechat_webhook_url` 后，程序会在以下时机通过企业微信 Bot 发送通知：

- **任务开始**：程序启动时，告知目标书籍
- **登录过期**：Cookie 失效需扫码时，发送 data 目录下的二维码图片 + 扫码说明
- **登录成功**：扫码完成后，告知登录成功并继续执行
- **任务完成**：阅读结束后，发送摘要（书籍、阅读时长、滚动/翻页次数等）
- **执行出错**：发生异常时，发送错误信息和最近日志

获取 Webhook 地址：在企业微信群中添加机器人，从机器人信息卡中复制 Webhook 地址。

**crontab 示例**（每天 9 点执行）：

```bash
0 9 * * * cd /path/to/weread && /path/to/python main.py >> log/cron.log 2>&1
```

## 读书列表 (books.txt)

每行一个书名。未使用 `-b` 指定书名时，程序会从此列表中**随机**选取一本。

读书列表优先级：
- **用户目录下存在 `books.txt`** 时，直接使用该文件，`book_list_file` 配置不生效
- 否则按 `book_list_file` 解析（默认 `books.txt`），用户目录不存在时回退到项目根目录

```
三体
活着
人类简史
```

## 日志

- 控制台：实时输出
- 文件：`data/users/{用户}/weread.log`（按用户分别记录）

## 首次登录

点击登录后，二维码会保存到 `data/users/{用户}/login.png`，便于远程或无头环境扫码。

## 流程说明

1. **启动浏览器**：以非无头模式打开 Chrome，访问 [weread.qq.com](https://weread.qq.com)
2. **登录**：根据配置使用 Cookie 或扫码；扫码时二维码保存至 `data/users/{用户}/login.png`
3. **搜索书籍**：从 `-b` 参数或读书列表随机获取书名，搜索并打开第一本
4. **模拟阅读**：随机滚动、翻页，持续 `reading_duration` 秒
5. **关闭**：完成后自动关闭浏览器

## 注意事项

- 若出现「双重验证码」，请在网页上手动输入验证码
- 微信读书禁止使用第三方插件或修改过的客户端，本程序仅供个人学习使用，请勿滥用
- 若微信读书改版，页面选择器可能需要调整

## 常见问题

| 问题 | 解决方式 |
|------|----------|
| Ubuntu: `Chrome not found` | 安装 Chrome 或 Chromium（见上方平台说明），或确认 `which google-chrome` / `which chromium-browser` 有输出 |
| Ubuntu: 依赖缺失 | 执行 `sudo apt install libnss3 libatk1.0-0 libgbm1` 等（见平台说明） |
| macOS: 无法打开 Chrome | 在系统设置中允许运行来自未知开发者的应用 |
| 无图形界面（Server） | 在 global.json 中设置 `"headless": true`，二维码会保存到 `data/users/{用户}/login.png`，用 scp 下载后扫码 |
| 无头模式截图失败 | 确认 Chrome 版本支持 headless，并已安装 `libgbm1` 等依赖 |
