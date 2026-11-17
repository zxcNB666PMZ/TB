import streamlit as st
import os
import json
import re
import pandas as pd
from zhipuai import ZhipuAI
from dotenv import load_dotenv
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
import plotly.express as px
from supabase import create_client, Client

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
load_dotenv()

st.set_page_config(page_title="财务 AI 助手", page_icon="💼", layout="wide")
st.title("💼 财务 AI 智能分析与台账助手 (云端版)")

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
supabase_url = get_secret("SUPABASE_URL")
supabase_key = get_secret("SUPABASE_KEY")

if not api_key or not supabase_url:
    st.error("🚨 致命错误：未读取到 API 或 数据库密钥！请检查云端 Secrets。")
    st.stop()

client = ZhipuAI(api_key=api_key)

# 最原始、最稳定的连接方式，彻底清理可能存在的斜杠
@st.cache_resource
def init_supabase() -> Client:
    clean_url = supabase_url.strip().rstrip("/")
    return create_client(clean_url, supabase_key)

supabase = init_supabase()

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
            response = supabase.table("users").select("*").eq("username", username).execute()
            if response.data:
                user_info = response.data[0]
                if user_info.get("password") == password:
                    st.session_state.logged_in = True
                    st.session_state.current_user = user_info.get("username")
                    st.session_state.current_role = user_info.get("role", "未知角色")
                    st.rerun()
                else:
                    st.error("❌ 密码错误！")
            else:
                st.error("❌ 用户不存在！")
        except Exception as e:
            st.error(f"数据库查询失败: {e}")
    st.stop() 

# ==========================================
# 侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 功能菜单")
    st.caption(f"👤 当前用户: {st.session_state.current_user} ({st.session_state.current_role})")
    
    app_mode = st.radio("请选择功能模块：", [
        "🤖 AI Agent 智能对话", 
        "🧾 批量发票识别台账", 
        "🗄️ 历史数据查询", 
        "📈 流水智能分类"
    ])
    
    st.markdown("---")
    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.logged_in = False
        st.rerun()

# ==========================================
# 工具函数 (云端直连版)
# ==========================================
def search_financial_report(query):
    if "vectorstore" not in st.session_state:
        return "当前用户尚未上传任何财报 PDF，无法查询。"
    docs = st.session_state.vectorstore.similarity_search(query, k=3)
    return "\n\n".join([doc.page_content for doc in docs])

def query_invoice_db(supplier_name):
    """云端直接连库查账"""
    try:
        response = supabase.table("invoices").select("价税合计").or_(
            f"购买方名称.like.%{supplier_name}%,销售方名称.like.%{supplier_name}%"
        ).execute()
        if not response.data:
            return f"数据库中没有找到关于 '{supplier_name}' 的发票记录。"
        total = sum(float(item["价税合计"]) for item in response.data if item["价税合计"])
        return f"查询到 '{supplier_name}' 的发票总金额为：{total} 元。"
    except Exception as e:
        return f"查询出错: {e}"

def calculator(expression):
    try:
        return str(eval(expression))
    except Exception:
        return "计算表达式错误"

agent_tools = [
    {"type": "function", "function": {"name": "search_financial_report", "description": "检索财报", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "query_invoice_db", "description": "查发票金额", "parameters": {"type": "object", "properties": {"supplier_name": {"type": "string"}}, "required": ["supplier_name"]}}},
    {"type": "function", "function": {"name": "calculator", "description": "计算器", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}}
]

# ==========================================
# 模块一：AI Agent
# ==========================================
if app_mode == "🤖 AI Agent 智能对话":
    st.subheader("🤖 AI 财务总监 (Agent 模式)")
    st.info("💡 试试问我：'帮我查一下滴滴的发票总额，如果上限是1000元，还能报多少？'")
    
    with st.sidebar:
        st.markdown("---")
        st.header("📂 财报知识库")
        uploaded_file = st.file_uploader("上传财务 PDF", type=["pdf"])
        if uploaded_file is not None and "vectorstore" not in st.session_state:
            with st.spinner("正在解析财报..."):
                try:
                    with pdfplumber.open(uploaded_file) as pdf:
                        text = "".join([page.extract_text() or "" for page in pdf.pages])
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
                    chunks = text_splitter.split_text(text)
                    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
                    st.session_state.vectorstore = Chroma.from_texts(chunks, embeddings)
                    st.success("✅ 财报已入库！")
                except Exception as e:
                    st.error(f"PDF解析失败: {e}")

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "你好！我是你的 AI 财务总监。我不仅能看财报，还能直接去数据库查你的发票。"}]

    for msg in st.session_state.agent_messages:
        if msg["role"] in ["user", "assistant"]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    if prompt := st.chat_input("例如：查一下滴滴的发票总额..."):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI 正在思考..."):
                messages_to_send = st.session_state.agent_messages.copy()
                for step in range(5):
                    try:
                        response = client.chat.completions.create(
                            model="glm-4-flash", messages=messages_to_send, tools=agent_tools, tool_choice="auto"
                        )
                        response_message = response.choices[0].message
                        
                        if response_message.tool_calls:
                            messages_to_send.append(response_message.model_dump())
                            for tool_call in response_message.tool_calls:
                                tool_name = tool_call.function.name
                                tool_args = json.loads(tool_call.function.arguments)
                                st.caption(f"🛠️ Agent 正在调用工具: `{tool_name}` ...")
                                
                                if tool_name == "search_financial_report":
                                    result = search_financial_report(tool_args["query"])
                                elif tool_name == "query_invoice_db":
                                    # 云端直接直连
                                    result = query_invoice_db(tool_args["supplier_name"])
                                elif tool_name == "calculator":
                                    result = calculator(tool_args["expression"])
                                else:
                                    result = "未知工具"
                                
                                st.caption(f"📦 工具返回结果: {result}")
                                messages_to_send.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(result)})
                        else:
                            final_answer = response_message.content
                            st.write(final_answer)
                            st.session_state.agent_messages.append({"role": "assistant", "content": final_answer})
                            break
                    except Exception as e:
                        st.error(f"Agent 思考出错: {e}")
                        break

# ==========================================
# 模块二：发票识别
# ==========================================
elif app_mode == "🧾 批量发票识别台账":
    st.subheader("一键提取发票信息并生成台账")
    uploaded_invoices = st.file_uploader("批量上传发票文件", type=["pdf"], accept_multiple_files=True)

    if uploaded_invoices and st.button("🚀 开始识别并存入云端"):
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
                records = df.to_dict(orient="records")
                supabase.table("invoices").insert(records).execute()
                st.success("💾 数据已成功沉淀到 Supabase 云端数据库！")
            except Exception as e:
                st.error(f"云端数据库保存失败: {e}")
            
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 下载本次识别为 CSV", data=csv, file_name='本次发票台账.csv', mime='text/csv')

# ==========================================
# 模块三：历史数据查询
# ==========================================
elif app_mode == "🗄️ 历史数据查询":
    st.subheader("📊 历史发票数据库与商业看板")
    
    try:
        response = supabase.table("invoices").select("*").execute()
        data = response.data
        
        if data:
            df_history = pd.DataFrame(data)
            df_history['价税合计'] = pd.to_numeric(df_history['价税合计'], errors='coerce').fillna(0)
            
            col1, col2, col3 = st.columns(3)
            total_amount = df_history['价税合计'].sum()
            col1.metric("💰 历史发票总金额", f"¥ {total_amount:,.2f}")
            col2.metric("🧾 发票总张数", f"{len(df_history)} 张")
            
            st.markdown("---")
            
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                supplier_df = df_history.groupby('购买方名称')['价税合计'].sum().reset_index()
                fig_pie = px.pie(supplier_df, values='价税合计', names='购买方名称', hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with chart_col2:
                df_history['开票日期'] = pd.to_datetime(df_history['开票日期'], errors='coerce')
                date_df = df_history.groupby('开票日期')['价税合计'].sum().reset_index()
                fig_bar = px.bar(date_df, x='开票日期', y='价税合计', text_auto='.2s')
                st.plotly_chart(fig_bar, use_container_width=True)

            st.dataframe(df_history, use_container_width=True)
        else:
            st.warning("数据库里还没有数据。")
    except Exception as e:
        st.warning(f"读取云端数据库失败: {e}")

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
            with col1: remark_col = st.selectbox("选择【交易备注】列：", columns)
            with col2: amount_col = st.selectbox("选择【金额】列：", columns)

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
                    supabase.table("transactions").insert(records).execute()
                    st.success("💾 数据已存入云端 transactions 表！")
                    
                    chart_df = df_bank.groupby('AI分类')[amount_col].sum().reset_index()
                    fig = px.pie(chart_df, values=amount_col, names='AI分类', hole=0.4)
                    st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"读取失败: {e}")
