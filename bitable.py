# -*- coding: utf-8 -*-
"""
飞书多维表格（Bitable）对接：把发票台账同步进多维表格，或者从多维表格拉数据回数据库。

需要的配置（写在服务器 /opt/finance-ai/.env）：
    FEISHU_BITABLE_APP_TOKEN=多维表格的 app_token
    FEISHU_BITABLE_TABLE_ID=数据表 id（tbl 开头）

飞书那边还要做两件事（只有你能操作）：
    1. 开放平台 → 应用 → 权限管理，添加：bitable:app（查看、评论、编辑和管理多维表格）
    2. 打开多维表格 → 右上角「...」→ 添加文档应用 → 选中你的机器人应用，权限选「可编辑」
       否则接口会报 permission denied

对应飞书接口：
    获取 token:      POST /open-apis/auth/v3/tenant_access_token/internal
    列字段:          GET  /open-apis/bitable/v1/apps/{app}/tables/{tbl}/fields
    批量新增记录:    POST /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/batch_create
    列出记录:        GET  /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records
"""

import json
import os
import time

import requests

BASE = "https://open.feishu.cn/open-apis"

# 字段顺序：数据库字段 → 多维表格列名
FIELD_MAP = [
    ("发票号码", "发票号码", 1),
    ("开票日期", "开票日期", 5),         # 5 = 日期
    ("购买方名称", "购买方名称", 1),
    ("销售方名称", "销售方名称", 1),
    ("价税合计", "价税合计", 2),          # 2 = 数字
    ("发票类型", "发票类型", 1),
    ("文件名", "文件名", 1),
]


class BitableError(RuntimeError):
    pass


def app_token():
    return (os.getenv("FEISHU_BITABLE_APP_TOKEN") or "").strip()


def table_id():
    return (os.getenv("FEISHU_BITABLE_TABLE_ID") or "").strip()


def is_configured():
    return bool(app_token() and table_id() and os.getenv("FEISHU_APP_ID") and os.getenv("FEISHU_APP_SECRET"))


def describe():
    if not app_token() or not table_id():
        return "未配置（.env 里缺 FEISHU_BITABLE_APP_TOKEN / FEISHU_BITABLE_TABLE_ID）"
    return f"app_token={app_token()[:8]}… table={table_id()}"


_token_cache = {"value": None, "expire_at": 0}


def tenant_token(force=False):
    """获取 tenant_access_token（有效期 2 小时，本地缓存）"""
    if not force and _token_cache["value"] and time.time() < _token_cache["expire_at"]:
        return _token_cache["value"]

    app_id = (os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (os.getenv("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise BitableError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")

    resp = requests.post(
        f"{BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise BitableError(f"取 token 失败：{data.get('msg')}（code={data.get('code')}）")

    _token_cache["value"] = data["tenant_access_token"]
    _token_cache["expire_at"] = time.time() + int(data.get("expire", 7200)) - 300
    return _token_cache["value"]


def _headers():
    return {
        "Authorization": f"Bearer {tenant_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _check(data, action):
    if data.get("code") != 0:
        code = data.get("code")
        msg = data.get("msg") or data.get("error") or ""
        hint = ""
        if code in (91403, 99991672, 1254302) or "permission" in str(msg).lower():
            hint = "（检查：机器人是否被加进多维表格的协作者、是否有 bitable:app 权限）"
        if code == 1254040 or "not found" in str(msg).lower():
            hint = "（检查：app_token 和 table_id 是否填对，表格是否被删除）"
        raise BitableError(f"{action}失败：{msg}（code={code}）{hint}")
    return data.get("data", {})


# ==========================================
# 读
# ==========================================
def list_fields():
    url = f"{BASE}/bitable/v1/apps/{app_token()}/tables/{table_id()}/fields"
    resp = requests.get(url, headers=_headers(), params={"page_size": 100}, timeout=20)
    data = _check(resp.json(), "查询字段")
    return data.get("items", [])


def list_records(page_size=500, max_pages=20):
    """列出所有记录（自动翻页）"""
    url = f"{BASE}/bitable/v1/apps/{app_token()}/tables/{table_id()}/records"
    records = []
    page_token = None
    for _ in range(max_pages):
        params = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        data = _check(resp.json(), "读取记录")
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return records


# ==========================================
# 写
# ==========================================
def _date_to_ms(value):
    """
    多维表格的日期字段要毫秒时间戳（int），不接受 "2026-11-20" 字符串。
    按北京时间换算，保证表里显示的是当天。
    """
    from datetime import datetime, timedelta, timezone

    text = str(value).strip()[:10]
    try:
        dt = datetime.strptime(text, "%Y-%m-%d").replace(
            tzinfo=timezone(timedelta(hours=8))
        )
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _to_bitable_fields(invoice):
    """数据库一行 → 多维表格 fields"""
    fields = {}
    for db_col, bt_col, _kind in FIELD_MAP:
        value = invoice.get(db_col)
        if value is None or value == "":
            continue
        if db_col == "价税合计":
            try:
                fields[bt_col] = float(value)
            except (TypeError, ValueError):
                continue
        elif db_col == "开票日期":
            ms = _date_to_ms(value)
            if ms is not None:
                fields[bt_col] = ms
        else:
            fields[bt_col] = str(value)
    return fields


def push_invoices(invoices, batch_size=500, progress=None):
    """
    把发票写入多维表格。返回 (成功条数, 失败说明列表)
    注意：这里是"新增"，不做去重；配合 pull 使用时要自己控制重复。
    """
    if not is_configured():
        raise BitableError("多维表格未配置，请在 .env 填 FEISHU_BITABLE_APP_TOKEN 和 FEISHU_BITABLE_TABLE_ID")

    url = f"{BASE}/bitable/v1/apps/{app_token()}/tables/{table_id()}/records/batch_create"
    created = 0
    errors = []

    for start in range(0, len(invoices), batch_size):
        chunk = invoices[start:start + batch_size]
        payload = {"records": [{"fields": _to_bitable_fields(inv)} for inv in chunk]}
        resp = requests.post(url, headers=_headers(), json=payload, timeout=60)
        try:
            data = _check(resp.json(), "写入记录")
            created += len(data.get("records", chunk))
        except BitableError as exc:
            errors.append(str(exc))
            break
        if progress:
            progress(min(start + batch_size, len(invoices)), len(invoices))

    return created, errors


def sync_all(only_missing=True):
    """
    把数据库里的发票同步到多维表格。
    only_missing=True 时，先读表格里已有的发票号码，只推不存在的，避免重复。
    返回 (推送条数, 跳过条数, 失败说明)
    """
    import db

    invoices = db.all_invoices()
    if not invoices:
        return 0, 0, ["数据库里没有发票"]

    existing = set()
    if only_missing:
        try:
            for rec in list_records():
                number = (rec.get("fields") or {}).get("发票号码")
                if number:
                    existing.add(str(number).strip())
        except BitableError as exc:
            return 0, 0, [f"读取表格已有记录失败：{exc}"]

    todo = [i for i in invoices if str(i.get("发票号码") or "").strip() not in existing]
    skipped = len(invoices) - len(todo)
    if not todo:
        return 0, skipped, []

    created, errors = push_invoices(todo)
    return created, skipped, errors


# ==========================================
# 自检
# ==========================================
def self_check():
    """逐项检查配置与连通性，返回 [(项目, 是否通过, 说明)]"""
    results = []

    results.append(("应用凭证", bool(os.getenv("FEISHU_APP_ID") and os.getenv("FEISHU_APP_SECRET")),
                    "FEISHU_APP_ID / FEISHU_APP_SECRET"))

    ok = bool(app_token() and table_id())
    results.append(("表格配置", ok, describe()))

    if not ok:
        return results

    try:
        tenant_token(force=True)
        results.append(("获取 access_token", True, "成功"))
    except Exception as exc:
        results.append(("获取 access_token", False, str(exc)[:120]))
        return results

    try:
        fields = list_fields()
        names = [f.get("field_name") for f in fields]
        results.append(("读取字段", True, f"{len(names)} 个字段：{', '.join(names[:8])}"))
    except Exception as exc:
        results.append(("读取字段", False, str(exc)[:160]))
        return results

    try:
        recs = list_records(page_size=10, max_pages=1)
        results.append(("读取记录", True, f"表里现有 {len(recs)} 条（只取首页样例）"))
    except Exception as exc:
        results.append(("读取记录", False, str(exc)[:160]))

    return results