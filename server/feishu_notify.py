# -*- coding: utf-8 -*-
"""用飞书应用机器人主动发消息（不需要 Webhook）"""

import json
import os

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

APP_ID = (os.getenv("FEISHU_APP_ID") or "").strip()
APP_SECRET = (os.getenv("FEISHU_APP_SECRET") or "").strip()


def get_token():
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {data}")
    return data["tenant_access_token"]


def send_text(chat_id, text):
    """往指定会话（群或私聊）发一条文本消息"""
    if not APP_ID or not APP_SECRET:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
    token = get_token()
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json; charset=utf-8",
        },
        json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        timeout=15,
    )
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:200]
    return resp.status_code, body


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python feishu_notify.py <chat_id> <消息内容>")
        raise SystemExit(1)
    code, body = send_text(sys.argv[1], sys.argv[2])
    print(code, body)
