# -*- coding: utf-8 -*-
"""
统一的大模型调用层：网页和飞书机器人共用。

默认走 DeepSeek（OpenAI 兼容接口），也保留智谱 GLM 作为备用。
切换只看 .env：

    LLM_PROVIDER=deepseek        # deepseek / zhipu
    LLM_MODEL=deepseek-chat      # 可选，留空用各家的默认值
    DEEPSEEK_API_KEY=sk-xxx
    ZHIPU_API_KEY=xxx            # 仅当 provider=zhipu 时需要

对外只暴露一个函数：chat()，返回统一结构的 LLMReply。
"""

import json
import os

# 自己加载同目录的 .env（踩过的坑：脚本单独运行时读不到配置）
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "zhipu": "glm-4-flash",
}

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


class ToolCall:
    __slots__ = ("id", "name", "arguments")

    def __init__(self, id, name, arguments):
        self.id = id
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f"ToolCall({self.name}, {self.arguments})"


class LLMReply:
    """统一的返回结构：不管是哪家的模型，都长这样"""

    __slots__ = ("content", "tool_calls")

    def __init__(self, content="", tool_calls=None):
        self.content = content or ""
        self.tool_calls = tool_calls or []

    def __repr__(self):
        return f"LLMReply(content={self.content[:40]!r}, tools={[t.name for t in self.tool_calls]})"


class LLMError(RuntimeError):
    pass


def provider():
    """当前使用哪家：显式配置优先，否则看谁的 key 存在"""
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit in ("deepseek", "zhipu"):
        return explicit
    if (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        return "deepseek"
    if (os.getenv("ZHIPU_API_KEY") or "").strip():
        return "zhipu"
    return "deepseek"


def fallback_provider():
    """
    备用模型：主模型不可用（余额不足/网络故障/限流）时自动顶上。
    两个 key 都配了就默认开启；想关掉设 LLM_FALLBACK=0。
    """
    if (os.getenv("LLM_FALLBACK") or "1").strip() in ("0", "false", "no"):
        return None
    primary = provider()
    other = "zhipu" if primary == "deepseek" else "deepseek"
    if other == "deepseek" and (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        return other
    if other == "zhipu" and (os.getenv("ZHIPU_API_KEY") or "").strip():
        return other
    return None


def model_name(p=None):
    explicit = (os.getenv("LLM_MODEL") or "").strip()
    if explicit and (p is None or p == provider()):
        return explicit
    return DEFAULT_MODELS[p or provider()]


def _api_key(p=None):
    p = p or provider()
    if p == "deepseek":
        return (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    return (os.getenv("ZHIPU_API_KEY") or "").strip()


def is_configured():
    return bool(_api_key())


# 最近一次调用的实际使用情况，供界面展示
_last_used_provider = None
_last_fallback_reason = None


def last_used():
    """返回 (实际使用的模型商, 降级原因 或 None)"""
    return _last_used_provider or provider(), _last_fallback_reason


def describe():
    """给界面显示的一行说明"""
    return f"{provider()} / {model_name()}"


def status_text():
    """界面上展示的状态：正常/已降级"""
    used, reason = last_used()
    if reason:
        return f"⚠️ {provider()} 不可用（{reason}），本次使用 {used} / {model_name(used)}"
    return f"✅ {provider()} / {model_name()}"


_http_client = None
_sdk_clients = {}


def _build_client(p=None):
    """懒加载：只有真正要调用时才建连接，单元测试不会碰网络"""
    global _http_client
    p = p or provider()
    key = _api_key(p)

    if not key:
        label = "DEEPSEEK_API_KEY" if p == "deepseek" else "ZHIPU_API_KEY"
        raise LLMError(f"缺少 API Key：请在 .env 里配置 {label}")

    if _sdk_clients.get(p) is not None:
        return _sdk_clients[p]

    if p == "deepseek":
        try:
            import httpx
            from openai import OpenAI
        except ImportError as exc:
            raise LLMError(
                "缺少 openai 依赖，请在服务器执行：.venv/bin/pip install openai"
            ) from exc
        # DeepSeek 的接口兼容 OpenAI 协议；超时放宽，避免网络抖动就报错
        _http_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
        _sdk_clients[p] = OpenAI(
            api_key=key, base_url=DEEPSEEK_BASE_URL, http_client=_http_client, max_retries=1
        )
    else:
        try:
            from zhipuai import ZhipuAI
        except ImportError as exc:
            raise LLMError("缺少 zhipuai 依赖") from exc
        _sdk_clients[p] = ZhipuAI(api_key=key)

    return _sdk_clients[p]


def reset_client():
    """测试或换 key 后强制重建连接"""
    global _http_client
    _sdk_clients.clear()
    _http_client = None


def _friendly_error(exc):
    """把各家五花八门的报错翻译成看得懂的一句话"""
    text = str(exc)
    low = text.lower()
    if "insufficient balance" in low or "402" in low:
        return "账户余额不足"
    if "401" in low or "invalid api key" in low or "authentication" in low:
        return "API Key 无效"
    if "429" in low or "rate limit" in low:
        return "请求太频繁被限流"
    if "timeout" in low or "timed out" in low:
        return "请求超时"
    if "connect" in low:
        return "网络连接失败"
    return text[:80]


def _call_one(p, messages, tools, temperature, tool_choice, max_tokens):
    client = _build_client(p)
    kwargs = {"model": model_name(p), "messages": messages, "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    resp = client.chat.completions.create(**kwargs)

    try:
        message = resp.choices[0].message
    except (AttributeError, IndexError) as exc:
        raise LLMError(f"{p} 返回结构异常：{resp}") from exc

    content = getattr(message, "content", "") or ""
    raw_calls = getattr(message, "tool_calls", None) or []

    calls = []
    for tc in raw_calls:
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        calls.append(
            ToolCall(
                id=getattr(tc, "id", "") or "",
                name=getattr(fn, "name", "") or "",
                arguments=getattr(fn, "arguments", "") or "{}",
            )
        )

    return LLMReply(content=content, tool_calls=calls)


def chat(messages, tools=None, temperature=0.3, tool_choice=None, max_tokens=None):
    """
    统一调用入口。主模型失败时自动切备用模型（可用 LLM_FALLBACK=0 关闭）。

    messages: [{"role": "system"/"user"/"assistant"/"tool", ...}]
    tools:    OpenAI 格式的工具定义列表（可选）
    返回：LLMReply(content=..., tool_calls=[ToolCall...])
    """
    global _last_used_provider, _last_fallback_reason

    primary = provider()
    candidates = [primary]
    fb = fallback_provider()
    if fb:
        candidates.append(fb)

    last_error = None
    for idx, p in enumerate(candidates):
        if not _api_key(p):
            continue
        try:
            reply = _call_one(p, messages, tools, temperature, tool_choice, max_tokens)
            _last_used_provider = p
            _last_fallback_reason = None if idx == 0 else f"{primary} {_friendly_error(last_error)}"
            return reply
        except LLMError:
            raise
        except Exception as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise LLMError(f"{primary} 调用失败：{last_error}") from last_error
    raise LLMError(f"缺少 API Key：请在 .env 里配置 {'DEEPSEEK_API_KEY' if primary == 'deepseek' else 'ZHIPU_API_KEY'}")


def chat_text(prompt, system=None, temperature=0.3, max_tokens=None):
    """只要文字结果的便捷方法（发票识别、流水分类用）"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    reply = chat(messages, temperature=temperature, max_tokens=max_tokens)
    return reply.content


def parse_json_reply(text, default=None):
    """
    模型返回的 JSON 有时会包 ```json ```，这里统一清洗后解析。
    解析失败返回 default（默认空字典），不抛异常打断业务流程。
    """
    import re

    if not text:
        return {} if default is None else default

    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # 兜底：从文本里抠出第一个 {...}
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {} if default is None else default