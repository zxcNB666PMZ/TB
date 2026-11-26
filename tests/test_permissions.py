# -*- coding: utf-8 -*-
"""角色权限测试：谁能看到哪些页面"""

import permissions as perm


class TestRolePages:
    def test_admin_sees_everything(self):
        assert perm.allowed_pages("管理员") == perm.all_pages()

    def test_finance_officer_no_user_admin(self):
        pages = perm.allowed_pages("财务专员")
        assert "👥 用户与权限" not in pages
        assert "🧾 批量发票识别台账" in pages
        assert "🗄️ 历史数据查询" in pages
        assert len(pages) == 4

    def test_viewer_only_history(self):
        pages = perm.allowed_pages("查看者")
        assert pages == ["🗄️ 历史数据查询"]

    def test_viewer_cannot_see_ledger(self):
        assert not perm.can_access("查看者", "🧾 批量发票识别台账")
        assert not perm.can_access("查看者", "📈 流水智能分类")
        assert not perm.can_access("查看者", "🤖 AI Agent 智能对话")

    def test_finance_officer_cannot_manage_users(self):
        assert not perm.can_manage_users("财务专员")
        assert not perm.can_manage_users("查看者")
        assert perm.can_manage_users("管理员")


class TestRoleNormalize:
    def test_known_roles_kept(self):
        for r in perm.ALL_ROLES:
            assert perm.normalize_role(r) == r

    def test_legacy_aliases(self):
        assert perm.normalize_role("admin") == "管理员"
        assert perm.normalize_role("财务") == "财务专员"
        assert perm.normalize_role("viewer") == "查看者"

    def test_unknown_role_defaults_to_viewer(self):
        """未知角色必须降级为最低权限，不能提权"""
        assert perm.normalize_role("超级外星人") == "查看者"
        assert perm.normalize_role("") == "查看者"
        assert perm.normalize_role(None) == "查看者"

    def test_unknown_role_cannot_manage_users(self):
        assert not perm.can_manage_users("超级外星人")


class TestNoRoleWithoutPages:
    def test_every_role_has_at_least_one_page(self):
        for r in perm.ALL_ROLES:
            assert perm.allowed_pages(r), f"{r} 没有任何可访问页面"
