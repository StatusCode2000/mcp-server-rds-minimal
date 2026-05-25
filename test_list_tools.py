"""
调用 MCP Gateway 的 tools/list 接口，获取所有可用工具列表
"""
from pprint import pprint

import httpx

MCP_URL = "http://localhost:8907/mcp/"


def list_tools():
    """发送 tools/list JSON-RPC 请求"""

    request_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    response = httpx.post(
        MCP_URL,
        json=request_body,
        headers=headers,
        timeout=30.0
    )

    print(f"状态码: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type')}")
    print()
    print("原始响应:")
    pprint(response.text)


if __name__ == "__main__":
    list_tools()