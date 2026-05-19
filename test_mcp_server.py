#!/usr/bin/env python3
"""MCP Server AK/SK 动态注入测试脚本"""

import requests
import json

# 配置
MCP_SERVER_URL = "http://localhost:8907/mcp/"
HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# 测试用的 AK/SK（替换为真实值进行实际测试）
TEST_AK = "YOUR_REAL_ACCESS_KEY"       # 替换为真实 AK
TEST_SK = "YOUR_REAL_SECRET_KEY"       # 替换为真实 SK
TEST_PROJECT_ID = "YOUR_PROJECT_ID"    # 替换为真实项目 ID


def parse_sse_response(response_text: str) -> dict:
    """解析 SSE 格式响应"""
    lines = response_text.strip().split("\n")
    for line in lines:
        if line.startswith("data: "):
            return json.loads(line[6:])
    return {}


def test_initialize():
    """测试 1: 初始化连接"""
    print("\n" + "=" * 50)
    print("测试 1: 初始化连接")
    print("=" * 50)

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }

    response = requests.post(MCP_SERVER_URL, headers=HEADERS_BASE, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")

    if "result" in result and "serverInfo" in result["result"]:
        print("✅ 初始化成功")
        return True
    else:
        print("❌ 初始化失败")
        return False


def test_list_tools():
    """测试 2: 列出可用工具"""
    print("\n" + "=" * 50)
    print("测试 2: 列出可用工具")
    print("=" * 50)

    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    }

    response = requests.post(MCP_SERVER_URL, headers=HEADERS_BASE, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")

    if "result" in result and "tools" in result["result"]:
        tools_count = len(result["result"]["tools"])
        print(f"✅ 成功加载 {tools_count} 个工具")
        tool_names = [t["name"] for t in result["result"]["tools"][:5]]
        print(f"示例工具: {tool_names}")
        return True
    else:
        print(f"❌ 获取工具列表失败")
        print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return False


def test_call_tool_with_headers():
    """测试 3: 通过 Headers 传递 AK/SK 调用 ListInstances"""
    print("\n" + "=" * 50)
    print("测试 3: 通过 Headers 传递 AK/SK")
    print("=" * 50)

    headers = HEADERS_BASE.copy()
    headers["X-Access-Key"] = TEST_AK
    headers["X-Secret-Key"] = TEST_SK

    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "ListInstances",
            "arguments": {
                "region": "cn-north-4",
                "project_id": TEST_PROJECT_ID,
            },
        },
    }

    print(f"请求 Headers: X-Access-Key={TEST_AK[:8]}..., X-Secret-Key={TEST_SK[:8]}...")
    print(f"调用工具: ListInstances")

    response = requests.post(MCP_SERVER_URL, headers=headers, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")

    content = result.get("result", {}).get("content", [])
    is_error = result.get("result", {}).get("isError", False)

    if content:
        # 解析返回内容
        text_content = content[0].get("text", "")
        
        if is_error:
            print(f"❌ 调用失败")
            print(f"错误信息: {text_content}")
            return False
        else:
            print("✅ Headers AK/SK 验证成功，API 调用正常")
            print("\n返回数据:")
            # 格式化输出返回数据
            try:
                data = json.loads(text_content)
                print(json.dumps(data, indent=2, ensure_ascii=False))
                
                # 如果有 instances 列表，显示实例数量
                if "instances" in data:
                    count = len(data["instances"])
                    print(f"\n共查询到 {count} 个实例")
                    # 显示第一个实例的基本信息
                    if count > 0:
                        first = data["instances"][0]
                        print(f"示例实例: ID={first.get('id')}, 名称={first.get('name')}, 状态={first.get('status')}")
            except json.JSONDecodeError:
                print(text_content)
            return True
    else:
        print("❌ 无返回内容")
        print(f"完整响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return False


def test_call_tool_with_arguments():
    """测试 4: 通过请求参数传递 AK/SK"""
    print("\n" + "=" * 50)
    print("测试 4: 通过请求参数传递 AK/SK")
    print("=" * 50)

    payload = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "ListInstances",
            "arguments": {
                "region": "cn-north-4",
                "project_id": TEST_PROJECT_ID,
                "access_key": TEST_AK,
                "secret_key": TEST_SK,
            },
        },
    }

    print(f"请求参数: access_key={TEST_AK[:8]}..., secret_key={TEST_SK[:8]}...")
    print(f"调用工具: ListInstances")

    response = requests.post(MCP_SERVER_URL, headers=HEADERS_BASE, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")

    content = result.get("result", {}).get("content", [])
    is_error = result.get("result", {}).get("isError", False)

    if content:
        text_content = content[0].get("text", "")
        
        if is_error:
            print(f"❌ 调用失败")
            print(f"错误信息: {text_content}")
            return False
        else:
            print("✅ 参数 AK/SK 验证成功，API 调用正常")
            print("\n返回数据:")
            try:
                data = json.loads(text_content)
                print(json.dumps(data, indent=2, ensure_ascii=False))
                
                if "instances" in data:
                    count = len(data["instances"])
                    print(f"\n共查询到 {count} 个实例")
            except json.JSONDecodeError:
                print(text_content)
            return True
    else:
        print("❌ 无返回内容")
        print(f"完整响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return False


def test_priority_headers_over_args():
    """测试 5: 验证优先级（Headers > 参数）- 使用真实 AK/SK"""
    print("\n" + "=" * 50)
    print("测试 5: 验证优先级（Headers > 参数）")
    print("=" * 50)
    print("说明: Headers 传递正确 AK/SK，参数传递错误 AK/SK")
    print("预期: 使用 Headers 中的正确值，调用成功")

    # Headers 用真实的 AK/SK
    headers = HEADERS_BASE.copy()
    headers["X-Access-Key"] = TEST_AK
    headers["X-Secret-Key"] = TEST_SK

    # 参数用错误的 AK/SK
    wrong_ak = "wrong_ak_12345"
    wrong_sk = "wrong_sk_12345"

    payload = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "ListInstances",
            "arguments": {
                "region": "cn-north-4",
                "project_id": TEST_PROJECT_ID,
                "access_key": wrong_ak,  # 错误值
                "secret_key": wrong_sk,  # 错误值
            },
        },
    }

    print(f"Headers AK/SK: {TEST_AK[:8]}.../{TEST_SK[:8]}... (正确)")
    print(f"参数 AK/SK: {wrong_ak}/{wrong_sk} (错误)")

    response = requests.post(MCP_SERVER_URL, headers=headers, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")

    content = result.get("result", {}).get("content", [])
    is_error = result.get("result", {}).get("isError", False)

    if content:
        text_content = content[0].get("text", "")
        
        if is_error:
            # 如果失败，检查是否是因为使用了参数中的错误值
            if "Unauthorized" in text_content or "APIGW.0301" in text_content:
                print("❌ 优先级错误：使用了参数中的错误 AK/SK")
                print(f"错误信息: {text_content}")
                return False
            else:
                print(f"❌ 其他错误: {text_content}")
                return False
        else:
            print("✅ 优先级验证成功：Headers 优先于参数")
            print("   使用了 Headers 中的正确 AK/SK，调用成功")
            print("\n返回数据:")
            try:
                data = json.loads(text_content)
                print(json.dumps(data, indent=2, ensure_ascii=False))
                
                if "instances" in data:
                    count = len(data["instances"])
                    print(f"\n共查询到 {count} 个实例")
            except json.JSONDecodeError:
                print(text_content)
            return True
    else:
        print("❌ 无返回内容")
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("MCP Server AK/SK 动态注入测试")
    print("=" * 60)
    print(f"服务地址: {MCP_SERVER_URL}")
    print(f"测试 AK: {TEST_AK[:8]}...")
    print(f"测试 Project ID: {TEST_PROJECT_ID}")

    results = []

    # 运行测试
    results.append(("初始化连接", test_initialize()))
    results.append(("列出工具", test_list_tools()))
    results.append(("Headers AK/SK", test_call_tool_with_headers()))
    results.append(("参数 AK/SK", test_call_tool_with_arguments()))
    results.append(("优先级验证", test_priority_headers_over_args()))

    # 打印汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    print(f"\n总计: {passed} 通过, {failed} 失败")

    return passed, failed


if __name__ == "__main__":
    run_all_tests()
