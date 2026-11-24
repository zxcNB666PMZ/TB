#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财务系统健康检查：网页 / 飞书机器人 / 数据库；异常时推飞书

告警通道（按优先级）：
  1) ALERT_CHAT_ID —— 用应用机器人发到指定会话（推荐，无需 Webhook）
  2) ALERT_WEBHOOK —— 自定义机器人 Webhook
  3) 都没有    —— 只写日志
"""

import json
import os
import subprocess
from datetime import datetime

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

ALERT_CHAT_ID = (os.getenv("ALERT_CHAT_ID") or "").strip()
WEBHOOK = (os.getenv("ALERT_WEBHOOK") or "").strip()
STATE_FILE = os.path.join(BASE_DIR, ".health_state.json")
FAIL_THRESHOLD = 2  # 连续失败 2 次才告警，避免抖动误报


def sh(cmd, timeout=25):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def check_web():
    try:
        r = requests.get("http://127.0.0.1:8501/_stcore/health", timeout=8)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"


def check_bot():
    ok, out = sh("systemctl is-active finance-bot")
    return (out == "active"), f"systemd={out}"


def check_db():
    cmd = (
        "PGPASSWORD=$(grep '^PGPASSWORD=' %s/.env | cut -d= -f2 | tr -d '\\r') "
        "psql -h 127.0.0.1 -U finance -d finance -tAc 'SELECT 1'" % BASE_DIR
    )
    ok, out = sh(cmd)
    return (ok and out.strip() == "1"), f"psql={out[:60]}"


def send_alert(text):
    """按优先级尝试各告警通道"""
    if ALERT_CHAT_ID:
        try:
            from feishu_notify import send_text

            code, body = send_text(ALERT_CHAT_ID, text)
            print("飞书推送(应用机器人):", code, str(body)[:120])
            return True
        except Exception as exc:
            print("应用机器人推送失败:", exc)

    if WEBHOOK:
        try:
            r = requests.post(
                WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=10
            )
            print("飞书推送(Webhook):", r.status_code)
            return r.status_code == 200
        except Exception as exc:
            print("Webhook 推送失败:", exc)

    print("[提示] 未配置告警通道（ALERT_CHAT_ID / ALERT_WEBHOOK），只写日志")
    return False


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as exc:
        print("状态保存失败:", exc)


def main():
    checks = {"网页": check_web(), "飞书机器人": check_bot(), "数据库": check_db()}
    state = load_state()
    lines, alerts = [], []

    for name, (ok, detail) in checks.items():
        if ok:
            state[name] = 0
            lines.append(f"OK   {name}: {detail}")
        else:
            state[name] = state.get(name, 0) + 1
            lines.append(f"FAIL {name}: {detail} (连续 {state[name]} 次)")
            if state[name] == FAIL_THRESHOLD:
                alerts.append(f"- {name} 异常：{detail}")

    save_state(state)
    print("\n".join(lines))

    if alerts:
        msg = (
            "🚨 服务器告警 "
            + datetime.now().strftime("%m-%d %H:%M")
            + "\n"
            + "\n".join(alerts)
            + "\n\n处理：systemctl restart finance-ai finance-bot"
        )
        print("\n=== 告警 ===\n" + msg)
        send_alert(msg)


if __name__ == "__main__":
    main()
