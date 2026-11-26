from mcp.server.mcpserver import MCPServer
from supabase import create_client, Client
import os
from dotenv import load_dotenv

# 加载你本地的密钥
load_dotenv()

# 1. 创建 MCP 服务实例
mcp = MCPServer("Finance-DB-MCP")

# 2. 连接 Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# 3. 定义工具
@mcp.tool()
def query_invoice_db(supplier_name: str) -> str:
    """去 Supabase 云数据库查询指定供应商的发票总金额"""
    print(f"🔍 MCP 服务收到请求，正在查询: {supplier_name}")
    try:
        response = supabase.table("invoices").select("价税合计").or_(
            f"购买方名称.like.%{supplier_name}%,销售方名称.like.%{supplier_name}%"
        ).execute()
        
        if not response.data:
            return f"数据库中没有找到关于 '{supplier_name}' 的发票记录。"
        
        total = sum(float(item["价税合计"]) for item in response.data if item["价税合计"])
        return f"查询到 '{supplier_name}' 的发票总金额为：{total} 元。"
    except Exception as e:
        return f"查询出错: {e}"

if __name__ == "__main__":
    # 以 SSE 模式启动
    print("🚀 MCP 服务器正在启动，监听端口 8000...")
    mcp.run(transport="sse")
