"""Read Feishu docx content using application credentials."""
import json
import os
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def api_request(path, payload=None, token=None):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request("https://open.feishu.cn/open-apis/" + path, data=body, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"飞书 HTTP 错误 {exc.code}，请检查应用权限和文档授权。") from None
    except URLError:
        raise RuntimeError("无法连接飞书，请检查网络。") from None
    if result.get("code") != 0:
        raise RuntimeError(f"飞书错误 {result.get('code')}: {result.get('msg', '请求失败')}")
    return result


def get_token():
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not secret:
        raise RuntimeError("请在 MCP 项目 .env 中配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET。")
    return api_request("auth/v3/tenant_access_token/internal", {
        "app_id": app_id, "app_secret": secret
    })["tenant_access_token"]


def read_document(document_url_or_id):
    value = document_url_or_id.strip()
    is_wiki = False
    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".feishu.cn"):
            return "请提供 https:// 开头的飞书文档链接。"
        match = re.fullmatch(r"/(docx|wiki)/([A-Za-z0-9]+)/?", parsed.path)
        if not match:
            return "目前支持 /docx/ 和 /wiki/ 文档链接；电子表格和多维表格需要另行接入。"
        is_wiki = match.group(1) == "wiki"
        value = match.group(2)
    if not re.fullmatch(r"[A-Za-z0-9]+", value):
        return "请提供有效的文档 ID 或 /docx/ 文档链接。"
    try:
        token = get_token()
        if is_wiki:
            node = api_request(f"wiki/v2/spaces/get_node?token={value}", token=token).get("data", {}).get("node", {})
            if node.get("obj_type") != "docx":
                return f"该知识库节点是 {node.get('obj_type', '未知类型')}，目前仅支持文档。"
            value = node.get("obj_token", "")
            if not re.fullmatch(r"[A-Za-z0-9]+", value):
                return "飞书没有返回有效的文档 ID。"
        result = api_request(f"docx/v1/documents/{value}/raw_content", token=token)
        content = result.get("data", {}).get("content", "")
        return json.dumps({"document_id": value, "content": content[:20000],
                           "truncated": len(content) > 20000}, ensure_ascii=False)
    except RuntimeError as exc:
        return str(exc)
