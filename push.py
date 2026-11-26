# -*- coding: utf-8 -*-
"""
主动推送：把消息发到飞书（不依赖用户先发消息）。

已经在用的两处证明这套能力是通的：
  - backup.sh 备份完成后推送结果
  - healthcheck.py 检测到故障时推送告警

本模块把它们统一成 push.send()，供：
  ① 网页「📤 发送到飞书」按钮
  ② report_push.py 定时汇总报表
  ③ 异常主动告警
  ④ Agent 的 push_to_feishu 工具
"""

import os

import feishu_notify

# 默认推送到哪：优先读 .env，没有就用你私聊机器人的会话
DEFAULT_CHAT_ID = (
    os.getenv("FEISHU_PUSH_CHAT_ID") or "oc_c28ae6e6a63b53a7aa30c8ec9427da19"
).strip()

MAX_LEN = 3000   # 飞书单条文本上限较宽，这里保守截断


def target_chat(chat_id=None):
    return (chat_id or os.getenv("FEISHU_PUSH_CHAT_ID") or DEFAULT_CHAT_ID).strip()


def send(text, chat_id=None):
    """
    发一条文本消息。返回 (是否成功, 说明)
    不会抛异常——推送失败不应该把业务流程打断。
    """
    body = (text or "").strip()
    if not body:
        return False, "内容为空，没有发送"

    if len(body) > MAX_LEN:
        body = body[: MAX_LEN - 20] + "\n……（内容过长已截断）"

    try:
        code, resp = feishu_notify.send_text(target_chat(chat_id), body)
    except Exception as exc:
        return False, f"发送异常：{exc}"

    if code == 200 and isinstance(resp, dict) and resp.get("code") == 0:
        return True, "已发送到飞书"

    detail = resp.get("msg") if isinstance(resp, dict) else str(resp)[:120]
    return False, f"发送失败（HTTP {code}）：{detail}"


def build_summary(title=None):
    """生成一段发票台账汇总文字"""
    import db

    today = __import__("datetime").date.today().isoformat()
    title = title or f"📊 财务台账日报 · {today}"

    try:
        q = db.quality_summary()
    except Exception as exc:
        return f"{title}\n\n❌ 读取数据库失败：{exc}"

    total_amount = float(q.get("total_amount") or 0)
    lines = [
        title,
        "",
        f"发票总数：{q['total']} 张",
        f"价税合计：¥{total_amount:,.2f}",
    ]

    if q.get("no_seller"):
        ratio = float(q["no_seller_amount"]) / total_amount * 100 if total_amount else 0
        lines.append(
            f"⚠️ 缺销售方：{q['no_seller']} 张（¥{float(q['no_seller_amount']):,.2f}，占 {ratio:.0f}%）"
        )
    if q.get("bad_amount"):
        lines.append(f"⚠️ 金额异常：{q['bad_amount']} 张")

    try:
        rows = db.all_invoices()
        by_seller = {}
        for r in rows:
            key = r.get("销售方名称") or "（未识别销售方）"
            by_seller[key] = by_seller.get(key, 0.0) + float(r.get("价税合计") or 0)
        top = sorted(by_seller.items(), key=lambda x: -x[1])[:5]
        if top:
            lines.append("")
            lines.append("金额最多的 5 家：")
            for name, amount in top:
                lines.append(f"  · {name}：¥{amount:,.2f}")
    except Exception:
        pass

    return "\n".join(lines)


def send_summary(title=None, chat_id=None):
    return send(build_summary(title), chat_id)


def send_alert(title, detail="", chat_id=None):
    """异常告警：标题 + 详情"""
    text = f"🚨 {title}"
    if detail:
        text += f"\n\n{detail}"
    return send(text, chat_id)


if __name__ == "__main__":
    ok, msg = send_summary()
    print(("✅ " if ok else "❌ ") + msg)