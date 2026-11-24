# -*- coding: utf-8 -*-
"""
财务数据 API（给 Streamlit Cloud 等外部客户端用）

设计原则：
  - 数据库只监听本机 127.0.0.1，公网只暴露这个 API 的 8502 端口
  - 所有请求必须带 X-API-Key 头
  - 只提供必要的读写接口

启动：systemctl start finance-api
自测：curl -H "X-API-Key: 你的key" http://127.0.0.1:8502/health
"""

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

from fastapi import Depends, FastAPI, Header, HTTPException, Query  # noqa: E402

import db  # noqa: E402

API_KEY = (os.getenv("API_KEY") or "").strip()
if not API_KEY:
    raise SystemExit("缺少 API_KEY，请先写入 .env")

app = FastAPI(title="Finance Data API", version="1.0", docs_url=None, redoc_url=None)


def auth(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    return True


@app.get("/health")
def health(_: bool = Depends(auth)):
    try:
        rows = db.all_invoices()
        return {"ok": True, "invoices": len(rows)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/invoices")
def invoices(supplier: str = Query(default=""), _: bool = Depends(auth)):
    """按公司名查询（购买方/销售方模糊匹配）"""
    supplier = supplier.strip()
    if not supplier:
        raise HTTPException(status_code=400, detail="supplier required")
    try:
        rows, samples = db.query_invoices(supplier)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    total = sum(float(r.get("价税合计") or 0) for r in rows)
    return {"count": len(rows), "total": round(total, 2), "rows": rows, "samples": samples}


@app.get("/invoices/all")
def all_invoices(limit: int = Query(default=500, ge=1, le=5000), _: bool = Depends(auth)):
    try:
        rows = db.all_invoices()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    rows = rows[:limit]
    total = sum(float(r.get("价税合计") or 0) for r in rows)
    return {"count": len(rows), "total": round(total, 2), "rows": rows}


@app.post("/login")
def login(payload: dict, _: bool = Depends(auth)):
    """校验账号密码（供云端登录）"""
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username/password required")
    try:
        user = db.find_user(username)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not user or str(user.get("password")) != str(password):
        return {"ok": False}
    return {"ok": True, "username": user.get("username"), "role": user.get("role")}


@app.post("/invoices/upsert")
def upsert(payload: dict, _: bool = Depends(auth)):
    """批量写入/更新发票（按发票号码去重）"""
    records = payload.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400, detail="records required")
    try:
        n = db.upsert_invoices(records)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "upserted": n}


@app.post("/transactions/insert")
def insert_tx(payload: dict, _: bool = Depends(auth)):
    records = payload.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400, detail="records required")
    try:
        n = db.insert_transactions(records)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "inserted": n}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8502, log_level="info")
