# -*- coding: utf-8 -*-
"""用户管理相关数据库操作测试"""

import db
import permissions


class TestUserManagement:
    def test_create_and_find(self):
        db.delete_user("TESTUSER_A")
        ok, msg = db.create_user("TESTUSER_A", "pass123456", "查看者")
        assert ok, msg
        user = db.find_user("TESTUSER_A")
        assert user is not None
        assert user["role"] == "查看者"
        # 密码必须是哈希，不能是明文
        assert user["password"] != "pass123456"
        assert user["password"].startswith("$2")
        db.delete_user("TESTUSER_A")

    def test_duplicate_user_rejected(self):
        db.delete_user("TESTUSER_B")
        db.create_user("TESTUSER_B", "pass123456", "查看者")
        ok, msg = db.create_user("TESTUSER_B", "other999", "管理员")
        assert not ok
        assert "已存在" in msg
        # 原来的角色不能被覆盖
        assert db.find_user("TESTUSER_B")["role"] == "查看者"
        db.delete_user("TESTUSER_B")

    def test_short_password_rejected(self):
        db.delete_user("TESTUSER_C")
        ok, _ = db.create_user("TESTUSER_C", "123", "查看者")
        assert not ok
        assert db.find_user("TESTUSER_C") is None

    def test_empty_username_rejected(self):
        ok, _ = db.create_user("   ", "pass123456", "查看者")
        assert not ok

    def test_update_role(self):
        db.delete_user("TESTUSER_D")
        db.create_user("TESTUSER_D", "pass123456", "查看者")
        db.update_user_role("TESTUSER_D", "财务专员")
        assert db.find_user("TESTUSER_D")["role"] == "财务专员"
        # 新角色带来的页面权限立即生效
        assert "🧾 批量发票识别台账" in permissions.allowed_pages(
            db.find_user("TESTUSER_D")["role"]
        )
        db.delete_user("TESTUSER_D")

    def test_set_password_changes_login(self):
        db.delete_user("TESTUSER_E")
        db.create_user("TESTUSER_E", "oldpass123", "查看者")
        assert db.verify_login("TESTUSER_E", "oldpass123")[0] is not None
        db.set_password("TESTUSER_E", "newpass456")
        assert db.verify_login("TESTUSER_E", "oldpass123")[0] is None
        assert db.verify_login("TESTUSER_E", "newpass456")[0] is not None
        db.delete_user("TESTUSER_E")

    def test_delete_user(self):
        db.delete_user("TESTUSER_F")
        db.create_user("TESTUSER_F", "pass123456", "查看者")
        assert db.delete_user("TESTUSER_F") is True
        assert db.find_user("TESTUSER_F") is None
        assert db.delete_user("TESTUSER_F") is False

    def test_list_users_no_password_field(self):
        users = db.list_users()
        assert isinstance(users, list)
        for u in users:
            assert "username" in u
            assert "password" not in u, "用户列表不能泄露密码字段"
