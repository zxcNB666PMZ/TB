---
name: dockerize-finance-app
description: 用 Docker 和 docker compose 打包财务 AI 项目（Streamlit 网页 + 飞书机器人 + PostgreSQL），实现一条命令在任何机器上启动，彻底消除环境不一致问题。
---

# 03 · Docker 化

## 目标

- 换机器不用再敲 20 条安装命令，`docker compose up -d` 就起来
- 网页、机器人、数据库三个容器编排在一起
- 保留 systemd 的自动重启能力（Docker 自带 `restart: always`）

## 前置条件

- 服务器装好 Docker（见步骤 1）
- 已有 `server/` 目录（app.py / db.py / bot_server.py / requirements.txt / schema.sql）

---

## 实施步骤

### 1. 服务器安装 Docker

```bash
curl -fsSL https://get.docker.com | bash
systemctl enable --now docker
docker --version
docker compose version
```

> 国内拉镜像慢可配加速器：新建 `/etc/docker/daemon.json`
> ```json
> { "registry-mirrors": ["https://docker.m.daocloud.io"] }
> ```
> 然后 `systemctl restart docker`

### 2. 目录结构

```
/opt/finance-ai/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
├── schema.sql
├── app.py
├── bot_server.py
├── db.py
└── .env                 # 不打包进镜像，运行时挂载
```

### 3. `Dockerfile`

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 系统依赖：pdfplumber 需要，时区要设置
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

# 非 root 运行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
```

> **注意**：镜像里不要放 `app.py` 的 `EXPOSE 8502` 之类多余端口；机器人容器不需要端口。

### 4. `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:14
    restart: always
    environment:
      POSTGRES_USER: finance
      POSTGRES_PASSWORD: ${PGPASSWORD}
      POSTGRES_DB: finance
      TZ: Asia/Shanghai
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U finance -d finance"]
      interval: 10s
      timeout: 5s
      retries: 10
    # 不暴露端口到宿主机，只有同网络容器能访问
    expose:
      - "5432"

  web:
    build: .
    restart: always
    depends_on:
      db:
        condition: service_healthy
    environment:
      PGHOST: db
      PGPORT: 5432
      PGDATABASE: finance
      PGUSER: finance
      PGPASSWORD: ${PGPASSWORD}
      ZHIPU_API_KEY: ${ZHIPU_API_KEY}
      LOCAL_MCP: "false"
    ports:
      - "8501:8501"

  bot:
    build: .
    restart: always
    depends_on:
      db:
        condition: service_healthy
    environment:
      PGHOST: db
      PGPORT: 5432
      PGDATABASE: finance
      PGUSER: finance
      PGPASSWORD: ${PGPASSWORD}
      ZHIPU_API_KEY: ${ZHIPU_API_KEY}
      FEISHU_APP_ID: ${FEISHU_APP_ID}
      FEISHU_APP_SECRET: ${FEISHU_APP_SECRET}
    command: ["python", "bot_server.py"]

volumes:
  pgdata:
```

创建 `.env`（与 compose 同目录，`docker compose` 会自动读取）：

```env
PGPASSWORD=Finance2026ok
ZHIPU_API_KEY=你的key
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

### 5. `.dockerignore`

```
.venv
__pycache__
*.pyc
.git
.env
*.bak
tests
```

### 6. 迁移现有数据（重要）

先把现有 PostgreSQL 数据导出：

```bash
# 旧环境（宿主机 PG）
PGPASSWORD='Finance2026ok' pg_dump -h 127.0.0.1 -U finance -d finance \
  --data-only --inserts > /tmp/data.sql
```

再导入到容器：

```bash
docker compose up -d db
sleep 10
docker compose exec -T db psql -U finance -d finance < /tmp/data.sql
```

### 7. 停掉 systemd 服务，改用 Docker

```bash
systemctl disable --now finance-ai finance-bot postgresql

cd /opt/finance-ai
docker compose up -d --build
docker compose ps
docker compose logs -f web
```

---

## 验收标准

- [ ] `docker compose ps` 三个容器都是 `Up (healthy)`
- [ ] 浏览器打开 `http://8.140.220.172:8501` 正常
- [ ] 飞书里发消息，机器人正常回复
- [ ] `docker compose restart` 后数据还在（volume 生效）
- [ ] 服务器重启后自动起来（`restart: always`）

## 常见坑

| 坑 | 说明 |
|---|---|
| compose 里的 `PGHOST` 写 `127.0.0.1` | 容器内要写服务名 `db` |
| 数据没持久化 | 忘了 `volumes: pgdata`，容器重建数据就没了 |
| `schema.sql` 只在首次初始化执行 | 已有数据卷不会重跑；改表用 Alembic（见 05） |
| 机器人容器抢连接 | 两个 bot 实例（宿主 + 容器）会互踢，先 `systemctl stop finance-bot` |
| 镜像太大 | 用 `-slim` 基础镜像 + `--no-cache-dir`，别装 torch |
| 时区不对导致日志/日期错 | `TZ=Asia/Shanghai` + 装 `tzdata` |
