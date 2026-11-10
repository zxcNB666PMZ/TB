import streamlit as st
import os
import json
import re
import pandas as pd
from zhipuai import ZhipuAI
from dotenv import load_dotenv
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# 解决国内下载 HuggingFace 模型慢的问题
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
load_dotenv()

st.set_page_config(page_title="财务 AI 助手", page_icon="💼", layout="wide")
st.title("💼 财务 AI 智能分析与台账助手")

client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

# ==========================================
# 侧边栏：功能切换
# ==========================================
with st.sidebar:
    st.header("⚙️ 功能菜单")
    app_mode = st.radio("请选择功能模块：", ["💬 财报文档问答 (RAG)", "🧾 批量发票识别台账"])

# ==========================================
# 模块一：原有 RAG 问答模块
# ==========================================
if app_mode == "💬 财报文档问答 (RAG)":
    st.subheader("财报文档智能问答")
    
    with st.sidebar:
        st.markdown("---")
        st.header("📂 文档知识库")
        uploaded_file = st.file_uploader("上传财务 PDF 报告", type=["pdf"])
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "你好！请在左侧上传财报 PDF，然后向我提问。"}]
    
    if uploaded_file is not None and "vectorstore" not in st.session_state:
        with st.spinner("正在解析 PDF 并存入知识库..."):
            reader = PdfReader(uploaded_file)
            text = "".join([page.extract_text() for page in reader.pages if page.extract_text()])
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            chunks = text_splitter.split_text(text)
            embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
            st.session_state.vectorstore = Chroma.from_texts(chunks, embeddings)
            st.success("✅ 财报解析完成！")

    # 展示历史对话
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # 聊天输入
    if prompt := st.chat_input("例如：这份财报中，今年的总营收是多少？"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        with st.chat_message("assistant"):
            with st.spinner("AI 正在查阅财报..."):
                try:
                    context = ""
                    if "vectorstore" in st.session_state:
                        docs = st.session_state.vectorstore.similarity_search(prompt, k=3)
                        context = "\n\n".join([doc.page_content for doc in docs])
                    
                    if context:
                        system_prompt = f"你是一个财务分析师。请严格根据以下【参考资料】回答问题，不要编造。\n\n【参考资料】：\n{context}"
                        messages_to_send = [{"role": "system", "content": system_prompt}] + st.session_state.messages
                    else:
                        messages_to_send = st.session_state.messages

                    response = client.chat.completions.create(
                        model="glm-4-flash",
                        messages=messages_to_send,
                        temperature=0.3,
                    )
                    answer = response.choices[0].message.content
                except Exception as e:
                    answer = f"出错了：{e}"
                st.write(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})

# ==========================================
# 模块二：新增的发票批量识别模块
# ==========================================
elif app_mode == "🧾 批量发票识别台账":
    st.subheader("一键提取发票信息并生成台账")
    st.info("💡 支持批量上传电子发票 PDF。AI 将自动提取：发票号码、开票日期、购买方、价税合计，并生成可下载的表格。")

    uploaded_invoices = st.file_uploader("批量上传发票文件", type=["pdf"], accept_multiple_files=True)

    if uploaded_invoices and st.button("🚀 开始识别并生成台账"):
        invoice_data_list = []
        progress_bar = st.progress(0)
        
        for i, file in enumerate(uploaded_invoices):
            text_content = ""
            # 简单处理：如果是 PDF，提取文字
            if file.name.lower().endswith(".pdf"):
                reader = PdfReader(file)
                text_content = "".join([page.extract_text() for page in reader.pages if page.extract_text()])
            
            if not text_content:
                st.warning(f"文件 {file.name} 解析失败或没有文字，已跳过。")
                continue

            # 用大模型提取 JSON
            prompt = f"""
            你是一个专业的财务票据识别助手。请从以下发票文本中提取关键信息，并严格返回 JSON 格式（不要任何多余解释）：
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
                raw_json = response.choices[0].message.content
                # 清理可能带的 markdown 符号
                raw_json = re.sub(r'```json\s*', '', raw_json)
                raw_json = re.sub(r'```\s*', '', raw_json).strip()
                
                data = json.loads(raw_json)
                data["文件名"] = file.name
                invoice_data_list.append(data)
            except Exception as e:
                st.error(f"处理 {file.name} 时出错: {e}")
            
            progress_bar.progress((i + 1) / len(uploaded_invoices))

        if invoice_data_list:
            st.success(f"🎉 成功识别 {len(invoice_data_list)} 张发票！")
            
            # 使用 Pandas 生成表格
            df = pd.DataFrame(invoice_data_list)
            
            # 调整列的顺序
            cols = ["文件名", "发票号码", "开票日期", "购买方名称", "销售方名称", "价税合计", "发票类型"]
            cols = [c for c in cols if c in df.columns]
            df = df[cols]
            
            st.dataframe(df, use_container_width=True)
            
            # 提供下载功能
            csv = df.to_csv(index=False).encode('utf-8-sig') # 加上 sig 防止 Excel 打开乱码
            st.download_button(
                label="📥 下载为 CSV 台账",
                data=csv,
                file_name='发票台账.csv',
                mime='text/csv',
            )