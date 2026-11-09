 
import streamlit as st
import time

# 1. 设置网页标题和图标
st.set_page_config(page_title="财务 AI 助手", page_icon="💼")

st.title("💼 财务 AI 智能问答助手")
st.caption("这是你的 AI 后端界面，目前正在使用模拟数据。")

# 2. 侧边栏：模拟文件上传功能
with st.sidebar:
    st.header("知识库管理")
    uploaded_file = st.file_uploader("上传财务 PDF 报告", type=["pdf"])
    if uploaded_file is not None:
        st.success(f"已成功加载: {uploaded_file.name}")
    else:
        st.info("请先上传一份财务 PDF（当前为演示模式，不上传也能聊）")

# 3. 对话记录初始化
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "你好！我是你的财务助手，请问有什么可以帮你？"}]

# 4. 展示历史对话
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 5. 接收用户输入并模拟回复
if prompt := st.chat_input("例如：帮我分析一下今年的营收趋势..."):
    # 显示用户的问题
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # 模拟 AI 思考过程
    with st.chat_message("assistant"):
        with st.spinner("AI 正在查阅财报中..."):
            time.sleep(1.5) # 假装思考1.5秒
            response = f"收到你的问题：“{prompt}”。\n\n（这是一个模拟回答，因为还没接入大模型。下一步我们就会让它真正变聪明！）"
            st.write(response)
            st.session_state.messages.append({"role": "assistant", "content": response})