# -*- coding: utf-8 -*-
"""
飞书机器人（服务器版 · 长连接 · PostgreSQL）

功能：飞书里发消息 → 智谱 GLM 判断是否需要查库 → 查本机 PostgreSQL → 回复
依赖：lark-oapi、zhipuai、python-dotenv、psycopg2（复用 db.py）

启动：systemctl start finance-bot
"""

import json
import os
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

import db  # noqa: E402  （必须在 load_dotenv 之后导入）

APP_ID = (os.getenv("FEISHU_APP_ID") or "").strip()
APP_SECRET = (os.getenv("FEISHU_APP_SECRET") or "").strip()
ZHIPU_API_KEY = (os.getenv("ZHIPU_API_KEY") or "").strip()
MODEL = os.getenv("ZHIPU_MODEL", "glm-4-flash")

if not APP_ID or not APP_SECRET:
    raise SystemExit("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
if not ZHIPU_API_KEY:
    raise SystemExit("缺少 ZHIPU_API_KEY")

SYSTEM_PROMPT = (
    "你是公司的 AI 财务助手，在飞书上和同事对话。当前系统时区为北京时间。"
    "规则："
    "1) 用户问某个公司/供应商的发票金额时，调用 query_invoice_db；"
    "用户问“一共有多少张发票/总共花了多少钱/按公司汇总/哪家花得最多”这类总体统计时，调用 invoice_overview。"
    "2) 绝不能凭空编造数字，也不能说“我无法访问数据库”。"
    "3) 工具返回没找到时，可换更短的关键词（如把“北京滴滴出行科技有限公司”改成“滴滴”）再查一次；"
    "仍然没有就如实告知，并提示库里现有公司名。"
    "4) 回答口语化、适合手机阅读，金额保留两位小数，不要罗列无关字段。"
    "5) 无法完成的事（如看具体发票图片、修改数据）要直说。"
    "6) 不要把“发票”“总额”这类通用词当公司名去查——那是 invoice_overview 的活。"
)

lark_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
zhipu = ZhipuAI(api_key=ZHIPU_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_invoice_db",
            "description": "按公司/供应商名称查询发票：统计张数与价税合计金额（购买方和销售方都会匹配）。",
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
    },
    {
        "type": "function",
        "function": {
            "name": "invoice_overview",
            "description": "发票总览统计：库里一共有多少张发票、总金额多少、按销售方分组的金额与张数。适用于“总共多少”“哪家最多”“汇总一下”这类问题。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def invoice_overview():
    """总览：总张数、总金额、按销售方分组"""
    try:
        rows = db.all_invoices()
    except Exception as exc:
        return f"查询数据库出错：{exc}"

    if not rows:
        return "数据库里目前还没有任何发票记录。"

    total = 0.0
    detail = {}
    for row in rows:
        amount = float(row.get("价税合计") or 0)
        total += amount
        key = row.get("销售方名称") or "（未识别销售方）"
        item = detail.setdefault(key, {"n": 0, "amt": 0.0})
        item["n"] += 1
        item["amt"] += amount

    lines = "\n".join(
        f"  {k}：{v['n']} 张，{v['amt']:.2f} 元"
        for k, v in sorted(detail.items(), key=lambda x: -x[1]["amt"])
    )
    return (
        f"数据库共有 {len(rows)} 张发票，价税合计 {total:.2f} 元。\n"
        f"按销售方分组：\n{lines}"
    )


def query_invoice_db(supplier_name):
    name = (supplier_name or "").strip()
    if not name:
        return "请提供要查询的公司或供应商名称。"
    try:
        rows, samples = db.query_invoices(name)
    except Exception as exc:
        return f"查询数据库出错：{exc}"

    if not rows:
        hint = "、".join(samples) if samples else "（库是空的）"
        return (
            f"没有找到与“{name}”相关的发票。数据库里现有的销售方有：{hint}。"
            "可以换个关键词，或向用户确认公司全称。"
        )

    total = 0.0
    detail = {}
    for row in rows:
        amount = float(row.get("价税合计") or 0)
        total += amount
        key = row.get("销售方名称") or "（未识别）"
        detail[key] = detail.get(key, 0.0) + amount

    lines = "\n".join(
        f"  {k}：{v:.2f} 元" for k, v in sorted(detail.items(), key=lambda x: -x[1])
    )
    return (
        f"找到与“{name}”相关的发票共 {len(rows)} 张，价税合计 {total:.2f} 元。\n"
        f"按销售方拆分：\n{lines}"
    )


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
        print(f"回复失败 code={resp.code} msg={resp.msg}", flush=True)


def _extract_text(message):
    try:
        content = json.loads(message.content or "{}")
    except Exception:
        return ""
    text = (content.get("text") or "").strip()
    if "@_user_" in text:
        text = " ".join(w for w in text.split() if not w.startswith("@_user_"))
    return text.strip()


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
                elif name == "invoice_overview":
                    result = invoice_overview()
                else:
                    result = f"未知工具：{name}"
                print(f"[{time.strftime('%H:%M:%S')}] 工具 {name} -> {result[:80]}", flush=True)
                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": str(result)}
                )
            continue

        answer = (msg.content or "").strip() or "我没查到明确结果，换个说法再问一次？"
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
            _reply(chat_id, "我目前只看得懂文字消息哦")
            return

        question = _extract_text(message)
        if not question:
            return

        print(f"[{time.strftime('%H:%M:%S')}] 收到(chat_id={chat_id}): {question}", flush=True)
        try:
            answer = _chat(chat_id, question)
        except Exception as exc:
            print(f"处理失败: {exc}", flush=True)
            answer = "抱歉，我这边出了点问题，稍后再发一次？"

        print(f"[{time.strftime('%H:%M:%S')}] 回复: {answer[:80]}", flush=True)
        _reply(chat_id, answer)

    except Exception as exc:
        print(f"消息事件异常: {exc}", flush=True)


def main():
    try:
        print(f"发票库：{len(db.all_invoices())} 条记录", flush=True)
    except Exception as exc:
        print(f"读取发票库失败：{exc}", flush=True)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    ws = lark.ws.Client(
        APP_ID, APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO
    )
    print("飞书机器人（服务器版）已启动，等待消息……", flush=True)
    ws.start()


if __name__ == "__main__":
    main()
