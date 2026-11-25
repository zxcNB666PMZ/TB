# -*- coding: utf-8 -*-
"""
财务 AI 智能分析与台账助手 —— 自建 PostgreSQL 版（服务器部署用）

相比 Supabase 版的改动：
1. 去掉 supabase 客户端，全部改走本地 db.py（PostgreSQL 连接池）
2. 数据迁移后不再依赖 *.supabase.co，国内服务器可直连
3. 保留 MCP 可选能力（默认关闭），失败自动降级为直连数据库
4. Agent 循环有兜底回复；calculator 有白名单校验

运行：
    streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
"""

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pdfplumber
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

import ui
import invoice_parser
import permissions
import llm

import db

# ---- MCP 是可选依赖：没装/没启动都不影响主流程 ----
try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except Exception:
    MCP_AVAILABLE = False

# ---- 向量库是可选依赖：没装就自动关闭财报 RAG 功能，其余功能不受影响 ----
RAG_AVAILABLE = False
HuggingFaceEmbeddings = None
Chroma = None
try:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings

    try:
        from langchain_chroma import Chroma
    except ImportError:
        from langchain_community.vectorstores import Chroma

    RAG_AVAILABLE = True
except Exception:
    RAG_AVAILABLE = False

load_dotenv()

st.set_page_config(page_title="财务 AI 助手", page_icon="💼", layout="wide")
ui.inject_css()


# ==========================================
# 智能读取配置
# ==========================================
def get_secret(key):
    val = os.getenv(key)
    if not val:
        try:
            val = st.secrets[key]
        except Exception:
            pass
    return val


api_key = get_secret("DEEPSEEK_API_KEY") or get_secret("ZHIPU_API_KEY")
use_mcp = str(get_secret("USE_MCP") or get_secret("LOCAL_MCP") or "").lower() in ("1", "true", "yes")

if not llm.is_configured():
    st.error(
        "🚨 未配置大模型 API Key。请在 .env 里填写 DEEPSEEK_API_KEY（推荐）或 ZHIPU_API_KEY。"
    )
    st.stop()

# 数据库连通性检查
try:
    db.ping()
except Exception as e:
    st.error(f"🚨 连不上 PostgreSQL：{e}")
    st.info("请确认 PostgreSQL 已启动、schema.sql 已执行、.env 里的 PG* 配置正确。")
    st.stop()


# ==========================================
# 🔒 登录鉴权拦截器
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.current_user = ""
    st.session_state.current_role = ""

if not st.session_state.logged_in:
    _left, _mid, _right = st.columns([1, 1.15, 1])
    with _mid:
        with st.container(border=True):
            ui.login_card_head()
            username = st.text_input("用户名", placeholder="请输入用户名")
            password = st.text_input("密码", type="password", placeholder="请输入密码")

            if st.button("登 录", use_container_width=True, type="primary"):
                try:
                    user, upgraded = db.verify_login(username, password)
                    if user:
                        if upgraded:
                            print(f"[auth] {username} 的明文密码已自动升级为 bcrypt", flush=True)
                        st.session_state.logged_in = True
                        st.session_state.current_user = user.get("username")
                        st.session_state.current_role = permissions.normalize_role(user.get("role"))
                        st.rerun()
                    else:
                        st.error("❌ 用户名或密码错误！")
                except Exception as e:
                    st.error(f"登录校验失败: {e}")
    st.stop()


# ==========================================
# 侧边栏：功能切换
# ==========================================
with st.sidebar:
    st.markdown(
        '<div style="padding:6px 2px 14px">'
        '<div style="font-size:19px;font-weight:700;letter-spacing:.5px">💼 财务 AI 助手</div>'
        '<div style="font-size:12px;opacity:.75;margin-top:2px">智能分析与台账管理</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="background:rgba(255,255,255,.13);border-radius:10px;padding:8px 12px;'
        f'font-size:13px;margin-bottom:12px">👤 {st.session_state.current_user}'
        f'<span style="opacity:.7"> · {st.session_state.current_role}</span></div>',
        unsafe_allow_html=True,
    )

    # ---- 权限：只显示当前角色能访问的页面 ----
    _role = permissions.normalize_role(st.session_state.current_role)
    _pages = permissions.allowed_pages(_role)

    if not _pages:
        st.error("该账号没有分配任何页面权限，请联系管理员。")
        if st.button("🚪 退出登录", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()
        st.stop()

    app_mode = st.radio("功能模块", _pages)

    # 双保险：即使 session_state 被改，也不允许越权进入
    if not permissions.can_access(_role, app_mode):
        st.error("⛔ 你没有权限访问该页面。")
        st.stop()

    st.markdown("---")
    st.markdown(
        f'<div style="font-size:11px;opacity:.6;margin-bottom:6px">'
        f'可访问 {len(_pages)} 个页面 · 模型 {llm.describe()}</div>',
        unsafe_allow_html=True,
    )
    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.logged_in = False
        st.rerun()


# ==========================================
# 异步执行工具
# ==========================================
def run_async(coro, timeout=60):
    """把协程丢到独立线程的新事件循环里执行，规避 asyncio.run 冲突"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)


@st.cache_resource
def get_embeddings():
    """嵌入模型只加载一次"""
    if not RAG_AVAILABLE:
        raise RuntimeError("服务器未安装向量模型，财报问答功能不可用")
    return HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")


# ==========================================
# Agent 工具函数
# ==========================================
def search_financial_report(query):
    """工具1：检索财报向量库"""
    if not RAG_AVAILABLE:
        return "服务器版未启用财报知识库（未安装向量模型），请直接问我发票台账相关的问题。"
    if "vectorstore" not in st.session_state:
        return "当前用户尚未上传任何财报 PDF，无法查询。"
    try:
        docs = st.session_state.vectorstore.similarity_search(query, k=3)
        if not docs:
            return "财报知识库里没有检索到相关内容。"
        return "\n\n".join([doc.page_content for doc in docs])
    except Exception as e:
        return f"财报检索失败: {e}"


def query_invoice_db(supplier_name):
    """工具2：直连本地 PostgreSQL 查发票（购买方、销售方都查）"""
    name = (supplier_name or "").strip()
    if not name:
        return "供应商名称不能为空。"

    try:
        rows, samples = db.query_invoices(name)

        if not rows:
            if samples:
                return (
                    f"数据库中没有找到 '{name}' 的发票记录。"
                    f"数据库中现有的销售方名称有：{', '.join(samples)}。"
                    f"请参考这些名称重新查询，或向用户确认具体公司名。"
                )
            return f"数据库中没有找到 '{name}' 的发票记录，且发票表当前为空。"

        total = sum(float(r["价税合计"]) for r in rows if r.get("价税合计") is not None)
        return (
            f"查询到与 '{name}' 相关的发票共 {len(rows)} 张，"
            f"价税合计总额为 {total:.2f} 元。"
        )
    except Exception as e:
        return f"数据库查询出错: {e}"


def calculator(expression):
    """工具3：安全计算器"""
    expr = str(expression)
    if not re.fullmatch(r"[\d\.\+\-\*/\(\)\s]+", expr):
        return "计算失败：只支持数字和 + - * / ( ) 运算。"
    try:
        return str(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return "计算表达式错误"


# ---- MCP 调用（可选）----
async def call_mcp_query_invoice(supplier_name):
    if not MCP_AVAILABLE:
        return "MCP 依赖未安装，无法调用。"
    async with sse_client("http://127.0.0.1:8000/sse") as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("query_invoice_db", {"supplier_name": supplier_name})
            if result.content and len(result.content) > 0:
                return result.content[0].text
            return "MCP 没有返回结果"


def query_invoice_db_via_mcp(supplier_name):
    try:
        return run_async(call_mcp_query_invoice(supplier_name), timeout=30)
    except Exception as e:
        return f"MCP 调用失败: {e}"


def query_invoice_tool(supplier_name):
    """统一入口：USE_MCP 打开时先走 MCP，失败自动降级直连"""
    if use_mcp:
        res = query_invoice_db_via_mcp(supplier_name)
        if "失败" in res or "未安装" in res:
            return query_invoice_db(supplier_name)
        return res
    return query_invoice_db(supplier_name)


# ==========================================
# 注册工具给大模型
# ==========================================
agent_tools = [
    {
        "type": "function",
        "function": {
            "name": "search_financial_report",
            "description": "当用户询问关于财报、年报、文档内容时，使用此工具检索财报文本。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_invoice_db",
            "description": "当用户询问某个供应商、公司的发票总金额、台账记录时，使用此工具查询发票数据库。",
            "parameters": {
                "type": "object",
                "properties": {"supplier_name": {"type": "string", "description": "供应商或公司名称，如滴滴"}},
                "required": ["supplier_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "当需要进行数学计算（如加减乘除、报销额度计算）时，使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "数学表达式，如 1000-800"}},
                "required": ["expression"]
            }
        }
    }
]

SYSTEM_PROMPT = (
    "你是公司的 AI 财务 Agent，连接着发票数据库（invoices 表）和财报知识库。规则："
    "1) 用户问发票、金额、台账、报销时必须调用 query_invoice_db 工具，不要声称自己无法访问数据库；"
    "2) 需要做加减乘除（例如算报销余额）时调用 calculator 工具；"
    "3) 用户问财报、年报、文档内容时调用 search_financial_report 工具；"
    "4) 工具返回“未找到”时，最多换一个说法再试一次，仍失败就如实告诉用户，绝对不要编造金额。"
)


# ==========================================
# 模块一：AI Agent 智能对话
# ==========================================
if app_mode == "🤖 AI Agent 智能对话":
    ui.hero(
        "AI 财务总监",
        "用自然语言查台账、算报销余额、做财务分析 —— 试试：「帮我查一下滴滴的发票总额，如果上限是 1000 元，还能报多少？」",
    )

    with st.sidebar:
        st.markdown("---")
        st.header("📂 财报知识库")
        if not RAG_AVAILABLE:
            st.info("当前服务器未安装向量模型，财报 PDF 问答已关闭。发票台账功能不受影响。")
        else:
            uploaded_file = st.file_uploader("上传财务 PDF 报告 (供 Agent 检索)", type=["pdf"])
            if uploaded_file is not None and "vectorstore" not in st.session_state:
                with st.spinner("正在解析财报..."):
                    try:
                        with pdfplumber.open(uploaded_file) as pdf:
                            text = "".join([page.extract_text() or "" for page in pdf.pages])
                        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
                        chunks = text_splitter.split_text(text)
                        st.session_state.vectorstore = Chroma.from_texts(chunks, get_embeddings())
                        st.success("✅ 财报已入库，Agent 可随时检索！")
                    except Exception as e:
                        st.error(f"PDF解析失败: {e}")

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{
            "role": "assistant",
            "content": "你好！我是你的 AI 财务总监。我不仅能看财报，还能直接去数据库查你的发票，并帮你算账。你想让我做点什么？"
        }]

    for msg in st.session_state.agent_messages:
        if msg["role"] in ["user", "assistant"]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    if prompt := st.chat_input("例如：查一下滴滴的发票总额，看看超没超预算..."):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI 正在思考并调度工具..."):

                messages_to_send = [{"role": "system", "content": SYSTEM_PROMPT}] + st.session_state.agent_messages.copy()
                final_answer = None

                for step in range(5):
                    try:
                        reply = llm.chat(
                            messages_to_send,
                            tools=agent_tools,
                            tool_choice="auto",
                            temperature=0.3,
                        )

                        if reply.tool_calls:
                            messages_to_send.append({
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
                            })

                            for tool_call in reply.tool_calls:
                                tool_name = tool_call.name
                                try:
                                    tool_args = json.loads(tool_call.arguments or "{}")
                                except Exception:
                                    tool_args = {}

                                st.caption(f"🛠️ Agent 正在调用工具: `{tool_name}` ...")

                                if tool_name == "search_financial_report":
                                    result = search_financial_report(tool_args.get("query", ""))
                                elif tool_name == "query_invoice_db":
                                    result = query_invoice_tool(tool_args.get("supplier_name", ""))
                                elif tool_name == "calculator":
                                    result = calculator(tool_args.get("expression", ""))
                                else:
                                    result = f"未知工具: {tool_name}"

                                st.caption(f"📦 工具返回结果: {result}")

                                messages_to_send.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": str(result)
                                })
                        else:
                            final_answer = reply.content or "我没有得到有效结果。"
                            break
                    except Exception as e:
                        st.error(f"Agent 思考出错: {e}")
                        break

                if final_answer is None:
                    final_answer = "抱歉，我查了几轮仍然没有得出明确结论。可以换成公司全称再问我一次吗？"

                st.write(final_answer)
                st.session_state.agent_messages.append({"role": "assistant", "content": final_answer})


# ==========================================
# 模块二：发票识别 + 存入本地 PostgreSQL
# ==========================================
elif app_mode == "🧾 批量发票识别台账":
    ui.hero(
        "批量发票识别",
        "上传 PDF 发票，自动提取字段并写入台账；相同发票号码重复上传会自动更新，不会产生重复数据。",
    )
    uploaded_invoices = st.file_uploader("批量上传发票文件", type=["pdf"], accept_multiple_files=True)

    if uploaded_invoices and st.button("🚀 开始识别并存入数据库", type="primary"):
        invoice_data_list = []
        progress_bar = st.progress(0)

        for i, file in enumerate(uploaded_invoices):
            text_content = ""
            if file.name.lower().endswith(".pdf"):
                try:
                    with pdfplumber.open(file) as pdf:
                        text_content = "".join([page.extract_text() or "" for page in pdf.pages])
                except Exception:
                    pass

            if not text_content:
                st.warning(f"文件 {file.name} 解析失败，已跳过。")
                progress_bar.progress((i + 1) / len(uploaded_invoices))
                continue

            prompt = f"""
            你是一个专业的财务票据识别助手。请从以下发票文本中提取关键信息，并严格返回 JSON 格式：
            {{
                "发票号码": "提取发票号码",
                "开票日期": "YYYY-MM-DD",
                "购买方名称": "公司名",
                "销售方名称": "公司名",
                "价税合计": 123.45,
                "发票类型": "增值税专票/普票/其他"
            }}
            如果没有找到某项，请填 null。金额必须是纯数字。
            发票文本：{text_content[:2000]}
            """

            try:
                reply_text = llm.chat_text(prompt, temperature=0.1)
                data = llm.parse_json_reply(reply_text, default={})
                if not data:
                    raise ValueError("模型没有返回可解析的 JSON，可能是发票文字不完整")
                data["文件名"] = file.name

                # 规范化 + 校验（金额千分位、日期格式、缺字段都会在这里处理）
                record = invoice_parser.clean_invoice_record(data)
                problems = invoice_parser.validate_invoice_record(record)
                record["_问题"] = problems
                invoice_data_list.append(record)
            except Exception as e:
                st.error(f"处理 {file.name} 时出错: {e}")

            progress_bar.progress((i + 1) / len(uploaded_invoices))

        if invoice_data_list:
            valid_records = [r for r in invoice_data_list if r.get("发票号码")]
            problem_records = [r for r in invoice_data_list if r.get("_问题")]

            st.success(f"🎉 识别完成 {len(invoice_data_list)} 张，其中 {len(valid_records)} 张有发票号码可以入库")

            show_df = pd.DataFrame(
                [{k: v for k, v in r.items() if k != "_问题"} for r in invoice_data_list]
            )
            st.dataframe(show_df, use_container_width=True)

            # 字段缺失/异常提醒
            if problem_records:
                st.warning(
                    f"⚠️ 有 {len(problem_records)} 张发票字段不完整或数值异常，"
                    "入库后统计可能不准，建议核对原始 PDF："
                )
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "文件名": r.get("文件名"),
                                "发票号码": r.get("发票号码"),
                                "销售方": r.get("销售方名称") or "(缺)",
                                "金额": r.get("价税合计"),
                                "问题": "；".join(r.get("_问题") or []),
                            }
                            for r in problem_records
                        ]
                    ),
                    use_container_width=True,
                )

            if valid_records:
                try:
                    n = db.upsert_invoices(valid_records)
                    st.success(f"💾 已写入 {n} 条发票记录（发票号码重复会自动更新）")
                except Exception as e:
                    st.error(f"数据库保存失败: {e}")
            else:
                st.error("❌ 这批文件都没能识别出发票号码，没有写入数据库。请检查 PDF 是否为电子发票原件。")

            csv = show_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 下载本次识别为 CSV", data=csv, file_name='本次发票台账.csv', mime='text/csv')


# ==========================================
# 模块三：历史数据查询
# ==========================================
elif app_mode == "🗄️ 历史数据查询":
    ui.hero("历史发票与商业看板", "查看全部发票台账、金额构成与开票趋势。")

    try:
        data = db.all_invoices()

        if data:
            df_history = pd.DataFrame(data)
            df_history["价税合计"] = pd.to_numeric(df_history["价税合计"], errors="coerce").fillna(0)

            total_amount = df_history["价税合计"].sum()
            col1, col2, col3 = st.columns(3)
            col1.metric("💰 发票总金额", f"¥ {total_amount:,.2f}")
            col2.metric("🧾 发票张数", f"{len(df_history)} 张")
            col3.metric("📅 覆盖天数", f"{df_history['开票日期'].nunique()} 天" if "开票日期" in df_history.columns else "—")

            # 数据质量提醒
            try:
                q = db.quality_summary()
                if q["total"] and q["no_seller"]:
                    ratio = float(q["no_seller_amount"]) / float(q["total_amount"] or 1) * 100
                    st.warning(
                        f"⚠️ 数据质量：{q['no_seller']} 张发票缺少「销售方名称」，"
                        f"涉及金额 ¥{float(q['no_seller_amount']):,.2f}（占 {ratio:.0f}%）。"
                        "这部分金额无法按供应商统计，建议重新上传原始 PDF 覆盖更新。"
                    )
                if q["bad_amount"]:
                    st.warning(f"⚠️ 有 {q['bad_amount']} 张发票金额缺失或异常，请核对。")
            except Exception:
                pass

            st.markdown("---")

            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                if "购买方名称" in df_history.columns:
                    supplier_df = df_history.groupby("购买方名称")["价税合计"].sum().reset_index()
                    fig_pie = px.pie(supplier_df, values="价税合计", names="购买方名称", hole=0.4)
                    st.plotly_chart(fig_pie, use_container_width=True)

            with chart_col2:
                if "开票日期" in df_history.columns:
                    df_history["开票日期"] = pd.to_datetime(df_history["开票日期"], errors="coerce")
                    date_df = df_history.groupby("开票日期")["价税合计"].sum().reset_index()
                    fig_bar = px.bar(date_df, x="开票日期", y="价税合计", text_auto=".2s")
                    st.plotly_chart(fig_bar, use_container_width=True)

            st.dataframe(df_history, use_container_width=True)
        else:
            st.warning("数据库里还没有数据。")
    except Exception as e:
        st.warning(f"读取数据库失败: {e}")


# ==========================================
# 模块四：流水智能分类
# ==========================================
elif app_mode == "📈 流水智能分类":
    ui.hero("流水智能分类", "上传银行流水，AI 自动识别消费类型并生成分类统计。")
    uploaded_excel = st.file_uploader("上传流水 Excel 文件", type=["xlsx", "xls", "csv"])

    if uploaded_excel is not None:
        try:
            df_bank = pd.read_csv(uploaded_excel) if uploaded_excel.name.endswith('.csv') else pd.read_excel(uploaded_excel)
            columns = df_bank.columns.tolist()

            col1, col2 = st.columns(2)
            with col1:
                remark_col = st.selectbox("选择【交易备注】列：", columns)
            with col2:
                amount_col = st.selectbox("选择【金额】列：", columns)

            if st.button("🚀 开始 AI 分类"):
                with st.spinner("AI 正在分析消费意图..."):
                    unique_remarks = df_bank[remark_col].astype(str).unique().tolist()[:50]
                    prompt = f"请将以下备注分类到：['餐饮', '交通', '办公', '工资', '采购', '娱乐', '其他']。严格返回 JSON 字典。\n备注：{unique_remarks}"

                    reply_text = llm.chat_text(prompt, temperature=0.1)
                    category_map = llm.parse_json_reply(reply_text, default={})
                    if not category_map:
                        st.error("AI 没有返回有效的分类结果，本次未写入数据库。请检查 API Key 或稍后重试。")
                        st.stop()

                    df_bank['AI分类'] = df_bank[remark_col].astype(str).map(category_map).fillna('其他')

                    st.dataframe(df_bank[[remark_col, amount_col, 'AI分类']].head(10), use_container_width=True)

                    df_to_save = df_bank.rename(columns={remark_col: '交易备注', amount_col: '金额'})
                    records = df_to_save[['交易备注', '金额', 'AI分类']].to_dict(orient="records")
                    n = db.insert_transactions(records)
                    st.success(f"💾 已写入 {n} 条流水到 PostgreSQL！")

                    chart_df = df_bank.groupby('AI分类')[amount_col].sum().reset_index()
                    fig = px.pie(chart_df, values=amount_col, names='AI分类', hole=0.4)
                    st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"读取失败: {e}")


# ==========================================
# 模块五：用户与权限（仅管理员）
# ==========================================
elif app_mode == "👥 用户与权限":
    if not permissions.can_manage_users(st.session_state.current_role):
        st.error("⛔ 只有管理员可以管理用户。")
        st.stop()

    ui.hero("用户与权限", "给不同的人分配不同角色，各自只看到自己能用的页面。")

    # ---- 角色权限说明 ----
    st.markdown("#### 🎫 角色能看到的页面")
    role_rows = []
    for role, pages in permissions.role_summary():
        role_rows.append({"角色": role, "可访问页面": " 、 ".join(pages) if pages else "（无）"})
    st.dataframe(pd.DataFrame(role_rows), use_container_width=True, hide_index=True)

    st.markdown("---")

    # ---- 现有用户 ----
    st.markdown("#### 👤 现有账号")
    try:
        users = db.list_users()
        role_counts = {}
        for u in users:
            r = permissions.normalize_role(u.get("role"))
            role_counts[r] = role_counts.get(r, 0) + 1

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("账号总数", len(users))
        m2.metric("管理员", role_counts.get("管理员", 0))
        m3.metric("财务专员", role_counts.get("财务专员", 0))
        m4.metric("查看者", role_counts.get("查看者", 0))

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "用户名": u["username"],
                        "角色": permissions.normalize_role(u.get("role")),
                        "可访问页面数": len(permissions.allowed_pages(u.get("role"))),
                    }
                    for u in users
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    except Exception as e:
        st.error(f"读取用户列表失败: {e}")
        users = []

    st.markdown("---")

    tab_add, tab_edit, tab_pwd = st.tabs(["➕ 新建账号", "🔧 改角色", "🔑 重置密码"])

    # 新建账号
    with tab_add:
        with st.form("form_add_user", clear_on_submit=True):
            new_user = st.text_input("用户名", placeholder="例如 zhangsan")
            new_pwd = st.text_input("初始密码", type="password", placeholder="至少 6 位")
            new_pwd2 = st.text_input("确认密码", type="password")
            new_role = st.selectbox("角色", permissions.ALL_ROLES, index=2)
            submitted = st.form_submit_button("创建账号", type="primary")

        if submitted:
            if new_pwd != new_pwd2:
                st.error("两次输入的密码不一致")
            else:
                ok, msg = db.create_user(new_user, new_pwd, new_role)
                (st.success if ok else st.error)(("✅ " if ok else "❌ ") + msg)
                if ok:
                    st.rerun()

    # 改角色
    with tab_edit:
        user_names = [u["username"] for u in users]
        if not user_names:
            st.info("还没有账号")
        else:
            target = st.selectbox("选择账号", user_names, key="edit_target")
            current = next(
                (permissions.normalize_role(u.get("role")) for u in users if u["username"] == target),
                "",
            )
            st.caption(f"当前角色：{current}")
            new_role2 = st.selectbox(
                "改成", permissions.ALL_ROLES, index=permissions.ALL_ROLES.index(current) if current in permissions.ALL_ROLES else 2
            )
            if st.button("保存角色", type="primary"):
                # 防止把最后一个管理员降级，导致没人能管
                if current == "管理员" and new_role2 != "管理员" and db.admin_count() <= 1:
                    st.error("❌ 这是最后一个管理员，不能改成其他角色（否则没人能管理系统了）")
                elif target == st.session_state.current_user and new_role2 != "管理员":
                    st.warning("⚠️ 你改的是自己的角色，保存后会立即失去管理权限。")
                    db.update_user_role(target, new_role2)
                    st.session_state.current_role = new_role2
                    st.rerun()
                else:
                    db.update_user_role(target, new_role2)
                    st.success(f"✅ 已把「{target}」改为 {new_role2}")
                    st.rerun()

    # 重置密码
    with tab_pwd:
        user_names2 = [u["username"] for u in users]
        if not user_names2:
            st.info("还没有账号")
        else:
            target2 = st.selectbox("选择账号", user_names2, key="pwd_target")
            p1 = st.text_input("新密码", type="password", key="p1")
            p2 = st.text_input("确认新密码", type="password", key="p2")
            if st.button("重置密码", type="primary"):
                if not p1 or len(p1) < 6:
                    st.error("密码至少 6 位")
                elif p1 != p2:
                    st.error("两次输入的密码不一致")
                else:
                    db.set_password(target2, p1)
                    st.success(f"✅ 已重置「{target2}」的密码")

    st.markdown("---")
    with st.expander("🗑️ 删除账号（谨慎操作）"):
        names = [u["username"] for u in users if u["username"] != st.session_state.current_user]
        if not names:
            st.info("没有可删除的其他账号")
        else:
            victim = st.selectbox("选择要删除的账号", names, key="del_target")
            confirm = st.text_input("输入 DELETE 确认删除", key="del_confirm")
            if st.button("删除账号"):
                if confirm.strip().upper() != "DELETE":
                    st.error("请先输入 DELETE 确认")
                elif db.admin_count() <= 1 and any(
                    u["username"] == victim and permissions.normalize_role(u.get("role")) == "管理员"
                    for u in users
                ):
                    st.error("❌ 不能删除最后一个管理员")
                else:
                    ok = db.delete_user(victim)
                    st.success(f"✅ 已删除「{victim}」" if ok else "未找到该用户")
                    st.rerun()
