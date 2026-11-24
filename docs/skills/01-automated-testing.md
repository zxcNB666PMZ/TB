---
name: pytest-finance-app
description: 给财务 AI 项目建立 pytest 自动化测试：覆盖数据库层、飞书机器人的工具函数、以及关键业务逻辑；使用独立测试库避免污染生产数据。
---

# 01 · 自动化测试（pytest）

## 目标

- 改一行代码，跑 `pytest -q` 就知道有没有弄坏别的功能
- 测试**不连生产库**，用独立的 `finance_test` 数据库
- 覆盖三类核心逻辑：数据库增删查、发票查询（含去重）、机器人工具函数

## 前置条件

- 代码在本地（`git clone` 到硬盘，不要放 U 盘）
- 已装依赖：`.venv/bin/pip install pytest pytest-cov`

---

## 实施步骤

### 1. 建测试数据库

```bash
sudo -u postgres psql -c "CREATE DATABASE finance_test OWNER finance;"
cd /tmp && PGPASSWORD='Finance2026ok' psql -h 127.0.0.1 -U finance -d finance_test -f /opt/finance-ai/schema.sql
```

### 2. 目录结构

```
/opt/finance-ai/
├── app.py
├── db.py
├── bot_server.py
└── tests/
    ├── conftest.py
    ├── test_db.py
    └── test_bot_tools.py
```

### 3. `tests/conftest.py`

```python
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在 import db 之前把连接指到测试库
os.environ.setdefault("PGHOST", "127.0.0.1")
os.environ.setdefault("PGPORT", "5432")
os.environ.setdefault("PGUSER", "finance")
os.environ.setdefault("PGPASSWORD", "Finance2026ok")
os.environ["PGDATABASE"] = "finance_test"

import db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_pool():
    db.init_pool(minconn=1, maxconn=3)
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    """每个用例前清空数据，保证互不影响"""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE invoices, transactions, users RESTART IDENTITY CASCADE;")
        conn.commit()
    yield
```

### 4. `tests/test_db.py`

```python
import db


def test_upsert_and_query():
    rows = [
        {
            "发票号码": "TEST001",
            "开票日期": "2026-11-10",
            "购买方名称": "测试公司",
            "销售方名称": "北京滴滴出行科技有限公司",
            "价税合计": 14.90,
            "发票类型": "普通发票",
            "文件名": "TEST001.pdf",
        }
    ]
    assert db.upsert_invoices(rows) == 1

    found, _ = db.query_invoices("滴滴")
    assert len(found) == 1
    assert float(found[0]["价税合计"]) == 14.90

    # 重复上传同一发票号码应更新而不是新增
    rows[0]["销售方名称"] = "滴滴出行科技有限公司"
    db.upsert_invoices(rows)
    assert len(db.all_invoices()) == 1


def test_query_not_found_returns_samples():
    rows = [
        {
            "发票号码": "TEST002",
            "开票日期": "2026-11-10",
            "购买方名称": "测试公司",
            "销售方名称": "北京易行出行旅游有限公司",
            "价税合计": 9.90,
            "发票类型": "普通发票",
            "文件名": "TEST002.pdf",
        }
    ]
    db.upsert_invoices(rows)
    found, samples = db.query_invoices("不存在的公司")
    assert found == []
    assert "北京易行出行旅游有限公司" in samples


def test_find_user():
    assert db.find_user("不存在的用户") is None
```

### 5. `tests/test_bot_tools.py`

```python
import bot_server


def test_query_invoice_db_formats_total(monkeypatch):
    monkeypatch.setattr(
        bot_server.db,
        "query_invoices",
        lambda name: (
            [{"价税合计": 14.9, "销售方名称": "北京滴滴出行科技有限公司"}],
            [],
        ),
    )
    result = bot_server.query_invoice_db("滴滴")
    assert "14.90" in result
    assert "1 张" in result


def test_query_invoice_db_not_found(monkeypatch):
    monkeypatch.setattr(bot_server.db, "query_invoices", lambda name: ([], ["甲公司"]))
    result = bot_server.query_invoice_db("不存在")
    assert "没有找到" in result
    assert "甲公司" in result


def test_overview_sums_all(monkeypatch):
    monkeypatch.setattr(
        bot_server.db,
        "all_invoices",
        lambda: [
            {"价税合计": 10, "销售方名称": "A"},
            {"价税合计": 20.5, "销售方名称": "B"},
        ],
    )
    result = bot_server.invoice_overview()
    assert "2 张" in result
    assert "30.50" in result
```

> `bot_server.py` 在被 import 时会 `load_dotenv` 并连数据库，测试时需保证 `.env` 存在。若不想连真库，可在 `conftest.py` 里事先 `os.environ["PGDATABASE"]="finance_test"`（已在上面设置）。

### 6. 运行

```bash
cd /opt/finance-ai
.venv/bin/pytest -v
.venv/bin/pytest --cov=. --cov-report=term-missing -q   # 看覆盖率
```

---

## 验收标准

- [ ] `pytest -v` 全绿
- [ ] 生产库 `finance` 里的数据没被改动（测试用 `finance_test`）
- [ ] 故意改坏 `db.query_invoices` 的 SQL，测试能报红
- [ ] 覆盖率 ≥ 50%（先覆盖 db.py 和 bot 工具函数）

## 常见坑

| 坑 | 说明 |
|---|---|
| 测试连到生产库 | 忘记设 `PGDATABASE=finance_test`，清表把真数据删了 |
| `db.py` 的全局 `_pool` 缓存 | 同一进程里改环境变量后再 `init_pool` 不会重建，需在 import 前设置 |
| `bot_server` import 即连飞书 | 目前它只在 `main()` 里启动长连接，import 是安全的；但会读 `.env` |
| Streamlit 页面难测 | 不要一开始就测 UI，先测纯函数和 db 层 |
