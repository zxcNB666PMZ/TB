# -*- coding: utf-8 -*-
"""
数据库访问层：自建 PostgreSQL（替代 Supabase）
所有 SQL 都在这里，app.py 只调用函数，方便以后换库。
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor, execute_values

_pool = None


def _conn_kwargs():
    return {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "5432") or 5432),
        "dbname": os.getenv("PGDATABASE", "finance"),
        "user": os.getenv("PGUSER", "finance"),
        "password": os.getenv("PGPASSWORD", ""),
        "connect_timeout": 10,
    }


def init_pool(minconn=1, maxconn=10):
    """初始化连接池（Streamlit 是多线程的，必须用池）"""
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(minconn, maxconn, **_conn_kwargs())
    return _pool


@contextmanager
def get_conn():
    pool = init_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _num(value):
    """转成数字，失败返回 None"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value):
    """只保留 YYYY-MM-DD，失败返回 None"""
    if not value:
        return None
    text = str(value).strip()[:10]
    return text or None


def _like_escape(text):
    """转义 LIKE 里的通配符，避免用户输入的 % 和 _ 改变匹配范围"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ==========================================
# 用户
# ==========================================
def find_user(username):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT username, password, role FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ==========================================
# 发票
# ==========================================
def query_invoices(name):
    """
    按供应商名模糊查询（购买方 + 销售方都查）。
    返回 (匹配行列表, 库内现有销售方名称样例)
    """
    pattern = "%" + _like_escape(name) + "%"
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            'SELECT "价税合计", "购买方名称", "销售方名称" FROM invoices '
            'WHERE "购买方名称" ILIKE %s OR "销售方名称" ILIKE %s',
            (pattern, pattern),
        )
        rows = [dict(r) for r in cur.fetchall()]

        samples = []
        if not rows:
            cur.execute(
                'SELECT DISTINCT "销售方名称" AS s FROM invoices '
                'WHERE "销售方名称" IS NOT NULL ORDER BY s LIMIT 20'
            )
            samples = [r["s"] for r in cur.fetchall()]

        return rows, samples


def all_invoices():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM invoices ORDER BY "开票日期" DESC NULLS LAST, id DESC')
        return [dict(r) for r in cur.fetchall()]


INVOICE_COLS = ["发票号码", "开票日期", "购买方名称", "销售方名称", "价税合计", "发票类型", "文件名"]


def upsert_invoices(records):
    """批量写入发票，按发票号码去重（有则更新，无则插入）"""
    if not records:
        return 0

    # 同一批次里发票号码可能重复，先合并，避免 ON CONFLICT 报错
    seen = {}
    for idx, r in enumerate(records):
        key = (r.get("发票号码") or "").strip() or f"__no_num_{idx}"
        seen[key] = r
    records = list(seen.values())

    values = []
    for r in records:
        values.append((
            r.get("发票号码"),
            _date(r.get("开票日期")),
            r.get("购买方名称"),
            r.get("销售方名称"),
            _num(r.get("价税合计")),
            r.get("发票类型"),
            r.get("文件名"),
        ))

    sql = (
        'INSERT INTO invoices ("发票号码","开票日期","购买方名称","销售方名称","价税合计","发票类型","文件名") '
        "VALUES %s "
        'ON CONFLICT ("发票号码") DO UPDATE SET '
        '"开票日期" = EXCLUDED."开票日期", '
        '"购买方名称" = EXCLUDED."购买方名称", '
        '"销售方名称" = EXCLUDED."销售方名称", '
        '"价税合计" = EXCLUDED."价税合计", '
        '"发票类型" = EXCLUDED."发票类型", '
        '"文件名" = EXCLUDED."文件名"'
    )

    with get_conn() as conn, conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=100)
        return len(values)


def insert_transactions(records):
    """批量写入银行流水"""
    if not records:
        return 0
    values = [(r.get("交易备注"), _num(r.get("金额")), r.get("AI分类")) for r in records]
    sql = 'INSERT INTO transactions ("交易备注","金额","AI分类") VALUES %s'
    with get_conn() as conn, conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=200)
        return len(values)


# ==========================================
# 健康检查
# ==========================================
def ping():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        return cur.fetchone() is not None
