# -*- coding: utf-8 -*-
"""页面冒烟测试：确认登录页能渲染、登录逻辑正确（跑在测试库上）"""

import os
import sys

import pytest

import db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(BASE_DIR, "app.py")

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

TEST_USER = "smoke_user"
TEST_PASS = "smoke_pass_2026"


@pytest.fixture(scope="module", autouse=True)
def seed_user():
    """在测试库里造一个临时用户，用完删掉"""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username = %s", (TEST_USER,))
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (TEST_USER, db.hash_password(TEST_PASS), "测试角色"),
        )
    yield
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username = %s", (TEST_USER,))


def _new_app():
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    return at


def test_login_page_renders():
    at = _new_app()
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.text_input) == 2, "登录页应有用户名和密码两个输入框"
    assert len(at.button) >= 1
    assert not at.session_state.get("logged_in")


def test_wrong_password_rejected():
    at = _new_app()
    at.text_input[0].set_value(TEST_USER)
    at.text_input[1].set_value("wrong-password")
    at.button[0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert not at.session_state.get("logged_in")
    assert any("错误" in e.value for e in at.error)


def test_correct_password_logs_in():
    at = _new_app()
    at.text_input[0].set_value(TEST_USER)
    at.text_input[1].set_value(TEST_PASS)
    at.button[0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state.get("logged_in") is True
    assert at.session_state.get("current_user") == TEST_USER


def test_logged_in_pages_render():
    """管理员能进四个功能页，且都不抛异常"""
    modes = [
        "🤖 AI Agent 智能对话",
        "🧾 批量发票识别台账",
        "🗄️ 历史数据查询",
        "📈 流水智能分类",
    ]
    for mode in modes:
        at = _new_app()
        at.session_state["logged_in"] = True
        at.session_state["current_user"] = TEST_USER
        at.session_state["current_role"] = "管理员"   # 管理员才看得到全部页面
        at.run()
        if len(at.radio) > 0:
            at.radio[0].set_value(mode).run()
        assert not at.exception, f"{mode} 渲染异常: {[e.message for e in at.exception]}"
        assert not at.error, f"{mode} 报错: {[e.value for e in at.error]}"


def _sidebar_pages(role):
    at = _new_app()
    at.session_state["logged_in"] = True
    at.session_state["current_user"] = TEST_USER
    at.session_state["current_role"] = role
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return list(at.radio[0].options) if len(at.radio) > 0 else []


def test_viewer_sees_only_history_page():
    """查看者只能看到历史数据查询一个页面"""
    pages = _sidebar_pages("查看者")
    assert pages == ["🗄️ 历史数据查询"], pages


def test_finance_officer_cannot_see_user_admin():
    pages = _sidebar_pages("财务专员")
    assert len(pages) == 4
    assert "👥 用户与权限" not in pages
    assert "🧾 批量发票识别台账" in pages


def test_admin_sees_user_admin_page():
    pages = _sidebar_pages("管理员")
    assert "👥 用户与权限" in pages
    assert len(pages) == 5


def test_unknown_role_degrades_to_viewer():
    """角色名写错时要降级成最低权限，不能提权"""
    pages = _sidebar_pages("不存在的角色XYZ")
    assert pages == ["🗄️ 历史数据查询"], pages


def test_admin_user_page_renders():
    at = _new_app()
    at.session_state["logged_in"] = True
    at.session_state["current_user"] = TEST_USER
    at.session_state["current_role"] = "管理员"
    at.run()
    at.radio[0].set_value("👥 用户与权限").run()
    assert not at.exception, [e.message for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert len(at.dataframe) >= 2, "应显示角色说明表和用户列表"
