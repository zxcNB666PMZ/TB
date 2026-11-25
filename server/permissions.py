# -*- coding: utf-8 -*-
"""
页面权限控制：不同角色只能看到/进入不同的功能页。

角色说明：
  管理员   —— 全部页面，含用户与权限管理
  财务专员 —— 日常业务：Agent 对话、发票识别、历史查询、流水分类
  查看者   —— 只读：只能看历史数据看板
"""

# 页面 → 允许访问的角色
PAGE_PERMISSIONS = {
    "🤖 AI Agent 智能对话": {"管理员", "财务专员"},
    "🧾 批量发票识别台账": {"管理员", "财务专员"},
    "🗄️ 历史数据查询": {"管理员", "财务专员", "查看者"},
    "📈 流水智能分类": {"管理员", "财务专员"},
    "👥 用户与权限": {"管理员"},
}

# 角色显示顺序（用于下拉框）
ALL_ROLES = ["管理员", "财务专员", "查看者"]

# 新建用户时的默认角色
DEFAULT_ROLE = "查看者"


def all_pages():
    return list(PAGE_PERMISSIONS.keys())


def normalize_role(role):
    """把历史/异常角色名归一化，未知角色按最保守的'查看者'处理"""
    role = (role or "").strip()
    if role in ALL_ROLES:
        return role
    # 兼容旧数据里的写法
    aliases = {
        "admin": "管理员",
        "administrator": "管理员",
        "超级管理员": "管理员",
        "财务": "财务专员",
        "财务专员": "财务专员",
        "finance": "财务专员",
        "只读": "查看者",
        "查看": "查看者",
        "viewer": "查看者",
        "普通用户": "查看者",
        "未知角色": "查看者",
    }
    return aliases.get(role, DEFAULT_ROLE)


def allowed_pages(role):
    """该角色能看到的页面列表（按 PAGE_PERMISSIONS 的声明顺序）"""
    role = normalize_role(role)
    return [page for page, roles in PAGE_PERMISSIONS.items() if role in roles]


def can_access(role, page):
    role = normalize_role(role)
    return role in PAGE_PERMISSIONS.get(page, set())


def can_manage_users(role):
    return can_access(role, "👥 用户与权限")


def role_summary():
    """用于界面展示：每个角色能看哪些页面"""
    lines = []
    for role in ALL_ROLES:
        pages = [p.split(" ", 1)[-1] for p in allowed_pages(role)]
        lines.append((role, pages))
    return lines