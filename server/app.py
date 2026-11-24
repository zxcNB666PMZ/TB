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
from zhipuai import ZhipuAI

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
st.title("💼 财务 AI 智能分析与台账助手")


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


api_key = get_secret("ZHIPU_API_KEY")
use_mcp = str(get_secret("USE_MCP") or get_secret("LOCAL_MCP") or "").lower() in ("1", "true", "yes")

if not api_key:
    st.error("🚨 未读取到 ZHIPU_API_KEY，请检查 .env 或云端 Secrets。")
    st.stop()

client = ZhipuAI(api_key=api_key)

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
    st.markdown("### 🔐 请先登录财务 AI 系统")
    st.info("为了保护财务数据安全，请验证您的身份。")

    username = st.text_input("用户名")
    password = st.text_input("密码", type="password")

    if st.button("登录"):
        try:
            user = db.find_user(username)
            if user:
                if user.get("password") == password:
                    st.session_state.logged_in = True
                    st.session_state.current_user = user.get("username")
                    st.session_state.current_role = user.get("role") or "未知角色"
                    st.rerun()
                else:
                    st.error("❌ 密码错误！")
            else:
                st.error("❌ 用户不存在！")
        except Exception as e:
            st.error(f"数据库查询失败: {e}")
    st.stop()


# ==========================================
# 侧边栏：功能切换
# ==========================================
with st.sidebar:
    st.header("⚙️ 功能菜单")
    st.caption(f"👤 当前用户: {st.session_state.current_user} ({st.session_state.current_role})")

    app_mode = st.radio("请选择功能模块：", [
        "🤖 AI Agent 智能对话",
        "🧾 批量发票识别台账",
        "🗄️ 历史数据查询",
        "📈 流水智能分类",
    ])

    st.markdown("---")
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
    st.subheader("🤖 AI 财务总监 (Agent 模式)")
    st.info("💡 试试问我：'帮我查一下滴滴的发票总额，如果上限是1000元，还能报多少？'")

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
                        response = client.chat.completions.create(
                            model="glm-4-flash",
                            messages=messages_to_send,
                            tools=agent_tools,
                            tool_choice="auto"
                        )
                        response_message = response.choices[0].message

                        if response_message.tool_calls:
                            messages_to_send.append({
                                "role": "assistant",
                                "content": response_message.content or "",
                                "tool_calls": [tc.model_dump() for tc in response_message.tool_calls]
                            })

                            for tool_call in response_message.tool_calls:
                                tool_name = tool_call.function.name
                                try:
                                    tool_args = json.loads(tool_call.function.arguments or "{}")
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
                            final_answer = response_message.content or "我没有得到有效结果。"
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
    st.subheader("一键提取发票信息并生成台账")
    uploaded_invoices = st.file_uploader("批量上传发票文件", type=["pdf"], accept_multiple_files=True)

    if uploaded_invoices and st.button("🚀 开始识别并存入数据库"):
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
                response = client.chat.completions.create(
                    model="glm-4-flash",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
                raw_json = re.sub(r'```json\s*', '', response.choices[0].message.content)
                raw_json = re.sub(r'```\s*', '', raw_json).strip()
                data = json.loads(raw_json)
                data["文件名"] = file.name
                invoice_data_list.append(data)
            except Exception as e:
                st.error(f"处理 {file.name} 时出错: {e}")

            progress_bar.progress((i + 1) / len(uploaded_invoices))

        if invoice_data_list:
            st.success(f"🎉 成功识别 {len(invoice_data_list)} 张发票！")
            df = pd.DataFrame(invoice_data_list)
            st.dataframe(df, use_container_width=True)

            try:
                n = db.upsert_invoices(invoice_data_list)
                st.success(f"💾 已写入 {n} 条发票记录到 PostgreSQL（发票号码重复会自动更新）")
            except Exception as e:
                st.error(f"数据库保存失败: {e}")

            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 下载本次识别为 CSV", data=csv, file_name='本次发票台账.csv', mime='text/csv')


# ==========================================
# 模块三：历史数据查询
# ==========================================
elif app_mode == "🗄️ 历史数据查询":
    st.subheader("📊 历史发票数据库与商业看板")

    try:
        data = db.all_invoices()

        if data:
            df_history = pd.DataFrame(data)
            df_history["价税合计"] = pd.to_numeric(df_history["价税合计"], errors="coerce").fillna(0)

            col1, col2, col3 = st.columns(3)
            total_amount = df_history["价税合计"].sum()
            col1.metric("💰 历史发票总金额", f"¥ {total_amount:,.2f}")
            col2.metric("🧾 发票总张数", f"{len(df_history)} 张")

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
    st.subheader("📈 流水智能分类")
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

                    response = client.chat.completions.create(
                        model="glm-4-flash",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1,
                    )
                    raw_json = re.sub(r'```json\s*', '', response.choices[0].message.content)
                    raw_json = re.sub(r'```\s*', '', raw_json).strip()

                    category_map = json.loads(raw_json)
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
