# Nature Astronomy Daily Digest — 配置指南

## 1. 安装依赖

```bash
pip install feedparser requests beautifulsoup4 anthropic
```

## 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入真实值：

```bash
cp .env.example .env
```

编辑 `.env`：
- `ANTHROPIC_API_KEY`：从 console.anthropic.com 获取
- `EMAIL_FROM`：你的 Gmail 地址
- `EMAIL_TO`：收件地址（可以和 FROM 相同）
- `EMAIL_PASSWORD`：Gmail **App Password**（不是登录密码）

### 如何获取 Gmail App Password
1. Google 账户 → 安全性 → 两步验证（需先开启）
2. 搜索"应用专用密码" → 生成 → 复制 16 位密码

## 3. 手动测试运行

```bash
cd /Users/lenia/claude/nature_digest
source .env  # 或用下面的方式加载
export $(cat .env | xargs) && python digest.py
```

## 4. 设置每日定时任务（macOS cron）

```bash
crontab -e
```

添加一行（每天早上 8:00 运行）：

```
0 8 * * * cd /Users/lenia/claude/nature_digest && export $(cat .env | xargs) && /usr/bin/python3 digest.py >> /Users/lenia/claude/nature_digest/digest.log 2>&1
```

## 5. 文件说明

| 文件 | 说明 |
|------|------|
| `digest.py` | 主脚本 |
| `.env` | 密钥配置（不要上传到 git）|
| `seen_articles.json` | 已处理文章记录（自动生成）|
| `digest.log` | 运行日志（自动生成）|
