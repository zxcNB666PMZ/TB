import streamlit as st
import os
from zhipuai import ZhipuAI
from dotenv import load_dotenv
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# 解决国内下载 HuggingFace 模型慢的问题
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

load_dotenv()

st.set_page_config(page_title="财务 AI 助手", page_icon="💼")
st.title("💼 财务 AI 智能问答助手 (RAG版)")
st.caption("上传财报 PDF，让 AI 基于文档内容精准回答。")

client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

# 初始化历史对话
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "你好！请先在左侧上传财务 PDF，然后向我提问。"}]

# 侧边栏：处理 PDF
with st.sidebar:
    st.header("📂 文档知识库")
    uploaded_file = st.file_uploader("上传财务 PDF 报告", type=["pdf"])
    
    if uploaded_file is not None:
        # 检查是否已经处理过该文件，避免每次聊天都重新处理
        if "vectorstore" not in st.session_state:
            with st.spinner("正在解析 PDF 并存入知识库，请稍候..."):
                # 1. 提取 PDF 文本
                reader = PdfReader(uploaded_file)
                text = "".join([page.extract_text() for page in reader.pages if page.extract_text()])
                
                # 2. 文本切片 (每500字一段，重叠50字，防止上下文断裂)
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
                chunks = text_splitter.split_text(text)
                
                # 3. 向量化并存入本地库 (这里用的是一个很小的开源中文向量模型)
                embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
                st.session_state.vectorstore = Chroma.from_texts(chunks, embeddings)
                
                st.success("✅ 财报解析完成！可以开始提问了。")
        else:
            st.success("✅ 财报已在知识库中。")

# 展示历史对话
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 接收提问
if prompt := st.chat_input("例如：这份财报中，今年的总营收是多少？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("AI 正在查阅财报并思考..."):
            try:
                # 1. 检索阶段：去库里找和问题最相关的 3 段文本
                context = ""
                if "vectorstore" in st.session_state:
                    docs = st.session_state.vectorstore.similarity_search(prompt, k=3)
                    context = "\n\n".join([doc.page_content for doc in docs])
                
                # 2. 生成阶段：把检索到的资料塞给大模型
                if context:
                    system_prompt = f"""你是一个专业的财务分析师。请严格根据以下【参考资料】回答用户的问题。
如果参考资料中找不到答案，请诚实地回答“根据上传的文档，我找不到相关信息”，绝不要编造。

【参考资料】：
{context}
"""
                    # 将系统提示词加入消息列表发给大模型
                    messages_to_send = [{"role": "system", "content": system_prompt}] + st.session_state.messages
                else:
                    messages_to_send = st.session_state.messages

                response = client.chat.completions.create(
                    model="glm-4-flash",
                    messages=messages_to_send,
                    temperature=0.3, # 回答问题降低随机性，更严谨
                )
                answer = response.choices[0].message.content
            except Exception as e:
                answer = f"哎呀，出错了：{e}"
                
            st.write(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})