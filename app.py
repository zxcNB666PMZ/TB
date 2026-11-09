import streamlit as st
import os
from zhipuai import ZhipuAI
from dotenv import load_dotenv

# 加载 .env 文件里的密码
load_dotenv()

# 1. 设置网页标题
st.set_page_config(page_title="财务 AI 助手", page_icon="💼")
st.title("💼 财务 AI 智能问答助手")
st.caption("已接入智谱 GLM 模型，安全、免费、极速。")

# 初始化智谱客户端
client = ZhipuAI(api_key="57b65822406342cda424b46d135e02d8.0Jnr8pPt79znLtsj")
# 2. 对话记录初始化
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "你好！我是你的财务助手，有什么可以帮你的？"}]

# 3. 展示历史对话
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 4. 接收用户输入并调用真实大模型
if prompt := st.chat_input("例如：请帮我制定一个家庭理财计划..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # 调用大模型
    with st.chat_message("assistant"):
        with st.spinner("AI 正在飞速思考中..."):
            try:
                response = client.chat.completions.create(
                    model="glm-4-flash", # 免费且速度极快的模型
                    messages=st.session_state.messages,
                    temperature=0.7,
                )
                answer = response.choices[0].message.content
            except Exception as e:
                answer = f"哎呀，出错了：{e}"
                
            st.write(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})