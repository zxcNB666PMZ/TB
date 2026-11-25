# -*- coding: utf-8 -*-
"""
飞书机器人（服务器版 · 长连接 · PostgreSQL）

功能：飞书里发消息 → 共享 Agent 判断是否查库 → 查本机 PostgreSQL → 回复
模型：默认 DeepSeek（.env 用 LLM_PROVIDER 可切回智谱）
记忆：与网页「智能对话」共用 agent.py 和 chat_messages 表
      飞书用户绑定网页账号后，两边看到的是同一段对话
依赖：lark-oapi、openai（DeepSeek）、python-dotenv、psycopg2（复用 db.py）

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

import agent  # noqa: E402  （必须在 load_dotenv 之后导入）
import db  # noqa: E402
import llm  # noqa: E402

APP_ID = (os.getenv("FEISHU_APP_ID") or "").strip()
APP_SECRET = (os.getenv("FEISHU_APP_SECRET") or "").strip()
MODEL = llm.model_name()

if not APP_ID or not APP_SECRET:
    raise SystemExit("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
if not llm.is_configured():
    raise SystemExit("缺少大模型 API Key：请配置 DEEPSEEK_API_KEY（或 ZHIPU_API_KEY）")

lark_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

_seen_ids = set()
_seen_lock = threading.Lock()


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


def _sender_open_id(data):
    """取发送者 open_id（不同版本 SDK 字段位置略有差异，逐个兜底）"""
    try:
        sender = getattr(data.event, "sender", None)
        if sender is not None:
            sender_id = getattr(sender, "sender_id", None)
            if sender_id is not None:
                for attr in ("open_id", "user_id", "union_id"):
                    value = getattr(sender_id, attr, None)
                    if value:
                        return str(value)
    except Exception:
        pass
    return None


def _conversation_key(chat_id, open_id):
    """
    决定这段对话存在哪个"会话"下：
    - 飞书用户已绑定网页账号 → user:{用户名}，网页和飞书共享
    - 没绑定 → feishu:{chat_id}，独立线程
    """
    if open_id:
        try:
            username = db.find_username_by_open_id(open_id)
            if username:
                print(
                    f"[{time.strftime('%H:%M:%S')}] 已绑定账号：{open_id[:12]}… → {username}",
                    flush=True,
                )
                return f"user:{username}"
            print(f"[{time.strftime('%H:%M:%S')}] 未绑定的飞书用户：{open_id}", flush=True)
        except Exception as exc:
            print(f"查询绑定关系失败: {exc}", flush=True)
    return f"feishu:{chat_id}"


def _chat(chat_id, user_text, open_id=None):
    conversation_key = _conversation_key(chat_id, open_id)

    outcome = agent.run(
        conversation_key,
        user_text,
        channel="feishu",
        on_tool=lambda name, args, result: print(
            f"[{time.strftime('%H:%M:%S')}] 工具 {name} -> {str(result)[:80]}", flush=True
        ),
    )

    if outcome["error"]:
        print(f"模型错误：{outcome['error']}", flush=True)

    return outcome["answer"]


# 用户发这些词，机器人直接告知 open_id，方便绑定
_ID_COMMANDS = {
    "我的id", "我的ID", "我的 id", "我的open_id", "我的openid",
    "我的open id", "绑定", "绑定账号", "获取id", "getid",
}


def _maybe_id_command(user_text, open_id, chat_id):
    if not open_id:
        return None
    if (user_text or "").strip().lower() in {c.lower() for c in _ID_COMMANDS}:
        return (
            f"你的飞书 open_id 是：\n{open_id}\n\n"
            "把这个发给管理员，让他到网页「👥 用户与权限 → 绑定飞书账号」里绑定你的网页账号。\n"
            "绑定之后，你在网页和飞书里看到的就是同一段对话了。"
        )
    return None


def on_message(data: P2ImMessageReceiveV1) -> None:
    try:
        message = data.event.message
        chat_id = message.chat_id
        msg_id = message.message_id
        open_id = _sender_open_id(data)

        with _seen_lock:
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

        print(
            f"[{time.strftime('%H:%M:%S')}] 收到(chat_id={chat_id}, open_id={open_id}): {question}",
            flush=True,
        )

        # 发「我的ID」时直接回 open_id，不走大模型
        special = _maybe_id_command(question, open_id, chat_id)
        if special:
            _reply(chat_id, special)
            return

        try:
            answer = _chat(chat_id, question, open_id=open_id)
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
        print(f"大模型：{llm.describe()}", flush=True)
    except Exception as exc:
        print(f"启动自检失败：{exc}", flush=True)

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