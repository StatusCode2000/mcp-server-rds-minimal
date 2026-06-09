"""test_server_deep.py — MCPServer call_tool 深度 mock 测试
覆盖 call_tool 的完整业务路径：AK/SK 优先级、华为云 API 调用、
trace_id 注入、ClientRequestException、通用 Exception
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import contextvars

from assets.utils.server import MCPServer, _request_headers, _trace_id
from mcp.server.fastmcp.exceptions import ToolError
from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
from mcp.types import CallToolRequest


# ============================================================
# Helper: 构造 CallToolRequest 并调用注册的 handler
# ============================================================

async def invoke_call_tool(server, name, arguments):
    """通过 MCP 注册的 handler 调用 call_tool

    handler 是 lowlevel Server 注册的包装函数，
    它接收 CallToolRequest，提取 name/arguments，
    调用原始 call_tool 函数，返回 CallToolResult。
    ToolError 被 handler 捕获 → CallToolResult(isError=True, content=[TextContent])
    """
    req = MagicMock()
    req.params = MagicMock()
    req.params.name = name
    req.params.arguments = arguments or {}

    handler = server.server.request_handlers.get(CallToolRequest)
    return await handler(req)


# ============================================================
# Fixtures
# ============================================================

def _make_mock_tool(name="ListInstances"):
    tool = MagicMock()
    tool.name = name
    tool.description = f"查询{name}"
    tool.inputSchema = {
        "properties": {
            "project_id": {"in": "path", "type": "string"},
            "region": {"in": "query", "type": "string"},
        },
        "required": ["project_id"],
    }
    return tool


def _make_mock_openapi():
    return {
        "info": {"title": "RDS", "x-host": "rds.cn-east-2.myhuaweicloud.com"},
        "paths": {
            "/ListInstances": {
                "x-method": "GET",
                "x-url": "{endpoint}/v3/{project_id}/instances",
                "get": {
                    "operationId": "ListInstances",
                    "parameters": [],
                    "responses": {"200": {"description": "OK"}},
                },
            },
        },
    }


@pytest.fixture
def mcp_server():
    """创建完整初始化的 MCPServer 实例（mock 文件加载，真实注册 handler）"""
    with patch("assets.utils.server.load_config") as mock_load_config, \
         patch("assets.utils.server.load_openapi") as mock_load_openapi, \
         patch("assets.utils.server.OpenAPIToToolsConverter") as mock_converter_cls:

        from assets.utils.model import MCPConfig
        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http",
                                ak="config_ak", sk="config_sk")
        mock_load_config.return_value = mock_config

        mock_load_openapi.return_value = _make_mock_openapi()

        mock_tool = _make_mock_tool()
        mock_converter = MagicMock()
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))

    return server


@pytest.fixture
def mock_response():
    resp = MagicMock()
    resp.content = b'{"instances": [{"id": "inst-001", "name": "test", "status": "ACTIVE"}]}'
    resp.json.return_value = {"instances": [{"id": "inst-001", "name": "test", "status": "ACTIVE"}]}
    resp.headers = {"X-TRACE-ID": "hw-uuid-456"}
    return resp


@pytest.fixture(autouse=True)
def reset_contextvars():
    _request_headers.set({})
    _trace_id.set("")
    yield
    _request_headers.set({})
    _trace_id.set("")


# ============================================================
# 成功路径
# ============================================================

class TestCallToolSuccess:
    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_success_with_trace_id_and_hw_trace_id(self, mock_build_http, mock_create_client, mcp_server, mock_response):
        _trace_id.set("my-trace-123")
        _request_headers.set({"x-access-key": "ak123", "x-secret-key": "sk123"})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = mock_response
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/v3/{project_id}/instances",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc123"})
        data = json.loads(result.root.content[0].text)
        assert data["trace_id"] == "my-trace-123"
        assert data["hw_trace_id"] == "hw-uuid-456"

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_success_no_hw_trace_id(self, mock_build_http, mock_create_client, mcp_server):
        _trace_id.set("auto-uuid-001")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        resp = MagicMock()
        resp.content = b'{"instances": []}'
        resp.json.return_value = {"instances": []}
        resp.headers = {}  # 无 X-TRACE-ID

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = resp
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        data = json.loads(result.root.content[0].text)
        assert data["trace_id"] == "auto-uuid-001"
        assert "hw_trace_id" not in data

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_success_empty_response_content(self, mock_build_http, mock_create_client, mcp_server):
        _trace_id.set("trace-002")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        resp = MagicMock()
        resp.content = None
        resp.json.return_value = {}
        resp.headers = {}

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = resp
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        data = json.loads(result.root.content[0].text)
        assert data["trace_id"] == "trace-002"


# ============================================================
# AK/SK 优先级
# ============================================================

class TestCallToolAKSKPriority:
    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_ak_from_headers(self, mock_build_http, mock_create_client, mcp_server):
        _trace_id.set("t-001")
        _request_headers.set({"x-access-key": "header_ak", "x-secret-key": "header_sk"})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = MagicMock(content=b'{}', json=MagicMock(return_value={}), headers={})
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        mock_create_client.assert_called_once()
        assert mock_create_client.call_args[0][0] == "header_ak"

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_ak_from_arguments(self, mock_build_http, mock_create_client, mcp_server):
        _trace_id.set("t-002")
        _request_headers.set({})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = MagicMock(content=b'{}', json=MagicMock(return_value={}), headers={})
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc", "access_key": "arg_ak", "secret_key": "arg_sk"})
        assert mock_create_client.call_args[0][0] == "arg_ak"

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_ak_from_config(self, mock_build_http, mock_create_client, mcp_server):
        _trace_id.set("t-003")
        _request_headers.set({})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = MagicMock(content=b'{}', json=MagicMock(return_value={}), headers={})
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        assert mock_create_client.call_args[0][0] == "config_ak"

    @pytest.mark.asyncio
    async def test_missing_ak_sk(self, mcp_server):
        """AK/SK 全部缺失 → isError=True 的错误响应"""
        _trace_id.set("t-004")
        _request_headers.set({})
        mcp_server.config.ak = None
        mcp_server.config.sk = None

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        assert result.root.isError is True
        assert "t-004" in result.root.content[0].text
        assert "X-Access-Key" in result.root.content[0].text


# ============================================================
# 错误路径（handler 捕获 ToolError → isError=True）
# ============================================================

class TestCallToolErrors:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, mcp_server):
        """工具名不在 tool_service_map → isError"""
        _trace_id.set("t-005")
        result = await invoke_call_tool(mcp_server, "unknown_tool", {})
        assert result.root.isError is True
        assert "t-005" in result.root.content[0].text
        assert "unknown_tool" in result.root.content[0].text

    @pytest.mark.asyncio
    async def test_tool_not_found_in_service(self, mcp_server):
        """服务内工具名未匹配 → isError"""
        _trace_id.set("t-006")
        mcp_server.original_tools["rds"] = []
        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        assert result.root.isError is True
        assert "t-006" in result.root.content[0].text
        assert "ListInstances" in result.root.content[0].text

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_client_request_exception(self, mock_build_http, mock_create_client, mcp_server):
        """ClientRequestException → isError=True 带 trace_id"""
        _trace_id.set("t-007")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        mock_client = MagicMock()
        ex = ClientRequestException(401, MagicMock(error_code="APIGW.0301", error_msg="Unauthorized"))
        mock_client.do_http_request.side_effect = ex
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        assert result.root.isError is True
        assert "t-007" in result.root.content[0].text
        assert "API 请求失败" in result.root.content[0].text

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_generic_exception(self, mock_build_http, mock_create_client, mcp_server):
        """通用 Exception → isError=True 带 trace_id"""
        _trace_id.set("t-008")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        mock_client = MagicMock()
        mock_client.do_http_request.side_effect = RuntimeError("connection refused")
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        assert result.root.isError is True
        assert "t-008" in result.root.content[0].text
        assert "内部错误" in result.root.content[0].text


# ============================================================
# 华为云 X-TRACE-ID 提取
# ============================================================

class TestCallToolHwTraceId:
    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_lowercase_x_trace_id(self, mock_build_http, mock_create_client, mcp_server):
        """华为云响应 header 小写 x-trace-id 也能提取"""
        _trace_id.set("t-009")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        resp = MagicMock()
        resp.content = b'{"data": []}'
        resp.json.return_value = {"data": []}
        resp.headers = {"x-trace-id": "hw-lowercase-uuid"}

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = resp
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        data = json.loads(result.root.content[0].text)
        assert data["hw_trace_id"] == "hw-lowercase-uuid"

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_response_no_headers_attr(self, mock_build_http, mock_create_client, mcp_server):
        """响应对象没有 headers 属性 → hw_trace_id 为空"""
        _trace_id.set("t-010")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        resp = MagicMock(spec=[])  # 没有 headers 属性
        resp.content = b'{"data": []}'
        resp.json = MagicMock(return_value={"data": []})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = resp
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        result = await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc"})
        data = json.loads(result.root.content[0].text)
        assert "hw_trace_id" not in data


# ============================================================
# region 优先级 + filter_parameters
# ============================================================

class TestCallToolMisc:
    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_region_from_arguments(self, mock_build_http, mock_create_client, mcp_server):
        """region 从 arguments 获取"""
        _trace_id.set("t-011")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = MagicMock(content=b'{}', json=MagicMock(return_value={}), headers={})
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc", "region": "cn-east-2"})
        assert mock_create_client.call_args[0][3] == "cn-east-2"

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_region_from_arguments(self, mock_build_http, mock_create_client, mcp_server):
        """region 从 arguments 传入"""
        _trace_id.set("t-012")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = MagicMock(content=b'{}', json=MagicMock(return_value={}), headers={})
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc", "region": "cn-east-2"})
        assert mock_create_client.call_args[0][3] == "cn-east-2"

    @patch("assets.utils.server.create_api_client")
    @patch("assets.utils.server.build_http_info")
    @pytest.mark.asyncio
    async def test_filter_parameters_removes_none(self, mock_build_http, mock_create_client, mcp_server):
        """filter_parameters 在 call_tool 中去除 None 值"""
        _trace_id.set("t-013")
        _request_headers.set({"x-access-key": "ak", "x-secret-key": "sk"})

        mock_client = MagicMock()
        mock_client.do_http_request.return_value = MagicMock(content=b'{}', json=MagicMock(return_value={}), headers={})
        mock_create_client.return_value = mock_client
        mock_build_http.return_value = {"method": "GET", "resource_path": "/t",
                                         "header_params": {}, "query_params": {}, "path_params": {},
                                         "body": {}, "response_headers": None, "cname": None,
                                         "collection_formats": {}, "post_params": {}}

        await invoke_call_tool(mcp_server, "rds_ListInstances", {"project_id": "abc", "unused_param": None})
        # build_http_info 调用的 arguments 应不含 None
        filtered_args = mock_build_http.call_args[0][1]
        assert "unused_param" not in filtered_args


# ============================================================
# MCPServer 初始化深度测试
# ============================================================

class TestMCPServerClientManagement:
    @pytest.mark.asyncio
    async def test_register_client(self, mcp_server):
        """客户端注册"""
        mock_request = MagicMock()
        await mcp_server.register_client("client-1", mock_request)
        assert "client-1" in mcp_server.active_clients
        assert mcp_server.active_clients["client-1"]["request"] == mock_request

    @pytest.mark.asyncio
    async def test_unregister_client(self, mcp_server):
        """客户端注销"""
        mock_request = MagicMock()
        await mcp_server.register_client("client-1", mock_request)
        await mcp_server.unregister_client("client-1")
        assert "client-1" not in mcp_server.active_clients

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_client(self, mcp_server):
        """注销不存在的客户端 → 无异常"""
        await mcp_server.unregister_client("nonexistent")

    @pytest.mark.asyncio
    async def test_list_tools_via_handler(self, mcp_server):
        """list_tools handler 返回带前缀的工具列表"""
        # 通过 MCP 注册的 handler 调用，而非 mcp_server.list_tools()
        from mcp.types import ListToolsRequest
        req = MagicMock()
        req.params = MagicMock()

        handler = mcp_server.server.request_handlers.get(ListToolsRequest)
        result = await handler(req)
        tools = result.root.tools
        assert len(tools) > 0
        assert tools[0].name == "rds_ListInstances"


class TestMCPServerInitializeDeep:
    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_whitelist_filter_applied(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """白名单过滤只保留指定工具"""
        from assets.utils.model import MCPConfig, ToolFilterConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http",
                                tool_filters={"rds": ToolFilterConfig(mode="whitelist", tools=["ListInstances"])})
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_tool1 = MagicMock()
        mock_tool1.name = "ListInstances"
        mock_tool1.description = "查询实例"
        mock_tool1.inputSchema = {"properties": {}, "required": []}

        mock_tool2 = MagicMock()
        mock_tool2.name = "CreateInstance"
        mock_tool2.description = "创建实例"
        mock_tool2.inputSchema = {"properties": {}, "required": []}

        mock_converter = MagicMock()
        mock_converter.convert.return_value = [mock_tool1, mock_tool2]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))
        assert len(server.original_tools["rds"]) == 1
        assert server.original_tools["rds"][0].name == "ListInstances"

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_blacklist_filter_applied(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """黑名单过滤排除指定工具"""
        from assets.utils.model import MCPConfig, ToolFilterConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http",
                                tool_filters={"rds": ToolFilterConfig(mode="blacklist", tools=["CreateInstance"])})
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_tool1 = MagicMock()
        mock_tool1.name = "ListInstances"
        mock_tool1.description = "查询实例"
        mock_tool1.inputSchema = {"properties": {}, "required": []}

        mock_tool2 = MagicMock()
        mock_tool2.name = "CreateInstance"
        mock_tool2.description = "创建实例"
        mock_tool2.inputSchema = {"properties": {}, "required": []}

        mock_converter = MagicMock()
        mock_converter.convert.return_value = [mock_tool1, mock_tool2]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))
        assert len(server.original_tools["rds"]) == 1
        assert server.original_tools["rds"][0].name == "ListInstances"

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_tool_prefix_mapping(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """工具名前缀映射到 service_code"""
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http")
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_tool = MagicMock()
        mock_tool.name = "ListInstances"
        mock_tool.description = "查询实例"
        mock_tool.inputSchema = {"properties": {}, "required": []}

        mock_converter = MagicMock()
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))
        assert "rds_ListInstances" in server.tool_service_map
        assert server.tool_service_map["rds_ListInstances"] == "rds"
        assert server.tools[0].name == "rds_ListInstances"

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_multi_service_init(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """多服务初始化：rds + das"""
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds", "das"], transport="http")
        mock_load_config.return_value = mock_config

        rds_openapi = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}
        das_openapi = {"info": {"title": "DAS", "x-host": "das.myhuaweicloud.com"}, "paths": {}}
        mock_load_openapi.side_effect = [rds_openapi, das_openapi]

        rds_tool = MagicMock()
        rds_tool.name = "ListInstances"
        rds_tool.description = "查询实例"
        rds_tool.inputSchema = {"properties": {}, "required": []}

        das_tool = MagicMock()
        das_tool.name = "ListSchemas"
        das_tool.description = "查询Schema"
        das_tool.inputSchema = {"properties": {}, "required": []}

        mock_converter = MagicMock()
        mock_converter.convert.side_effect = [[rds_tool], [das_tool]]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))
        assert "rds" in server.openapi_dicts
        assert "das" in server.openapi_dicts
        assert "rds_ListInstances" in server.tool_service_map
        assert "das_ListSchemas" in server.tool_service_map
        assert len(server.tools) == 2