# 财务 AI 系统 · 服务器部署包

> 运行在阿里云 ECS（Ubuntu 22.04 / 2核2G），数据库使用本机 PostgreSQL。
> 与 Streamlit Cloud 版本（`main` 分支）相互独立。

## 组件

| 文件 | 作用 |
|---|---|
| `app.py` | Streamlit 网页版（登录 / 发票识别 / 台账 / 图表 / AI Agent） |
| `db.py` | PostgreSQL 访问层（连接池、参数化查询） |
| `bot_server.py` | 飞书机器人（长连接 + 智谱 Function Calling） |
| `schema.sql` | 数据库建表脚本 |
| `requirements.txt` | Python 依赖（不含 PyTorch，2G 内存可跑） |
| `finance-ai.service` | systemd：网页服务 |
| `finance-bot.service` | systemd：飞书机器人 |
| `.env.example` | 配置模板 |

## 部署步骤

```bash
# 1. 系统依赖
apt update && apt install -y python3-pip python3-venv postgresql postgresql-contrib curl git

# 2. 建库
sudo -u postgres psql -c "CREATE USER finance WITH PASSWORD '你的密码';"
sudo -u postgres psql -c "CREATE DATABASE finance OWNER finance;"
sudo -u postgres psql -d finance -c "GRANT ALL ON SCHEMA public TO finance;"

# 3. 上传代码到 /opt/finance-ai，然后建表
cd /tmp && PGPASSWORD='你的密码' psql -h 127.0.0.1 -U finance -d finance -f /opt/finance-ai/schema.sql

# 4. Python 环境
cd /opt/finance-ai && python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 5. 配置
cp .env.example .env && vi .env   # 填 ZHIPU_API_KEY / PG* / FEISHU_*

# 6. 服务
cp finance-ai.service finance-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now finance-ai finance-bot
```

访问 `http://<公网IP>:8501`。

## 运维

```bash
systemctl status finance-ai finance-bot
systemctl restart finance-ai       # 改代码后重启网页
journalctl -u finance-bot -f       # 实时看飞书消息
```

## 注意

- `.env` **不要提交到 git**（含密钥）
- 数据库**不要**开放 5432 到公网
- 2G 内存机器不要安装 `langchain-huggingface` / `langchain-chroma`（PyTorch 会 OOM），财报 PDF 问答功能会自动关闭
