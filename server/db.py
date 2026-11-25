# -*- coding: utf-8 -*-
"""
数据库访问层：自建 PostgreSQL（替代 Supabase）
所有 SQL 都在这里，app.py 只调用函数，方便以后换库。
"""

import os
import re
from contextlib import contextmanager
from datetime import date as _date_cls
from datetime import datetime

import bcrypt
import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor, execute_values

import invoice_parser

# 自己加载 .env：这样任何脚本 import db 都能直接连库，不必依赖调用方先 load_dotenv
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

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
    """转成数字，失败返回 None（兼容 "1,234.56" / "¥88.8" / "88.8元"）"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    text = (
        text.replace(",", "")
        .replace("，", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("元", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _date(value):
    """统一成 YYYY-MM-DD，失败返回 None（兼容 2026/11/01、2026年11月01日）"""
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, _date_cls):
        return value.isoformat()

    # 2026/11/01、2026.11.01、2026年11月01日 → 2026-11-01
    normalized = (
        text.replace("/", "-")
        .replace(".", "-")
        .replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .strip()
    )
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return _date_cls(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


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


def hash_password(password):
    """bcrypt 加盐哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _is_hash(value):
    return bool(value) and value.startswith(("$2a$", "$2b$", "$2y$"))


def set_password(username, password):
    """把用户密码改成 bcrypt 哈希存储"""
    hashed = hash_password(password)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET password = %s WHERE username = %s", (hashed, username))


def verify_login(username, password):
    """
    校验登录。返回 (user 或 None, 是否刚升级为哈希)
    兼容历史明文密码：校验通过后自动改写为 bcrypt 哈希。
    """
    user = find_user(username)
    if not user:
        return None, False

    stored = user.get("password") or ""
    if _is_hash(stored):
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            ok = False
        return (user if ok else None), False

    # 旧明文密码
    if stored == password:
        set_password(username, password)
        return user, True
    return None, False


def list_users():
    """列出所有用户（不含密码）"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT username, role FROM users ORDER BY username")
        return [dict(r) for r in cur.fetchall()]


def create_user(username, password, role):
    """
    新建用户。返回 (是否成功, 提示信息)
    用户名已存在时不覆盖，避免误改别人的密码。
    """
    username = (username or "").strip()
    if not username:
        return False, "用户名不能为空"
    if not password or len(password) < 6:
        return False, "密码至少 6 位"
    if find_user(username):
        return False, f"用户「{username}」已存在"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, hash_password(password), role),
        )
    return True, f"已创建用户「{username}」，角色：{role}"


def update_user_role(username, role):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET role = %s WHERE username = %s", (role, username))
        return cur.rowcount


def delete_user(username):
    """删除用户，返回是否删掉了"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username = %s", (username,))
        return cur.rowcount > 0


def count_by_role(role):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users WHERE role = %s", (role,))
        return cur.fetchone()[0]


def admin_count():
    return count_by_role("管理员")


# ==========================================
# 飞书身份绑定
# ==========================================
def find_user_by_feishu(open_id):
    """按飞书 open_id 找到对应的网页账号"""
    if not open_id:
        return None
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT username, role FROM users WHERE feishu_open_id = %s", (open_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def bind_feishu(username, open_id):
    """把飞书 open_id 绑到网页账号上；一个飞书号只能绑一个账号"""
    if not username or not open_id:
        return False, "用户名和 open_id 都不能为空"

    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT username FROM users WHERE feishu_open_id = %s", (open_id,))
        row = cur.fetchone()
        if row and row["username"] != username:
            return False, f"这个飞书号已经绑定到「{row['username']}」了，请先解绑"

        cur.execute(
            "UPDATE users SET feishu_open_id = %s WHERE username = %s",
            (open_id, username),
        )
        if cur.rowcount == 0:
            return False, f"用户「{username}」不存在"
    return True, f"已把飞书号绑定到「{username}」"


def unbind_feishu(username):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET feishu_open_id = NULL WHERE username = %s", (username,)
        )
        return cur.rowcount > 0


def list_feishu_bindings():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT username, role, feishu_open_id FROM users "
            "WHERE feishu_open_id IS NOT NULL ORDER BY username"
        )
        return [dict(r) for r in cur.fetchall()]


def find_username_by_open_id(open_id):
    u = find_user_by_feishu(open_id)
    return u["username"] if u else None


# ==========================================
# 对话记忆（网页和飞书共用）
# ==========================================
_chat_schema_ready = False


def ensure_chat_schema():
    """建对话表和飞书绑定字段（可重复执行）"""
    global _chat_schema_ready
    if _chat_schema_ready:
        return
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGSERIAL PRIMARY KEY,
                conversation_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                channel TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_key_id "
            "ON chat_messages (conversation_key, id)"
        )
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_open_id TEXT")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_feishu_open_id "
            "ON users (feishu_open_id) WHERE feishu_open_id IS NOT NULL"
        )
    _chat_schema_ready = True


def save_chat(conversation_key, role, content, channel=None):
    ensure_chat_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chat_messages (conversation_key, role, content, channel) "
            "VALUES (%s, %s, %s, %s)",
            (conversation_key, role, (content or "")[:8000], channel),
        )


def load_chat(conversation_key, limit=20):
    """取最近 limit 轮消息，转成模型能吃的格式（user/assistant 交替）"""
    ensure_chat_schema()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT role, content FROM ("
            "  SELECT id, role, content FROM chat_messages "
            "  WHERE conversation_key = %s AND role IN ('user','assistant') "
            "  ORDER BY id DESC LIMIT %s"
            ") t ORDER BY id",
            (conversation_key, limit),
        )
        return [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]


def chat_history(conversation_key, limit=50):
    """给界面展示用：带时间和渠道"""
    ensure_chat_schema()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT role, content, channel, created_at FROM ("
            "  SELECT id, role, content, channel, created_at FROM chat_messages "
            "  WHERE conversation_key = %s ORDER BY id DESC LIMIT %s"
            ") t ORDER BY id",
            (conversation_key, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def clear_chat(conversation_key):
    ensure_chat_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM chat_messages WHERE conversation_key = %s", (conversation_key,))
        return cur.rowcount


def chat_stats():
    """统计有多少个会话、多少条消息"""
    ensure_chat_schema()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT count(DISTINCT conversation_key) AS conversations, count(*) AS messages "
            "FROM chat_messages"
        )
        return dict(cur.fetchone())


# ==========================================
# 发票
# ==========================================
def query_invoices(name):
    """
    按供应商名模糊查询（购买方 + 销售方都查），并做**供应商别名归一化匹配**：
    搜"滴滴"也能命中"北京滴滴出行科技有限公司"、"滴滴出行科技有限公司"等不同写法。

    返回 (匹配行列表, 库内现有销售方名称样例)
    """
    keyword = (name or "").strip()
    pattern = "%" + _like_escape(keyword) + "%"

    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            'SELECT "价税合计", "购买方名称", "销售方名称" FROM invoices '
            'WHERE "购买方名称" ILIKE %s OR "销售方名称" ILIKE %s',
            (pattern, pattern),
        )
        rows = [dict(r) for r in cur.fetchall()]

        # 归一化别名匹配：把库里所有销售方名称取出来，找出与关键词"同一家公司"的
        if keyword:
            cur.execute(
                'SELECT DISTINCT "销售方名称" AS s FROM invoices '
                'WHERE "销售方名称" IS NOT NULL AND trim("销售方名称") <> \'\''
            )
            existing_names = [r["s"] for r in cur.fetchall()]
            aliases = [n for n in existing_names if invoice_parser.same_supplier(keyword, n)]

            found = {(r.get("销售方名称"), r.get("购买方名称"), str(r.get("价税合计"))) for r in rows}
            extra = [n for n in aliases if not any(r.get("销售方名称") == n for r in rows)]
            if extra:
                cur.execute(
                    'SELECT "价税合计", "购买方名称", "销售方名称" FROM invoices '
                    'WHERE "销售方名称" = ANY(%s)',
                    (extra,),
                )
                for r in cur.fetchall():
                    item = dict(r)
                    key = (item.get("销售方名称"), item.get("购买方名称"), str(item.get("价税合计")))
                    if key not in found:
                        found.add(key)
                        rows.append(item)

        samples = []
        if not rows:
            cur.execute(
                'SELECT DISTINCT "销售方名称" AS s FROM invoices '
                'WHERE "销售方名称" IS NOT NULL ORDER BY s LIMIT 20'
            )
            samples = [r["s"] for r in cur.fetchall()]

        return rows, samples


def quality_summary():
    """数据质量概览：总数、缺销售方名称的条数与金额"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
              count(*) AS total,
              count(*) FILTER (
                WHERE "销售方名称" IS NULL OR trim("销售方名称") = ''
              ) AS no_seller,
              coalesce(sum("价税合计") FILTER (
                WHERE "销售方名称" IS NULL OR trim("销售方名称") = ''
              ), 0) AS no_seller_amount,
              coalesce(sum("价税合计"), 0) AS total_amount,
              count(*) FILTER (
                WHERE "价税合计" IS NULL OR "价税合计" <= 0
              ) AS bad_amount
            FROM invoices
            """
        )
        return dict(cur.fetchone())


def all_invoices():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM invoices ORDER BY "开票日期" DESC NULLS LAST, id DESC')
        return [dict(r) for r in cur.fetchall()]


INVOICE_COLS = ["发票号码", "开票日期", "购买方名称", "销售方名称", "价税合计", "发票类型", "文件名"]


def upsert_invoices(records):
    """
    批量写入发票，按发票号码去重（有则更新，无则插入）。
    没有发票号码的记录会被跳过（无法去重，写进去只会产生垃圾数据）。
    返回实际写入条数。
    """
    if not records:
        return 0

    # 同一批次里发票号码可能重复，先合并，避免 ON CONFLICT 报错；顺便丢掉无号码的
    seen = {}
    for r in records:
        key = str(r.get("发票号码") or "").strip()
        if not key:
            continue
        seen[key] = r
    if not seen:
        return 0
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
