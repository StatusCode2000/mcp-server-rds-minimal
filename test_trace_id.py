"""
测试 trace_id 机制：
1. 传入自定义 X-Trace-Id，验证 trace_id 和 hw_trace_id 都在响应中
2. 不传入 X-Trace-Id，验证自动生成 UUID trace_id
3. 错误情况，验证 trace_id 返回在错误文本中
"""
import httpx
import json

MCP_URL = "http://localhost:8907/mcp/"
TEST_AK = "HPUAXAUB9NJ4SOFPP737"
TEST_SK = "DPJ4n3JPb3SCkSEjSyRAhcdeFQ299tPByDdCmIFO"
TEST_PROJECT_ID = "101b890ffd5f439db704618744b52abe"

HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def call_tool(name, arguments, extra_headers=None):
    """调用工具并返回解析后的响应"""
    headers = HEADERS_BASE.copy()
    headers["X-Access-Key"] = TEST_AK
    headers["X-Secret-Key"] = TEST_SK
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }

    response = httpx.post(MCP_URL, json=payload, headers=headers, timeout=30.0)

    for line in response.text.strip().split("\n"):
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


def test_with_trace_id():
    """测试1: 传入自定义 trace_id"""
    print("=" * 60)
    print("测试1: 传入自定义 X-Trace-Id")
    print("=" * 60)

    custom_id = "my-custom-trace-20260526"
    result = call_tool(
        "rds_ListInstances",
        {"region": "cn-east-2", "project_id": TEST_PROJECT_ID},
        extra_headers={"X-Trace-Id": custom_id},
    )

    content = result.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "")
        try:
            data = json.loads(text)
            our_trace = data.get('trace_id', '无')
            hw_trace = data.get('hw_trace_id', '无')
            print(f"  传入的 X-Trace-Id:     {custom_id}")
            print(f"  响应 trace_id:         {our_trace}")
            print(f"  响应 hw_trace_id:      {hw_trace}")
            print(f"  trace_id 正确:         {our_trace == custom_id}")
        except json.JSONDecodeError:
            print(f"  响应内容: {text[:200]}")
    print()


def test_without_trace_id():
    """测试2: 不传入 trace_id，自动生成 UUID"""
    print("=" * 60)
    print("测试2: 不传入 X-Trace-Id，验证自动生成")
    print("=" * 60)

    result = call_tool(
        "rds_ListInstances",
        {"region": "cn-east-2", "project_id": TEST_PROJECT_ID},
    )

    content = result.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "")
        try:
            data = json.loads(text)
            our_trace = data.get('trace_id', '无')
            hw_trace = data.get('hw_trace_id', '无')
            print(f"  自动生成的 trace_id:   {our_trace}")
            print(f"  华为云 hw_trace_id:    {hw_trace}")
            print(f"  trace_id 是 UUID 格式: {our_trace != '无' and '-' in our_trace}")
        except json.JSONDecodeError:
            print(f"  响应内容: {text[:200]}")
    print()


def test_error_with_trace_id():
    """测试3: 错误情况下 trace_id 是否返回"""
    print("=" * 60)
    print("测试3: 错误情况（不传 AK/SK）trace_id 是否返回")
    print("=" * 60)

    headers = HEADERS_BASE.copy()
    headers["X-Trace-Id"] = "error-test-001"
    # 不传 AK/SK

    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "rds_ListInstances",
            "arguments": {"region": "cn-east-2", "project_id": TEST_PROJECT_ID},
        },
    }

    response = httpx.post(MCP_URL, json=payload, headers=headers, timeout=30.0)

    for line in response.text.strip().split("\n"):
        if line.startswith("data:"):
            result = json.loads(line[5:].strip())
            # MCP 协议中 ToolError 在 result.content[0].text，不在 result.error
            mcp_result = result.get("result", {})
            is_error = mcp_result.get("isError", False)
            content = mcp_result.get("content", [])
            if content:
                text = content[0].get("text", "")
                print(f"  isError: {is_error}")
                print(f"  错误内容: {text}")
                print(f"  trace_id 'error-test-001' 是否在错误内容中: {'error-test-001' in text}")
            else:
                # 兜底：也可能走 JSON-RPC error 字段
                error = result.get("error", {})
                print(f"  JSON-RPC error: {error}")
            break
    print()


if __name__ == "__main__":
    test_with_trace_id()
    test_without_trace_id()
    test_error_with_trace_id()