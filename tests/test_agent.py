# -*- coding: utf-8 -*-
"""共享 Agent 与对话记忆测试（不联网）"""

import db
import agent


KEY = "test:agent"


class TestTools:
    def test_overview_returns_text(self):
        out = agent.invoice_overview()
        assert "发票" in out

    def test_query_unknown_company(self):
        out = agent.query_invoice_db("绝不存在的公司XYZ")
        assert "没有找到" in out

    def test_reimbursement_over_limit(self, clean_invoices):
        db.upsert_invoices([
            {
                "发票号码": "TEST9001",
                "开票日期": "2026-11-01",
                "购买方名称": "测试科技有限公司",
                "销售方名称": "滴滴出行科技有限公司",
                "价税合计": 6000,
            }
        ])
        out = agent.reimbursement_check("滴滴", 5000)
        assert "超额" in out
        assert "0.00 元" in out

    def test_reimbursement_remaining(self, clean_invoices):
        db.upsert_invoices([
            {
                "发票号码": "TEST9002",
                "开票日期": "2026-11-01",
                "购买方名称": "测试科技有限公司",
                "销售方名称": "滴滴出行科技有限公司",
                "价税合计": 1000,
            }
        ])
        out = agent.reimbursement_check("滴滴", 5000)
        assert "4000.00" in out

    def test_reimbursement_bad_limit(self):
        out = agent.reimbursement_check("滴滴", "五千")
        assert "不是有效数字" in out


class TestCalculator:
    def test_simple_add(self):
        assert "= 300" in agent.calculator("100+200")

    def test_float(self):
        assert "7328.91" in agent.calculator("12671.09-5342.18")

    def test_parentheses(self):
        assert "= 14" in agent.calculator("(2+5)*2")

    def test_chinese_multiply_symbol(self):
        assert "= 12" in agent.calculator("3×4")

    def test_division_by_zero(self):
        out = agent.calculator("1/0")
        assert "失败" in out

    def test_rejects_code_injection(self):
        """绝对不能执行任意代码"""
        out = agent.calculator("__import__('os').system('rm -rf /')")
        assert "失败" in out

    def test_rejects_names(self):
        assert "失败" in agent.calculator("abc + 1")


class TestChatMemory:
    def test_save_and_load(self):
        db.clear_chat(KEY)
        db.save_chat(KEY, "user", "你好", channel="web")
        db.save_chat(KEY, "assistant", "你好呀", channel="web")
        history = db.load_chat(KEY)
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["content"] == "你好"
        db.clear_chat(KEY)

    def test_clear(self):
        db.clear_chat(KEY)
        db.save_chat(KEY, "user", "x")
        assert db.clear_chat(KEY) >= 1
        assert db.load_chat(KEY) == []

    def test_history_is_isolated_by_key(self):
        db.clear_chat("test:a")
        db.clear_chat("test:b")
        db.save_chat("test:a", "user", "只属于A")
        db.save_chat("test:b", "user", "只属于B")
        assert db.load_chat("test:a")[0]["content"] == "只属于A"
        assert db.load_chat("test:b")[0]["content"] == "只属于B"
        db.clear_chat("test:a")
        db.clear_chat("test:b")

    def test_load_limits(self):
        db.clear_chat(KEY)
        for i in range(30):
            db.save_chat(KEY, "user", f"消息{i}")
        assert len(db.load_chat(KEY, limit=10)) == 10
        db.clear_chat(KEY)

    def test_chat_stats(self):
        stats = db.chat_stats()
        assert "conversations" in stats
        assert "messages" in stats


class TestFeishuBinding:
    def test_bind_and_find(self):
        db.delete_user("TESTBIND")
        db.create_user("TESTBIND", "pass123456", "查看者")
        ok, msg = db.bind_feishu("TESTBIND", "ou_test123456")
        assert ok, msg
        assert db.find_username_by_open_id("ou_test123456") == "TESTBIND"
        db.unbind_feishu("TESTBIND")
        assert db.find_username_by_open_id("ou_test123456") is None
        db.delete_user("TESTBIND")

    def test_one_feishu_one_account(self):
        db.delete_user("TESTBIND1")
        db.delete_user("TESTBIND2")
        db.create_user("TESTBIND1", "pass123456", "查看者")
        db.create_user("TESTBIND2", "pass123456", "查看者")
        db.bind_feishu("TESTBIND1", "ou_dup999")
        ok, msg = db.bind_feishu("TESTBIND2", "ou_dup999")
        assert not ok, "同一个飞书号不能绑两个账号"
        assert "已经绑定" in msg
        db.unbind_feishu("TESTBIND1")
        db.delete_user("TESTBIND1")
        db.delete_user("TESTBIND2")

    def test_bind_unknown_user(self):
        ok, _ = db.bind_feishu("根本不存在的用户", "ou_x")
        assert not ok


class TestBitableHelpers:
    def test_field_mapping(self):
        import bitable
        fields = bitable._to_bitable_fields({
            "发票号码": "123",
            "开票日期": "2026-11-20",
            "购买方名称": "甲公司",
            "销售方名称": "乙公司",
            "价税合计": "1234.56",
            "发票类型": "普票",
            "文件名": "a.pdf",
        })
        assert fields["发票号码"] == "123"
        assert fields["价税合计"] == 1234.56
        assert isinstance(fields["价税合计"], float)
        # 日期字段必须是毫秒时间戳（飞书不接受日期字符串）
        assert isinstance(fields["开票日期"], int)
        assert fields["开票日期"] == 1795104000000

    def test_date_conversion(self):
        import bitable
        assert bitable._date_to_ms("2026-11-20") == 1795104000000
        assert bitable._date_to_ms("2026-11-20 13:45:00") == 1795104000000
        assert bitable._date_to_ms("不是日期") is None
        assert bitable._date_to_ms("") is None

    def test_field_mapping_skips_empty(self):
        import bitable
        fields = bitable._to_bitable_fields({"发票号码": "123", "销售方名称": None, "价税合计": ""})
        assert "销售方名称" not in fields
        assert "价税合计" not in fields

    def test_not_configured(self, monkeypatch):
        """不依赖 .env：显式清空配置再判断"""
        import bitable

        monkeypatch.delenv("FEISHU_BITABLE_APP_TOKEN", raising=False)
        monkeypatch.delenv("FEISHU_BITABLE_TABLE_ID", raising=False)
        monkeypatch.delenv("FEISHU_APP_ID", raising=False)
        monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
        assert not bitable.is_configured()
        assert "未配置" in bitable.describe()