---
name: github-actions-ci-cd
description: 用 GitHub Actions 给财务 AI 项目做 CI/CD：push 后自动跑代码规范检查、pytest 测试、构建 Docker 镜像，并在通过后自动部署到阿里云服务器。
---

# 02 · CI/CD（GitHub Actions）

## 目标

- 每次 `git push` 自动跑：代码检查 → 单元测试 → 镜像构建
- 测试通过后自动部署到阿里云，不用再手动 `scp`
- 失败时 GitHub 上有红色 ❌，飞书收到通知

## 前置条件

- 已完成 `01-automated-testing`（有可运行的 pytest）
- 已完成 `03-docker`（有 Dockerfile）—— 若暂时没有，先跳过 build/deploy job
- 仓库 `zxcNB666PMZ/TB`，服务器 `8.140.220.172`

---

## 实施步骤

### 1. 本地加代码检查工具

```bash
cd /opt/finance-ai
.venv/bin/pip install ruff black
.venv/bin/ruff check .
.venv/bin/black --check .
```

在项目根加 `pyproject.toml`：

```toml
[tool.ruff]
line-length = 100
exclude = [".venv", "server/.venv"]

[tool.ruff.lint]
select = ["E", "F", "W", "I"]   # 语法错误、未使用变量、导入顺序

[tool.black]
line-length = 100
```

### 2. 建 SSH 部署密钥（不要用密码）

在**本地**生成一对专供部署的密钥：

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/deploy_key -N ""
```

把公钥追加到服务器：

```bash
ssh-copy-id -i ~/.ssh/deploy_key.pub root@8.140.220.172
# 或手动：cat deploy_key.pub >> /root/.ssh/authorized_keys
```

验证免密登录：

```bash
ssh -i ~/.ssh/deploy_key root@8.140.220.172 "echo deploy-ok"
```

### 3. 配置 GitHub Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 值 |
|---|---|
| `SSH_HOST` | `8.140.220.172` |
| `SSH_USER` | `root` |
| `SSH_PRIVATE_KEY` | `deploy_key` 文件的**全部内容** |
| `PGPASSWORD_TEST` | `Finance2026ok`（测试库密码） |

### 4. `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, feat/feishu-bot]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff black
      - run: ruff check .
      - run: black --check .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_USER: finance
          POSTGRES_PASSWORD: ${{ secrets.PGPASSWORD_TEST }}
          POSTGRES_DB: finance_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: 安装依赖
        run: |
          pip install -r server/requirements.txt
          pip install pytest
      - name: 建表
        env:
          PGPASSWORD: ${{ secrets.PGPASSWORD_TEST }}
        run: psql -h 127.0.0.1 -U finance -d finance_test -f server/schema.sql
      - name: 跑测试
        env:
          PGHOST: 127.0.0.1
          PGPORT: 5432
          PGUSER: finance
          PGPASSWORD: ${{ secrets.PGPASSWORD_TEST }}
          PGDATABASE: finance_test
        run: pytest -q
```

### 5. `.github/workflows/deploy.yml`（测试通过后自动部署）

```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_run:
    workflows: [CI]
    types: [completed]

jobs:
  deploy:
    if: github.event_name == 'push' || github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: 上传代码到服务器
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          source: "server/*"
          target: "/opt/finance-ai"
          strip_components: 1
          overwrite: true

      - name: 重启服务
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/finance-ai
            systemctl restart finance-ai
            systemctl restart finance-bot
            sleep 5
            systemctl is-active finance-ai finance-bot
```

### 6. 推送验证

```bash
git add .github pyproject.toml
git commit -m "ci: 添加 GitHub Actions 流水线"
git push origin feat/feishu-bot
```

打开 https://github.com/zxcNB666PMZ/TB/actions 看运行结果。

---

## 验收标准

- [ ] push 后 Actions 页面出现 CI 运行记录
- [ ] lint 失败时（故意加个语法错误）流水线变红
- [ ] test 通过后，服务器上 `/opt/finance-ai/app.py` 的修改时间被更新
- [ ] 部署后 `curl http://8.140.220.172:8501` 返回 200

## 常见坑

| 坑 | 说明 |
|---|---|
| `scp-action` 把整个仓库传上去 | 用 `source: "server/*"` + `strip_components: 1` 只传 server 目录内容 |
| 密钥格式：多行私钥 | 粘贴时要包含 `-----BEGIN` 和 `-----END` 整段 |
| 部署覆盖了 `.env` | `.env` 不在仓库里，不会被覆盖；但**别把 `.env` 提交进 git** |
| 服务重启失败但流水线显示成功 | 最后加 `systemctl is-active` 检查，非 0 会失败 |
| 免费的 Actions 分钟数 | 公开仓库免费；私有仓库每月 2000 分钟，够用 |
