# -*- coding: utf-8 -*-
"""
把 Supabase 云端数据迁移到自建 PostgreSQL。

原理：Supabase 的 *.supabase.co 被墙，但连接池域名 *.pooler.supabase.com 是通的，
      所以这里用「数据库直连（连接池）」的方式把三张表整表复制过来。

在服务器上运行：
    cd /opt/finance-ai
    venv/bin/python migrate_from_supabase.py
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor, execute_values

load_dotenv()

SRC = {
    "host": os.getenv("SUPABASE_DB_HOST", "").strip(),
    "port": int(os.getenv("SUPABASE_DB_PORT", "5432") or 5432),
    "dbname": os.getenv("SUPABASE_DB_NAME", "postgres").strip(),
    "user": os.getenv("SUPABASE_DB_USER", "").strip(),
    "password": os.getenv("SUPABASE_DB_PASSWORD", ""),
    "sslmode": "require",
    "connect_timeout": 20,
}

DST = {
    "host": os.getenv("PGHOST", "127.0.0.1"),
    "port": int(os.getenv("PGPORT", "5432") or 5432),
    "dbname": os.getenv("PGDATABASE", "finance"),
    "user": os.getenv("PGUSER", "finance"),
    "password": os.getenv("PGPASSWORD", ""),
    "connect_timeout": 20,
}

TABLES = ["users", "invoices", "transactions"]


def dst_columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


def copy_table(src, dst, table):
    """整表复制：只复制两边都存在的列，id 交给目标库自增"""
    with src.cursor(cursor_factory=RealDictCursor) as scur:
        try:
            scur.execute('SELECT * FROM public."%s"' % table)
        except psycopg2.Error as e:
            dst.rollback()
            print(f"[{table}] 读取源表失败（可能表不存在）: {e}")
            return 0
        rows = [dict(r) for r in scur.fetchall()]

    if not rows:
        print(f"[{table}] 源表 0 行，跳过")
        return 0

    dcols = dst_columns(dst, table)
    cols = [c for c in rows[0].keys() if c in dcols and c != "id"]
    if not cols:
        print(f"[{table}] 没有可迁移的公共列，跳过。源列 = {list(rows[0].keys())}, 目标列 = {sorted(dcols)}")
        return 0

    col_sql = ", ".join('"%s"' % c for c in cols)
    values = [tuple(r.get(c) for c in cols) for r in rows]
    sql = 'INSERT INTO public."%s" (%s) VALUES %%s ON CONFLICT DO NOTHING' % (table, col_sql)

    with dst.cursor() as dcur:
        execute_values(dcur, sql, values, page_size=200)
    dst.commit()

    print(f"[{table}] ✅ 写入 {len(values)} 行 | 列: {cols}")
    return len(values)


def main():
    missing = [k for k in ("host", "user", "password") if not SRC[k]]
    if missing:
        print("❌ .env 里缺少 Supabase 数据库连接信息，缺:", missing)
        print("   到 Supabase 控制台 → Settings → Database → Connection string")
        print("   选【Session pooler】，把 host / user / password 分别填到：")
        print("   SUPABASE_DB_HOST / SUPABASE_DB_USER / SUPABASE_DB_PASSWORD")
        print("   （注意：是数据库密码，不是 anon key）")
        sys.exit(1)

    print(f"→ 连接 Supabase 连接池: {SRC['host']}:{SRC['port']}")
    try:
        src = psycopg2.connect(**SRC)
    except Exception as e:
        print(f"❌ 连不上 Supabase 连接池: {e}")
        print("   检查 host 是否形如 aws-0-xxx.pooler.supabase.com，user 是否形如 postgres.项目ref")
        sys.exit(1)
    print("✅ 源库连接成功")

    print(f"→ 连接本地 PostgreSQL: {DST['host']}:{DST['port']}/{DST['dbname']}")
    try:
        dst = psycopg2.connect(**DST)
    except Exception as e:
        print(f"❌ 连不上本地数据库: {e}")
        print("   检查 PostgreSQL 是否已启动、schema.sql 是否已执行、.env 的 PG* 是否正确")
        sys.exit(1)
    print("✅ 目标库连接成功\n")

    total = 0
    for table in TABLES:
        try:
            total += copy_table(src, dst, table)
        except Exception as e:
            dst.rollback()
            print(f"[{table}] ❌ 迁移失败: {e}")

    src.close()
    dst.close()
    print(f"\n🎉 迁移结束，共写入 {total} 行")
    print("说明：发票号码重复的记录会被跳过（ON CONFLICT DO NOTHING）")


if __name__ == "__main__":
    main()
