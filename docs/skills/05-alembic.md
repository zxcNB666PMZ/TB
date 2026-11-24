---
name: alembic-db-migrations
description: 用 Alembic 管理财务系统的 PostgreSQL 表结构演进：把现有 schema.sql 转为基线版本，之后改表通过版本脚本自动升级/回滚，并可与 CI 集成做迁移检查。
---

# 05 · 数据库迁移（Alembic）

## 目标

- 现在的表结构是手写 `schema.sql`，改一次表就要手动跑 SQL，容易漏、容易错
- 改成：每次结构变更生成一个**版本脚本**，`alembic upgrade head` 一键升级
- 支持回滚（`downgrade`），并且能在 CI 里检查"模型和数据库是否一致"

## 前置条件

- Python 环境：`.venv`
- 现有数据库 `finance` 已经有数据（7 张发票）**不能丢**

---

## 实施步骤

### 1. 安装

```bash
cd /opt/finance-ai
.venv/bin/pip install alembic
.venv/bin/pip freeze | grep -i alembic >> requirements.txt
```

### 2. 初始化（在项目根目录）

```bash
cd /opt/finance-ai
.venv/bin/alembic init migrations
```

生成：

```
alembic.ini
migrations/
├── env.py
├── script.py.mako
└── versions/
```

### 3. 配置 `alembic.ini`

把 `sqlalchemy.url` 留空（改从 `.env` 读），并指定脚本位置：

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os

# 留空，由 env.py 从环境变量拼
sqlalchemy.url =
```

### 4. 改 `migrations/env.py`

关键是把 `db.py` 里的连接信息接进来：

```python
import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = (
    f"postgresql+psycopg2://{os.getenv('PGUSER','finance')}:"
    f"{os.getenv('PGPASSWORD','')}@"
    f"{os.getenv('PGHOST','127.0.0.1')}:{os.getenv('PGPORT','5432')}/"
    f"{os.getenv('PGDATABASE','finance')}"
)


def run_migrations_offline():
    context.configure(url=url, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

> 若后续引入 SQLAlchemy 模型，再加 `target_metadata`；目前项目是裸 SQL，用**手写迁移脚本**更合适。

### 5. 把现有表结构固化为"基线版本"

因为库里已经有表，不能再 `create_all`。做法：手写一个 baseline 脚本，`upgrade()` 里**什么都不做**（表已存在），`downgrade()` 里 drop。

```bash
.venv/bin/alembic revision -m "baseline existing schema"
```

在生成的 `migrations/versions/xxxx_baseline_existing_schema.py` 里：

```python
"""baseline existing schema

Revision ID: xxxx
Revises:
Create Date: ...
"""

revision = "xxxx"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """表已由 schema.sql 建好，这里什么都不做"""
    pass


def downgrade() -> None:
    pass
```

打上版本标记：

```bash
.venv/bin/alembic stamp head
.venv/bin/alembic current     # 应显示基线版本号
```

### 6. 之后每次改表：生成新版本

**方式 A：手写（推荐，当前项目是裸 SQL）**

```bash
.venv/bin/alembic revision -m "add invoice category column"
```

编辑生成的文件：

```python
def upgrade() -> None:
    op.execute('ALTER TABLE invoices ADD COLUMN IF NOT EXISTS "费用类别" text')
    op.execute('CREATE INDEX IF NOT EXISTS idx_invoices_category ON invoices ("费用类别")')


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_invoices_category')
    op.execute('ALTER TABLE invoices DROP COLUMN IF EXISTS "费用类别"')
```

需要 `from alembic import op`。

**方式 B：自动对比（引入 SQLAlchemy 模型后）**

```bash
.venv/bin/alembic revision --autogenerate -m "sync models"
```

### 7. 应用迁移

```bash
.venv/bin/alembic upgrade head      # 升级到最新
.venv/bin/alembic history           # 看历史
.venv/bin/alembic downgrade -1      # 回退一步
.venv/bin/alembic current           # 当前版本
```

### 8. 部署时自动迁移

在 systemd 的 `ExecStartPre` 里加一行，或 Docker 的 entrypoint 里执行：

```ini
[Service]
ExecStartPre=/opt/finance-ai/.venv/bin/alembic -c /opt/finance-ai/alembic.ini upgrade head
ExecStart=...
```

> 注意工作目录：`WorkingDirectory=/opt/finance-ai` 必须对，否则找不到 `migrations/`。

### 9. CI 里加"迁移检查"（可选）

```yaml
- name: 检查迁移脚本可执行
  run: |
    alembic upgrade head
    alembic check || true   # 有模型时可用
```

---

## 验收标准

- [ ] `alembic current` 显示基线版本
- [ ] 新建一个迁移（加字段），`alembic upgrade head` 后表结构真的变了
- [ ] `alembic downgrade -1` 能干净回退
- [ ] 现有 7 条发票数据在迁移后仍在
- [ ] 版本脚本提交到 git，团队成员 `upgrade head` 后结构一致

## 常见坑

| 坑 | 说明 |
|---|---|
| 直接对已有库 `create_all` / autogenerate | 会生成"建表"脚本，执行时报表已存在错误 |
| 忘记 `stamp` 基线 | 第一次 `upgrade` 会重跑建表 |
| 中文列名 | 必须双引号：`"费用类别"`，否则语法错误 |
| 迁移里的 SQL 用 `psycopg2` 直接执行 | 用 `op.execute()`，Alembic 会纳入事务 |
| `alembic.ini` 里写死密码 | 密码放 `.env`，别提交到 git |
| 生产环境先 updaterade 再部署代码 | 顺序：先迁移（兼容旧代码）→ 再发新代码，避免新旧代码抢表结构 |
| 回滚丢数据 | `downgrade` 里 `DROP COLUMN` 会丢该列数据，生产回滚前先备份 |
