# -*- coding: utf-8 -*-
"""推送功能测试（mock 掉网络）"""

import push


class TestSend:
    def test_empty_text_rejected(self):
        ok, msg = push.send("   ")
        assert not ok
        assert "内容为空" in msg

    def test_success_maps_ok(self, monkeypatch):
        monkeypatch.setattr(push.feishu_notify, "send_text", lambda cid, t: (200, {"code": 0}))
        ok, msg = push.send("测试消息")
        assert ok
        assert "已发送" in msg

    def test_failure_is_not_exception(self, monkeypatch):
        def boom(cid, t):
            raise RuntimeError("网络不通")

        monkeypatch.setattr(push.feishu_notify, "send_text", boom)
        ok, msg = push.send("测试")
        assert not ok
        assert "异常" in msg

    def test_api_error_reported(self, monkeypatch):
        monkeypatch.setattr(
            push.feishu_notify, "send_text",
            lambda cid, t: (200, {"code": 230002, "msg": "bot not in chat"}),
        )
        ok, msg = push.send("测试")
        assert not ok
        assert "bot not in chat" in msg

    def test_long_text_truncated(self, monkeypatch):
        captured = {}

        def fake(cid, t):
            captured["text"] = t
            return 200, {"code": 0}

        monkeypatch.setattr(push.feishu_notify, "send_text", fake)
        push.send("啊" * 5000)
        assert len(captured["text"]) <= push.MAX_LEN
        assert "已截断" in captured["text"]

    def test_chat_id_override(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            push.feishu_notify, "send_text",
            lambda cid, t: (captured.setdefault("cid", cid), {"code": 0})[1],
        )
        push.send("x", chat_id="oc_custom")
        assert captured["cid"] == "oc_custom"


class TestSummary:
    def test_summary_has_counts_and_amount(self):
        text = push.build_summary()
        assert "发票总数" in text
        assert "价税合计" in text
        assert "¥" in text

    def test_summary_custom_title(self):
        text = push.build_summary("我是自定义标题")
        assert text.startswith("我是自定义标题")

    def test_send_summary(self, monkeypatch):
        monkeypatch.setattr(push.feishu_notify, "send_text", lambda cid, t: (200, {"code": 0}))
        ok, _ = push.send_summary()
        assert ok


class TestAlert:
    def test_alert_has_title_and_detail(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            push.feishu_notify, "send_text",
            lambda cid, t: (captured.setdefault("text", t), {"code": 0})[1],
        )
        push.send_alert("同步失败", "详情内容")
        assert "🚨" in captured["text"]
        assert "同步失败" in captured["text"]
        assert "详情内容" in captured["text"]

    def test_alert_without_detail(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            push.feishu_notify, "send_text",
            lambda cid, t: (captured.setdefault("text", t), {"code": 0})[1],
        )
        push.send_alert("只报警")
        assert "只报警" in captured["text"]


class TestAgentPushTool:
    def test_tool_registered(self):
        import agent
        names = [t["function"]["name"] for t in agent.TOOLS]
        assert "push_to_feishu" in names

    def test_summary_kind(self, monkeypatch):
        import agent

        monkeypatch.setattr(push, "send_summary", lambda title=None: (True, "已发送"))
        out = agent.push_to_feishu(None, "summary")
        assert "已推送台账汇总" in out

    def test_text_kind(self, monkeypatch):
        import agent

        monkeypatch.setattr(push, "send", lambda text, chat_id=None: (True, "已发送"))
        out = agent.push_to_feishu("你好", "text")
        assert "已发送" in out