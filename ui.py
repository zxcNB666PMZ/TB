# -*- coding: utf-8 -*-
"""UI 主题与组件：统一视觉风格（CSS 注入 + 可复用组件）"""

import streamlit as st

CSS = """
<style>
/* ---------- 全局 ---------- */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.stApp {
    background: linear-gradient(160deg, #f5f7fb 0%, #eef2f9 100%);
}
.block-container {
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    max-width: 1200px;
}

/* ---------- 隐藏 Streamlit 默认元素 ---------- */
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }

/* ---------- 侧边栏 ---------- */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1e3a8a 0%, #1e40af 60%, #2563eb 100%);
}
[data-testid="stSidebar"] * { color: #e5edff !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.18); }
[data-testid="stSidebar"] .stRadio label {
    padding: 8px 10px; border-radius: 10px; transition: .2s;
}
[data-testid="stSidebar"] .stRadio label:hover { background: rgba(255,255,255,.12); }
[data-testid="stSidebar"] .stButton>button {
    background: rgba(255,255,255,.14); color: #fff;
    border: 1px solid rgba(255,255,255,.25);
}
[data-testid="stSidebar"] .stButton>button:hover { background: rgba(255,255,255,.24); }

/* ---------- 按钮 ---------- */
.stButton>button {
    border-radius: 10px;
    border: 1px solid #dbe3f0;
    background: #fff;
    color: #1e40af;
    font-weight: 600;
    padding: .5rem 1.1rem;
    transition: all .18s ease;
}
.stButton>button:hover {
    border-color: #2563eb;
    box-shadow: 0 4px 14px rgba(37,99,235,.18);
    transform: translateY(-1px);
}
.stButton>button[kind="primary"] {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: #fff; border: none;
}

/* ---------- 输入框 ---------- */
.stTextInput input, .stNumberInput input {
    border-radius: 10px !important;
    border: 1px solid #dbe3f0 !important;
    padding: .55rem .8rem !important;
    background: #fff !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,.12) !important;
}

/* ---------- 卡片化容器 ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #fff;
    border-radius: 16px;
    border: 1px solid #e8eef8;
    box-shadow: 0 6px 24px rgba(30,58,138,.06);
    padding: 6px;
}

/* ---------- 指标卡 ---------- */
[data-testid="stMetric"] {
    background: #fff;
    border: 1px solid #e8eef8;
    border-radius: 14px;
    padding: 14px 16px;
    box-shadow: 0 4px 16px rgba(30,58,138,.06);
}
[data-testid="stMetricValue"] { color: #1e40af; font-weight: 700; }
[data-testid="stMetricLabel"] { color: #64748b; }

/* ---------- 表格 ---------- */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #e8eef8;
}

/* ---------- 登录页 ---------- */
.login-wrap { text-align: center; padding: 10px 0 4px; }
.login-logo {
    width: 64px; height: 64px; line-height: 64px; margin: 0 auto 10px;
    border-radius: 18px; font-size: 30px;
    background: linear-gradient(135deg, #2563eb, #1e40af);
    box-shadow: 0 8px 22px rgba(37,99,235,.28);
}
.login-title { font-size: 22px; font-weight: 700; color: #0f172a; margin: 0; }
.login-sub { color: #64748b; font-size: 13px; margin-top: 4px; }

/* ---------- 页头 ---------- */
.hero {
    background: linear-gradient(120deg, #1e3a8a 0%, #2563eb 55%, #3b82f6 100%);
    border-radius: 18px;
    padding: 22px 26px;
    color: #fff;
    margin-bottom: 18px;
    box-shadow: 0 10px 30px rgba(30,64,175,.22);
}
.hero h1 { font-size: 22px; margin: 0 0 6px; font-weight: 700; color: #fff; }
.hero p { margin: 0; opacity: .9; font-size: 13.5px; }

.sec-title {
    font-size: 16px; font-weight: 700; color: #0f172a;
    margin: 6px 0 10px; display: flex; align-items: center; gap: 8px;
}

/* ---------- 聊天 ---------- */
[data-testid="stChatMessage"] {
    background: #fff; border-radius: 14px; border: 1px solid #e8eef8;
    box-shadow: 0 3px 12px rgba(30,58,138,.05);
}
</style>
"""


def inject_css():
    """在 set_page_config 之后调用一次"""
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = ""):
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def section_title(icon: str, text: str):
    st.markdown(f'<div class="sec-title">{icon} {text}</div>', unsafe_allow_html=True)


def login_card_head():
    st.markdown(
        '<div class="login-wrap">'
        '<div class="login-logo">💼</div>'
        '<p class="login-title">财务 AI 助手</p>'
        '<p class="login-sub">请验证身份后进入系统</p>'
        "</div>",
        unsafe_allow_html=True,
    )
