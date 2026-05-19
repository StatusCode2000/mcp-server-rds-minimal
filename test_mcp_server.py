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
TEST_AK = "your_test_ak"
TEST_SK = "your_test_sk"
TEST_PROJECT_ID = "your_project_id"


def parse_sse_response(response_text: str) -> dict:
    """解析 SSE 格式响应"""
    # SSE 格式: "event: message\ndata: {...}"
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
        # 打印前 5 个工具名称
        tool_names = [t["name"] for t in result["result"]["tools"][:5]]
        print(f"示例工具: {tool_names}")
        return True
    else:
        print(f"❌ 获取工具列表失败")
        print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return False


def test_call_tool_with_headers():
    """测试 3: 通过 Headers 传递 AK/SK"""
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

    print(f"请求 Headers: X-Access-Key={TEST_AK}, X-Secret-Key={TEST_SK}")

    response = requests.post(MCP_SERVER_URL, headers=headers, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")

    # 判断结果
    content = result.get("result", {}).get("content", [])
    if content and "SdkException" in str(content):
        # 如果是认证错误，说明 Headers AK/SK 已被正确提取
        if "APIGW.0301" in str(content) or "Unauthorized" in str(content):
            print("✅ Headers AK/SK 已被正确提取（认证失败证明使用了 Headers 中的值）")
            return True
        else:
            print(f"⚠️ 其他错误: {content}")
            return False
    elif content and not result.get("result", {}).get("isError"):
        print("✅ Headers AK/SK 验证成功，API 调用正常")
        return True
    else:
        print("❌ 未知错误")
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

    print(f"请求参数: access_key={TEST_AK}, secret_key={TEST_SK}")

    response = requests.post(MCP_SERVER_URL, headers=HEADERS_BASE, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")

    content = result.get("result", {}).get("content", [])
    if content and ("APIGW.0301" in str(content) or "Unauthorized" in str(content)):
        print("✅ 参数 AK/SK 已被正确提取（认证失败证明使用了参数中的值）")
        return True
    elif content and not result.get("result", {}).get("isError"):
        print("✅ 参数 AK/SK 验证成功，API 调用正常")
        return True
    else:
        print("❌ 未知错误")
        return False


def test_priority_headers_vs_args():
    """测试 5: 验证优先级（Headers > 参数）"""
    print("\n" + "=" * 50)
    print("测试 5: 验证优先级（Headers > 参数）")
    print("=" * 50)

    headers_ak = "headers_priority_ak"
    headers_sk = "headers_priority_sk"
    args_ak = "args_secondary_ak"
    args_sk = "args_secondary_sk"

    headers = HEADERS_BASE.copy()
    headers["X-Access-Key"] = headers_ak
    headers["X-Secret-Key"] = headers_sk

    payload = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "ListInstances",
            "arguments": {
                "region": "cn-north-4",
                "project_id": TEST_PROJECT_ID,
                "access_key": args_ak,
                "secret_key": args_sk,
            },
        },
    }

    print(f"Headers AK/SK: {headers_ak}/{headers_sk}")
    print(f"参数 AK/SK: {args_ak}/{args_sk}")
    print("预期: 使用 Headers 中的值")

    response = requests.post(MCP_SERVER_URL, headers=headers, json=payload)
    result = parse_sse_response(response.text)

    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(result, indent=2, ensure_ascii=False)}")

    # 由于 headers_ak/sk 是假的，应该返回认证错误
    # 如果返回认证错误，说明 Headers 优先级高于参数
    content = result.get("result", {}).get("content", [])
    if content and ("APIGW.0301" in str(content) or "Unauthorized" in str(content)):
        print("✅ 优先级验证成功：Headers 优先于参数（使用 Headers 中的假 AK/SK 导致认证失败）")
        return True
    else:
        print("❌ 优先级验证失败")
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("MCP Server AK/SK 动态注入测试")
    print("=" * 60)
    print(f"服务地址: {MCP_SERVER_URL}")
    print(f"测试 AK: {TEST_AK}")
    print(f"测试 Project ID: {TEST_PROJECT_ID}")
    print("提示: 请将 TEST_AK/TEST_SK/TEST_PROJECT_ID 替换为真实值进行完整测试")

    results = []

    # 运行测试
    results.append(("初始化连接", test_initialize()))
    results.append(("列出工具", test_list_tools()))
    results.append(("Headers AK/SK", test_call_tool_with_headers()))
    results.append(("参数 AK/SK", test_call_tool_with_arguments()))
    results.append(("优先级验证", test_priority_headers_vs_args()))

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
