# -*- coding: utf-8 -*-
"""
统一的 AI Agent 核心：网页的「智能对话」和飞书机器人共用这一份代码。

设计要点：
1. 只有一套工具定义（TOOLS）和一套执行逻辑，两边行为完全一致
2. 对话记忆存在 PostgreSQL 的 chat_messages 表里，不在内存里
   —— 这样网页刷新不丢、机器人重启不丢，同一用户两边还能看到同一段对话
3. conversation_key 是"谁在聊"的唯一标识：
       user:admin          → 已绑定飞书的网页用户（两边共享）
       feishu:ou_xxx       → 还没绑定网页账号的飞书用户（单独线程）
"""

import ast
import operator

import db
import llm

SYSTEM_PROMPT = (
    "你是公司的 AI 财务助手，可以在网页和飞书上使用。当前时区为北京时间。"
    "规则："
    "1) 问某家公司/供应商的发票金额，调用 query_invoice_db；"
    "问“一共多少张/总共花了多少/按公司汇总/哪家最多”这类总体统计，调用 invoice_overview。"
    "2) 涉及“报销上限/预算/还能报多少/超没超”的问题，必须调用 reimbursement_check，"
    "把上限数字作为 limit_amount 传进去，绝对不要自己做减法或估算。工具算出来的数字要原样转述。"
    "3) 绝不能凭空编造数字，也不能说“我无法访问数据库”。"
    "4) 工具没找到时，换更短的关键词再查一次（如“北京滴滴出行科技有限公司”→“滴滴”）；"
    "仍然没有就如实告知，并提示库里现有的公司名。"
    "5) 需要四则运算时调用 calculator，不要心算。"
    "6) 回答口语化、适合手机阅读；金额保留两位小数；不要罗列无关字段。"
    "7) 不要把“发票”“总额”这类通用词当公司名去查。"
)

# ==========================================
# 工具实现
# ==========================================
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
        key = row.get("销售方名称") or "（未识别销售方）"
        item = detail.setdefault(key, {"n": 0, "amt": 0.0})
        item["n"] += 1
        item["amt"] += amount

    lines = "\n".join(
        f"  {k}：{v['n']} 张，{v['amt']:.2f} 元"
        for k, v in sorted(detail.items(), key=lambda x: -x[1]["amt"])
    )
    return f"找到与“{name}”相关的发票共 {len(rows)} 张，价税合计 {total:.2f} 元。\n按销售方拆分：\n{lines}"


def reimbursement_check(supplier_name, limit_amount):
    """报销额度核算：由代码算，不交给模型算"""
    name = (supplier_name or "").strip()
    if not name:
        return "请提供要核算的公司或供应商名称。"

    try:
        limit = float(limit_amount)
    except (TypeError, ValueError):
        return f"报销上限“{limit_amount}”不是有效数字，请只给数字，例如 5000。"

    try:
        rows, samples = db.query_invoices(name)
    except Exception as exc:
        return f"查询数据库出错：{exc}"

    if not rows:
        hint = "、".join(samples) if samples else "（库是空的）"
        return f"没有找到与“{name}”相关的发票，无法核算额度。库里现有的销售方有：{hint}。"

    used = sum(float(r.get("价税合计") or 0) for r in rows)
    remaining = round(limit - used, 2)

    head = f"「{name}」相关发票共 {len(rows)} 张，已开票金额 {used:.2f} 元；报销上限 {limit:.2f} 元。"

    if remaining > 0.005:
        body = f"还能报 {remaining:.2f} 元（已用 {used / limit * 100:.1f}%）。" if limit else f"还能报 {remaining:.2f} 元。"
    elif abs(remaining) <= 0.005:
        body = "额度刚好用完，还能报 0.00 元。"
    else:
        body = (
            f"已经超额 {-remaining:.2f} 元，还能报 0.00 元。"
            f"如需报销需额外审批（累计 {used:.2f} 元 > 上限 {limit:.2f} 元）。"
        )

    return head + body


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("只支持数字")
    if isinstance(node, ast.BinOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ValueError("不支持的运算符")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ValueError("不支持的运算符")
        return op(_safe_eval(node.operand))
    raise ValueError("表达式里只能有数字和四则运算")


def calculator(expression):
    """安全四则运算（不用 eval，避免注入）"""
    text = (expression or "").strip().replace("×", "*").replace("÷", "/").replace("，", ",").replace(",", "")
    if not text:
        return "请提供要计算的表达式。"
    try:
        value = _safe_eval(ast.parse(text, mode="eval"))
    except Exception as exc:
        return f"计算失败：{exc}（只能做加减乘除和括号）"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{text} = {value}"


def push_to_feishu(text=None, kind="text"):
    """
    主动把消息推送到飞书（不需要用户先在飞书发消息）。

    kind:
      text    —— 推送 text 参数里的内容
      summary —— 生成并推送当前发票台账汇总
    """
    import push

    if kind == "summary" or not (text or "").strip():
        ok, msg = push.send_summary()
        return f"{'✅' if ok else '❌'} {msg}（已推送台账汇总）"

    ok, msg = push.send(text)
    return f"{'✅' if ok else '❌'} {msg}"


def system_info():
    """回答“你是什么模型/系统配置如何”这类关于自身的问题"""
    lines = [
        f"当前大模型：{llm.describe()}",
        f"供应商：{llm.provider()}，模型：{llm.model_name()}",
    ]

    used, reason = llm.last_used()
    if reason:
        lines.append(f"注意：主模型不可用（{reason}），上一次实际使用的是 {used}")

    try:
        q = db.quality_summary()
        lines.append(f"发票数据：{q['total']} 张，价税合计 {float(q['total_amount']):.2f} 元")
        if q["no_seller"]:
            lines.append(f"其中 {q['no_seller']} 张缺销售方名称")
    except Exception as exc:
        lines.append(f"（查询数据库失败：{exc}）")

    try:
        stats = db.chat_stats()
        lines.append(f"对话记录：{stats['conversations']} 个会话 / {stats['messages']} 条消息")
    except Exception:
        pass

    lines.append("数据来源：本机 PostgreSQL，非云端")
    return "\n".join(lines)


# ==========================================
# 工具声明（OpenAI / DeepSeek 通用格式）
# ==========================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_invoice_db",
            "description": "按公司/供应商名称查询发票：统计张数与价税合计金额（购买方和销售方都会匹配，支持别名）。",
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
            "description": "发票总览统计：一共有多少张发票、总金额多少、按销售方分组的金额与张数。适用于“总共多少”“哪家最多”“汇总一下”。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reimbursement_check",
            "description": (
                "报销额度核算：给定某公司的报销上限（元），返回已开票金额、还能报多少、是否超额。"
                "凡涉及“上限/预算/还能报多少/超没超”必须调用本工具，不要自己算。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_name": {"type": "string", "description": "公司或供应商名称关键词"},
                    "limit_amount": {"type": "number", "description": "报销上限金额（元），只填数字"},
                },
                "required": ["supplier_name", "limit_amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "四则运算计算器，用于金额加减乘除，避免心算错误。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式，如 (12671.09-5000)*0.06"}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": (
                "查询系统自身信息：当前使用哪个大模型、数据库有多少发票和对话。"
                "用户问“你是什么模型/接的什么AI/用的哪家模型/系统配置”时必须调用本工具，不要瞎猜。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "push_to_feishu",
            "description": (
                "把内容主动推送到用户的飞书（不需要用户先在飞书发消息）。"
                "用户说“发到我飞书/推给飞书/把结果发给我/发个汇总给我”时调用。"
                "不传 text 就推送完整的发票台账汇总。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要推送的内容；留空则自动生成台账汇总",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["text", "summary"],
                        "description": "text=推指定内容，summary=推台账汇总",
                    },
                },
            },
        },
    },
]

_HANDLERS = {
    "query_invoice_db": lambda a: query_invoice_db(a.get("supplier_name", "")),
    "invoice_overview": lambda a: invoice_overview(),
    "reimbursement_check": lambda a: reimbursement_check(
        a.get("supplier_name", ""), a.get("limit_amount")
    ),
    "calculator": lambda a: calculator(a.get("expression", "")),
    "system_info": lambda a: system_info(),
    "push_to_feishu": lambda a: push_to_feishu(
        a.get("text"), a.get("kind") or "text"
    ),
}


# ==========================================
# 对话执行
# ==========================================
def run(conversation_key, user_text, channel="web", max_steps=5,
        extra_tools=None, extra_handlers=None, history_limit=20, on_tool=None):
    """
    处理一轮对话。返回：
        {"answer": 文本, "tools": [{"name","args","result"}], "error": 错误信息或 None}
    """
    tools = TOOLS + list(extra_tools or [])
    handlers = dict(_HANDLERS)
    handlers.update(extra_handlers or {})

    trace = []
    try:
        history = db.load_chat(conversation_key, limit=history_limit)
    except Exception as exc:
        history = []
        print(f"[agent] 读取历史失败: {exc}", flush=True)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    messages.append({"role": "user", "content": user_text})

    try:
        db.save_chat(conversation_key, "user", user_text, channel=channel)
    except Exception as exc:
        print(f"[agent] 保存用户消息失败: {exc}", flush=True)

    answer = None
    error = None

    for _ in range(max_steps):
        try:
            reply = llm.chat(messages, tools=tools, tool_choice="auto", temperature=0.3)
        except llm.LLMError as exc:
            error = str(exc)
            answer = f"模型调用失败：{error}"
            break
        except Exception as exc:
            error = str(exc)
            answer = f"处理出错：{error}"
            break

        if not reply.tool_calls:
            answer = reply.content.strip() or "我没有得到有效结果，换个说法再问我一次？"
            break

        messages.append(
            {
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in reply.tool_calls
                ],
            }
        )

        for tc in reply.tool_calls:
            import json

            try:
                args = json.loads(tc.arguments or "{}")
            except Exception:
                args = {}

            handler = handlers.get(tc.name)
            result = handler(args) if handler else f"未知工具：{tc.name}"

            trace.append({"name": tc.name, "args": args, "result": str(result)})
            if on_tool:
                try:
                    on_tool(tc.name, args, result)
                except Exception:
                    pass

            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": str(result)}
            )

    if answer is None:
        answer = "抱歉，我查了几轮仍然没有得出明确结论。可以换成公司全称再问我一次吗？"

    try:
        db.save_chat(conversation_key, "assistant", answer, channel=channel)
    except Exception as exc:
        print(f"[agent] 保存回答失败: {exc}", flush=True)

    return {"answer": answer, "tools": trace, "error": error}