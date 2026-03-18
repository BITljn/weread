# 微信读书自动化 - 部署目录

## 运行方式

```bash
# 执行阅读任务（指定用户）
./run_weread.sh admin

# 添加新用户
./add_user.sh 新用户名
./add_user.sh 新用户 -w "企业微信Webhook地址"
```

## 直接运行 main

```bash
./venv/bin/python main.py -u admin
./venv/bin/python main.py -u admin -b 三体
```

## 配置

- `global.json` - 全局配置
- `data/users/<用户>/config.json` - 用户私有配置
- `data/users/<用户>/books.txt` - 用户读书列表
