# -*- coding: utf-8 -*-
"""
飞书机器人 v2 —— 带发票查询能力（本地 SQLite）

流程：飞书消息 → 智谱 GLM 判断要不要查库 → 查 finance.db → 把结果喂回模型 → 回复

运行：
    python bot_server.py

.env 需要：
    FEISHU_APP_ID / FEISHU_APP_SECRET / ZHIPU_API_KEY
可选：
    INVOICE_DB=E:\\TB\\finance.db     （默认就是这个路径）
    ZHIPU_MODEL=glm-4-flash
"""

import json
import os
import sqlite3
import threading
import time

import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)
from zhipuai import ZhipuAI

load_dotenv()

APP_ID = (os.getenv("FEISHU_APP_ID") or "").strip()
APP_SECRET = (os.getenv("FEISHU_APP_SECRET") or "").strip()
ZHIPU_API_KEY = (os.getenv("ZHIPU_API_KEY") or "").strip()
MODEL = os.getenv("ZHIPU_MODEL", "glm-4-flash")
DB_PATH = os.getenv("INVOICE_DB", r"E:\TB\finance.db")

if not APP_ID or not APP_SECRET:
    raise SystemExit("❌ .env 里缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
if not ZHIPU_API_KEY:
    raise SystemExit("❌ .env 里缺少 ZHIPU_API_KEY")
if not os.path.exists(DB_PATH):
    raise SystemExit(f"❌ 找不到发票数据库：{DB_PATH}")

SYSTEM_PROMPT = (
    "你是公司的 AI 财务助手，在飞书上和同事对话。"
    "规则："
    "1) 用户问发票、金额、花了多少、报销、某个公司开销时，必须调用 query_invoice_db 工具查库，"
    "绝不允许凭空回答或说“我查不到数据库”。"
    "2) 工具返回没找到时，可以换个更短的关键词再查一次（比如把“北京滴滴出行科技有限公司”改成“滴滴”）；"
    "仍然没有就如实告诉用户。"
    "3) 回答简洁口语化，适合手机阅读，金额保留两位小数，不要罗列无关细节。"
)

lark_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
zhipu = ZhipuAI(api_key=ZHIPU_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_invoice_db",
            "description": "查询发票数据库：按公司/供应商名称统计发票张数与价税合计金额（购买方和销售方都会匹配）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_name": {
                        "type": "string",
                        "description": "公司或供应商名称关键词，如 滴滴、易行",
                    }
                },
                "required": ["supplier_name"],
            },
        },
    }
]


# ---------- 数据库查询 ----------
def query_invoice_db(supplier_name):
    """查发票：购买方或销售方模糊匹配，返回张数、总额、按销售方拆分"""
    name = (supplier_name or "").strip()
    if not name:
        return "请提供要查询的公司或供应商名称。"

    keyword = name.replace("%", "").replace("_", "")
    like = "%" + keyword + "%"

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            'SELECT "销售方名称", "价税合计" FROM invoices '
            'WHERE "销售方名称" LIKE ? OR "购买方名称" LIKE ?',
            (like, like),
        ).fetchall()

        if not rows:
            names = [
                r[0]
                for r in conn.execute(
                    'SELECT DISTINCT "销售方名称" FROM invoices '
                    'WHERE "销售方名称" IS NOT NULL'
                ).fetchall()
            ]
            hint = "、".join(names) if names else "（库是空的）"
            return (
                f"没有找到与“{keyword}”相关的发票。"
                f"数据库里现有的销售方有：{hint}。"
                f"可以换个关键词，或向用户确认公司全称。"
            )

        total = 0.0
        detail = {}
        for seller, amount in rows:
            value = float(amount) if amount is not None else 0.0
            total += value
            key = seller or "（未识别）"
            detail[key] = detail.get(key, 0.0) + value

        lines = "\n".join(
            f"  {k}：{v:.2f} 元" for k, v in sorted(detail.items(), key=lambda x: -x[1])
        )
        return (
            f"找到与“{keyword}”相关的发票共 {len(rows)} 张，价税合计 {total:.2f} 元。\n"
            f"按销售方拆分：\n{lines}"
        )
    finally:
        conn.close()


# ---------- 会话记忆 ----------
_history = {}
_history_lock = threading.Lock()
MAX_MESSAGES = 12
_seen_ids = set()


def _remember(chat_id, role, content):
    with _history_lock:
        msgs = _history.setdefault(chat_id, [])
        msgs.append({"role": role, "content": content})
        del msgs[:-MAX_MESSAGES]


def _history_of(chat_id):
    with _history_lock:
        return list(_history.get(chat_id, []))


# ---------- 回复飞书 ----------
def _reply(chat_id, text):
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = lark_client.im.v1.message.create(request)
    if not resp.success():
        print(f"❌ 回复失败 code={resp.code} msg={resp.msg}")


def _extract_text(message):
    try:
        content = json.loads(message.content or "{}")
    except Exception:
        return ""
    text = (content.get("text") or "").strip()
    if "@_user_" in text:
        text = " ".join(w for w in text.split() if not w.startswith("@_user_"))
    return text.strip()


# ---------- 对话主流程：带工具调用 ----------
def _chat(chat_id, user_text):
    _remember(chat_id, "user", user_text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _history_of(chat_id)

    for _ in range(3):
        resp = zhipu.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
        )
        msg = resp.choices[0].message

        if getattr(msg, "tool_calls", None):
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except Exception:
                    args = {}

                if name == "query_invoice_db":
                    result = query_invoice_db(args.get("supplier_name", ""))
                else:
                    result = f"未知工具：{name}"

                print(f"[{time.strftime('%H:%M:%S')}] 工具 {name} -> {result[:80]}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    }
                )
            continue

        answer = (msg.content or "").strip() or "我没查到明确结果，可以换个说法再问一次吗？"
        _remember(chat_id, "assistant", answer)
        return answer

    return "这个问题我查了几轮还没查清，换个更具体的公司名再问我一次？"


def on_message(data: P2ImMessageReceiveV1) -> None:
    try:
        message = data.event.message
        chat_id = message.chat_id
        msg_id = message.message_id

        if msg_id in _seen_ids:
            return
        _seen_ids.add(msg_id)
        if len(_seen_ids) > 2000:
            _seen_ids.clear()

        if message.message_type != "text":
            _reply(chat_id, "我目前只看得懂文字消息哦 🙂")
            return

        question = _extract_text(message)
        if not question:
            return

        print(f"[{time.strftime('%H:%M:%S')}] 收到: {question}")

        try:
            answer = _chat(chat_id, question)
        except Exception as e:
            print("❌ 处理失败:", e)
            answer = "抱歉，我这边出了点问题，稍后再发一次？"

        print(f"[{time.strftime('%H:%M:%S')}] 回复: {answer[:80]}")
        _reply(chat_id, answer)

    except Exception as e:
        print("❌ 消息事件异常:", e)


def main():
    # 启动时打印一下库的情况，方便确认
    try:
        conn = sqlite3.connect(DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        total = conn.execute('SELECT SUM("价税合计") FROM invoices').fetchone()[0] or 0
        conn.close()
        print(f"📚 发票库：{DB_PATH}")
        print(f"   共 {n} 张发票，价税合计 {float(total):.2f} 元")
    except Exception as e:
        print("⚠️ 读取发票库失败:", e)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    ws = lark.ws.Client(
        APP_ID, APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO
    )
    print("🚀 飞书机器人 v2 已启动（可查发票）")
    print("   试试在飞书里问：帮我查一下滴滴的发票总额")
    ws.start()


if __name__ == "__main__":
    main()
