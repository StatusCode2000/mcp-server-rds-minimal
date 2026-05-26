"""
调用 MCP Gateway 的 tools/list 接口，获取所有可用工具列表
"""

import httpx
import json

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

    # 解析 SSE 响应
    content_type = response.headers.get("content-type", "")
    result = None

    if "text/event-stream" in content_type:
        for line in response.text.strip().split("\n"):
            if line.startswith("data:"):
                result = json.loads(line[5:].strip())
                break
    else:
        result = response.json()

    if not result:
        print("无法解析响应")
        return

    # 处理错误
    if "error" in result:
        print(f"错误: {result['error']}")
        return

    # 格式化输出工具列表
    tools = result.get("result", {}).get("tools", [])
    print(f"工具总数: {len(tools)}")
    print()

    rds_tools = [t for t in tools if t["name"].startswith("rds_")]
    das_tools = [t for t in tools if t["name"].startswith("das_")]

    if rds_tools:
        print(f"=== RDS 工具 ({len(rds_tools)} 个) ===")
        for t in rds_tools:
            desc = t.get("description", "")[:60]
            params = list(t.get("inputSchema", {}).get("properties", {}).keys())
            print(f"  {t['name']}")
            print(f"    描述: {desc}")
            print(f"    参数: {', '.join(params[:5])}")
            if len(params) > 5:
                print(f"    ... 还有 {len(params) - 5} 个参数")
        print()

    if das_tools:
        print(f"=== DAS 工具 ({len(das_tools)} 个) ===")
        for t in das_tools[:10]:
            desc = t.get("description", "")[:60]
            params = list(t.get("inputSchema", {}).get("properties", {}).keys())
            print(f"  {t['name']}")
            print(f"    描述: {desc}")
            print(f"    参数: {', '.join(params[:5])}")
            if len(params) > 5:
                print(f"    ... 还有 {len(params) - 5} 个参数")
        if len(das_tools) > 10:
            print(f"  ... 还有 {len(das_tools) - 10} 个 DAS 工具未显示")


if __name__ == "__main__":
    list_tools()