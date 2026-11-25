# -*- coding: utf-8 -*-
"""pytest 公共配置：把数据库指向独立的测试库 finance_test，绝不碰生产数据。"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ⚠️ 必须在 import db 之前设置：db.py 里的 load_dotenv 不会覆盖已存在的环境变量
os.environ["PGDATABASE"] = "finance_test"
os.environ.setdefault("PGHOST", "127.0.0.1")
os.environ.setdefault("PGPORT", "5432")
os.environ.setdefault("PGUSER", "finance")

import db  # noqa: E402
import invoice_parser  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """确认测试库可用；不可用时整组跳过（而不是误连生产库）"""
    assert db._conn_kwargs()["dbname"] == "finance_test", "测试必须使用 finance_test 库"
    try:
        db.ping()
    except Exception as exc:
        pytest.skip(f"测试库 finance_test 不可用，请先执行 scripts/create_test_db.sh（{exc}）")
    yield


@pytest.fixture()
def clean_invoices():
    """每个用例前后都清掉 TEST 开头的测试发票，保证互不干扰"""
    def _purge():
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM invoices WHERE \"发票号码\" LIKE 'TEST%%'")

    _purge()
    yield
    _purge()


@pytest.fixture()
def sample_invoice():
    return invoice_parser.clean_invoice_record(
        {
            "发票号码": "TEST0001",
            "开票日期": "2026-11-01",
            "购买方名称": "测试科技有限公司",
            "销售方名称": "滴滴出行科技有限公司",
            "价税合计": "¥1,234.56",
            "发票类型": "增值税电子普通发票",
            "文件名": "test_001.pdf",
        }
    )
