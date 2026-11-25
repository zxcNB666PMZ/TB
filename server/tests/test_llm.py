# -*- coding: utf-8 -*-
"""大模型调用层测试（不联网，只测配置解析和返回结构转换）"""

import os

import pytest

import llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("LLM_PROVIDER", "LLM_MODEL", "DEEPSEEK_API_KEY", "ZHIPU_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    llm.reset_client()
    yield
    llm.reset_client()


class TestProviderSelection:
    def test_explicit_deepseek(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        assert llm.provider() == "deepseek"

    def test_explicit_zhipu(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "zhipu")
        assert llm.provider() == "zhipu"

    def test_auto_detect_deepseek_by_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert llm.provider() == "deepseek"

    def test_auto_detect_zhipu_when_only_zhipu_key(self, monkeypatch):
        monkeypatch.setenv("ZHIPU_API_KEY", "zk-test")
        assert llm.provider() == "zhipu"

    def test_invalid_provider_falls_back(self, monkeypatch):
        """写错 provider 不能崩，按 key 自动判断"""
        monkeypatch.setenv("LLM_PROVIDER", "openai_gpt_9")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert llm.provider() == "deepseek"


class TestModelName:
    def test_deepseek_default_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        assert llm.model_name() == "deepseek-chat"

    def test_zhipu_default_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "zhipu")
        assert llm.model_name() == "glm-4-flash"

    def test_explicit_model_override(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")
        assert llm.model_name() == "deepseek-reasoner"


class TestConfigured:
    def test_not_configured_without_key(self):
        assert not llm.is_configured()

    def test_configured_with_deepseek_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert llm.is_configured()

    def test_configured_with_zhipu_key(self, monkeypatch):
        monkeypatch.setenv("ZHIPU_API_KEY", "zk-test")
        assert llm.is_configured()

    def test_chat_without_key_raises_clear_error(self):
        with pytest.raises(llm.LLMError) as exc:
            llm.chat([{"role": "user", "content": "hi"}])
        assert "API Key" in str(exc.value)

    def test_describe_shows_provider_and_model(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert llm.describe() == "deepseek / deepseek-chat"


class TestParseJsonReply:
    def test_plain_json(self):
        assert llm.parse_json_reply('{"a": 1}') == {"a": 1}

    def test_json_in_code_fence(self):
        assert llm.parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_noise_prefix(self):
        assert llm.parse_json_reply('好的，结果如下：\n{"a": 1}') == {"a": 1}

    def test_invalid_returns_default(self):
        assert llm.parse_json_reply("完全不是 JSON") == {}
        assert llm.parse_json_reply("", default={"x": 1}) == {"x": 1}

    def test_nested_json(self):
        text = '```json\n{"category": {"午餐": "餐饮", "打车": "交通"}}\n```'
        assert llm.parse_json_reply(text) == {"category": {"午餐": "餐饮", "打车": "交通"}}


class TestReplyStructure:
    def test_tool_call_holds_fields(self):
        tc = llm.ToolCall(id="call_1", name="query_invoice_db", arguments='{"supplier_name": "滴滴"}')
        assert tc.id == "call_1"
        assert tc.name == "query_invoice_db"
        assert '"滴滴"' in tc.arguments

    def test_reply_defaults(self):
        reply = llm.LLMReply()
        assert reply.content == ""
        assert reply.tool_calls == []
