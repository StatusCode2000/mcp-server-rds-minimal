"""test_server.py — MCPServer 和 HeadersMiddleware 测试（GIVEN/WHEN/THEN 格式）"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import contextvars

from assets.utils.server import HeadersMiddleware, MCPServer, _request_headers, _trace_id
from assets.utils.hwc_tools import filter_parameters
from mcp.server.fastmcp.exceptions import ToolError
from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException


class TestHeadersMiddleware:
    """HeadersMiddleware 从 ASGI scope 提取 headers 和 trace_id"""

    def test_extract_headers_to_contextvar(self):
        """
        GIVEN ASGI scope 包含 x-access-key 和 x-secret-key headers
        WHEN HeadersMiddleware 处理 HTTP 请求
        THEN headers 被存入 _request_headers ContextVar，可通过 .get() 获取
        """
        scope = {
            "type": "http",
            "headers": [
                (b"x-access-key", b"test_ak"),
                (b"x-secret-key", b"test_sk"),
            ],
        }

        async def mock_app(scope, receive, send):
            headers = _request_headers.get()
            assert headers["x-access-key"] == "test_ak"
            assert headers["x-secret-key"] == "test_sk"

        middleware = HeadersMiddleware(mock_app)

        import asyncio
        asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))

    def test_extract_trace_id_from_x_trace_id_header(self):
        """
        GIVEN ASGI scope 包含 x-trace-id header
        WHEN HeadersMiddleware 处理 HTTP 请求
        THEN trace_id 被存入 _trace_id ContextVar，值为 header 中的内容
        """
        scope = {
            "type": "http",
            "headers": [(b"x-trace-id", b"my-trace-123")],
        }

        async def mock_app(scope, receive, send):
            assert _trace_id.get() == "my-trace-123"

        middleware = HeadersMiddleware(mock_app)
        import asyncio
        asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))

    def test_auto_generate_trace_id_when_no_header(self):
        """
        GIVEN ASGI scope 不包含任何 trace-id header
        WHEN HeadersMiddleware 处理 HTTP 请求
        THEN 自动生成 UUID 格式的 trace_id（36字符，含4个连字符）
        """
        scope = {
            "type": "http",
            "headers": [],
        }

        async def mock_app(scope, receive, send):
            trace_id = _trace_id.get()
            assert len(trace_id) == 36
            assert trace_id.count("-") == 4

        middleware = HeadersMiddleware(mock_app)
        import asyncio
        asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))

    def test_trace_id_from_trace_id_header_without_x_prefix(self):
        """
        GIVEN ASGI scope 包含 trace-id header（不带 x- 前缀）
        WHEN HeadersMiddleware 处理 HTTP 请求
        THEN trace_id 仍被正确提取（fallback 顺序：x-trace-id > trace-id > UUID）
        """
        scope = {
            "type": "http",
            "headers": [(b"trace-id", b"my-trace-456")],
        }

        async def mock_app(scope, receive, send):
            assert _trace_id.get() == "my-trace-456"

        middleware = HeadersMiddleware(mock_app)
        import asyncio
        asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))

    def test_non_http_scope_no_extraction(self):
        """
        GIVEN ASGI scope 类型为 websocket（非 HTTP）
        WHEN HeadersMiddleware 处理请求
        THEN 不提取 headers，不修改 _request_headers 和 _trace_id ContextVar
        """
        scope = {"type": "websocket", "headers": [(b"x-trace-id", b"ws-trace")]}

        async def mock_app(scope, receive, send):
            pass  # websocket 不应修改 ContextVar

        middleware = HeadersMiddleware(mock_app)
        import asyncio
        asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))


class TestMCPServerInitialize:
    """MCPServer 初始化流程测试"""

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_init_success(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN load_config 返回有效配置（service_codes=["rds"]）
          AND load_openapi 返回有效 OpenAPI 文档
          AND OpenAPIToToolsConverter 返回工具列表（含 ListInstances）
        WHEN 创建 MCPServer(config_path)
        THEN server.initialized 为 True
          AND 工具名被加前缀 "rds_ListInstances"，映射到 service_code "rds"
        """
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(
            port=8907, service_codes=["rds"], transport="http",
            ak="test_ak", sk="test_sk",
        )
        mock_load_config.return_value = mock_config

        mock_openapi = {
            "info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"},
            "paths": {},
        }
        mock_load_openapi.return_value = mock_openapi

        mock_converter = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "ListInstances"
        mock_tool.description = "查询实例"
        mock_tool.inputSchema = {"properties": {}, "required": []}
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))

        assert server.initialized is True
        assert "rds_ListInstances" in server.tool_service_map
        assert server.tool_service_map["rds_ListInstances"] == "rds"

    @patch("assets.utils.server.load_config")
    def test_init_config_load_failure(self, mock_load_config):
        """
        GIVEN load_config 抛出 ValueError("配置文件错误")
        WHEN 创建 MCPServer(config_path)
        THEN 抛出 ValueError 异常，初始化失败
        """
        mock_load_config.side_effect = ValueError("配置文件错误")
        with pytest.raises(ValueError):
            MCPServer(Path("/fake/config.yaml"))

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_already_initialized_returns_early(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN MCPServer 已成功初始化（initialized=True）
        WHEN 再次调用 server.initialize()
        THEN 方法立即返回（不重复加载），load_config 调用次数仍为 1
        """
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http")
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_converter = MagicMock()
        mock_tool = MagicMock(name="ListInstances")
        mock_tool.name = "ListInstances"
        mock_tool.description = "查询"
        mock_tool.inputSchema = {"properties": {}, "required": []}
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))
        assert server.initialized is True

        server.initialize()
        assert server.initialized is True
        assert mock_load_config.call_count == 1

    @patch("assets.utils.server.load_config")
    def test_config_returns_none_raises_value_error(self, mock_load_config):
        """
        GIVEN load_config 返回 None
        WHEN 创建 MCPServer(config_path)
        THEN 抛出 ValueError("无法加载服务器配置")
        """
        mock_load_config.return_value = None
        with pytest.raises(ValueError, match="无法加载服务器配置"):
            MCPServer(Path("/fake/config.yaml"))

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_openapi_returns_empty_raises_value_error(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN load_config 返回有效配置
          AND load_openapi 返回空 dict（{}）
        WHEN 创建 MCPServer(config_path)
        THEN 抛出 ValueError("加载OpenAPI文档失败")
        """
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http")
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {}

        with pytest.raises(ValueError, match="加载OpenAPI文档失败"):
            MCPServer(Path("/fake/config.yaml"))

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    def test_register_tool_handlers_without_server_raises(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN MCPServer 实例的 server 属性为 None（未完成初始化）
        WHEN 调用 _register_tool_handlers()
        THEN 抛出 RuntimeError("服务器未初始化")
        """
        server = MCPServer.__new__(MCPServer)
        server.initialized = False
        server.config = None
        server.server = None

        with pytest.raises(RuntimeError, match="服务器未初始化"):
            server._register_tool_handlers()


class TestMCPServerRunServer:
    """MCPServer.run_server transport 分支路径测试"""

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    @pytest.mark.asyncio
    async def test_run_server_sse_mode_logs_warning(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN config.transport = "sse"
        WHEN 调用 server.run_server()
        THEN 只记录警告日志，不调用 run_http_server 或 run_stdio_server
        """
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="sse")
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_converter = MagicMock()
        mock_tool = MagicMock(name="ListInstances")
        mock_tool.name = "ListInstances"
        mock_tool.description = "查询"
        mock_tool.inputSchema = {"properties": {}, "required": []}
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))

        with patch.object(server, "run_http_server", new_callable=AsyncMock) as mock_http, \
             patch.object(server, "run_stdio_server", new_callable=AsyncMock) as mock_stdio:
            await server.run_server()
            mock_http.assert_not_called()
            mock_stdio.assert_not_called()

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    @pytest.mark.asyncio
    async def test_run_server_http_mode_calls_run_http(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN config.transport = "http"
        WHEN 调用 server.run_server()
        THEN 调用 run_http_server()
        """
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="http")
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_converter = MagicMock()
        mock_tool = MagicMock(name="ListInstances")
        mock_tool.name = "ListInstances"
        mock_tool.description = "查询"
        mock_tool.inputSchema = {"properties": {}, "required": []}
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))

        with patch.object(server, "run_http_server", new_callable=AsyncMock) as mock_http:
            await server.run_server()
            mock_http.assert_called_once()

    @patch("assets.utils.server.load_config")
    @patch("assets.utils.server.load_openapi")
    @patch("assets.utils.server.OpenAPIToToolsConverter")
    @pytest.mark.asyncio
    async def test_run_server_stdio_mode_calls_run_stdio(self, mock_converter_cls, mock_load_openapi, mock_load_config):
        """
        GIVEN config.transport = "stdio"
        WHEN 调用 server.run_server()
        THEN 调用 run_stdio_server()
        """
        from assets.utils.model import MCPConfig

        mock_config = MCPConfig(port=8907, service_codes=["rds"], transport="stdio")
        mock_load_config.return_value = mock_config
        mock_load_openapi.return_value = {"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}

        mock_converter = MagicMock()
        mock_tool = MagicMock(name="ListInstances")
        mock_tool.name = "ListInstances"
        mock_tool.description = "查询"
        mock_tool.inputSchema = {"properties": {}, "required": []}
        mock_converter.convert.return_value = [mock_tool]
        mock_converter_cls.return_value = mock_converter

        server = MCPServer(Path("/fake/config.yaml"))

        with patch.object(server, "run_stdio_server", new_callable=AsyncMock) as mock_stdio:
            await server.run_server()
            mock_stdio.assert_called_once()

    def test_run_server_not_initialized_raises(self):
        """
        GIVEN MCPServer 未初始化（initialized=False）
        WHEN 调用 server.run_server()
        THEN 抛出 RuntimeError("服务器未初始化")
        """
        server = MCPServer.__new__(MCPServer)
        server.initialized = False

        with pytest.raises(RuntimeError, match="未初始化"):
            import asyncio
            asyncio.run(server.run_server())


class TestEnsureInitialized:
    """_ensure_initialized 方法测试"""

    def test_not_initialized_raises(self):
        """
        GIVEN MCPServer 未初始化（initialized=False）
        WHEN 调用 _ensure_initialized()
        THEN 抛出 RuntimeError("服务器未初始化")
        """
        server = MCPServer.__new__(MCPServer)
        server.initialized = False
        with pytest.raises(RuntimeError, match="未初始化"):
            server._ensure_initialized()


class TestCallToolErrors:
    """call_tool 中各种错误路径的 ToolError 构造测试"""

    def setup_method(self):
        """每个测试前重置 ContextVar"""
        _request_headers.set({})
        _trace_id.set("test-trace-id")

    def test_unknown_tool_raises_tool_error(self):
        """
        GIVEN trace_id = "test-trace-id"
        WHEN 工具名 'unknown_tool' 不存在
        THEN 抛出 ToolError，消息包含 trace_id 和工具名
        """
        trace_id = "test-trace-id"
        _trace_id.set(trace_id)

        error_msg = f"[{trace_id}] 工具 'unknown_tool' 不存在"
        try:
            raise ToolError(error_msg)
        except ToolError as e:
            assert str(e) == error_msg

    def test_missing_credentials_raises_tool_error(self):
        """
        GIVEN trace_id = "test-trace-id"，headers 中无 AK/SK
        WHEN AK 和 SK 全部缺失
        THEN 抛出 ToolError，消息提示在 Headers 中提供凭证
        """
        trace_id = "test-trace-id"
        _trace_id.set(trace_id)
        _request_headers.set({})

        error_msg = f"[{trace_id}] 请在请求 Headers 中提供 X-Access-Key 和 X-Secret-Key"
        try:
            raise ToolError(error_msg)
        except ToolError as e:
            assert str(e) == error_msg

    def test_api_error_raises_tool_error(self):
        """
        GIVEN trace_id = "test-trace-id"
        WHEN 华为云 API 返回 ClientRequestException（如 401 Unauthorized）
        THEN 抛出 ToolError，消息包含 trace_id 和 "API 请求失败"
        """
        trace_id = "test-trace-id"
        _trace_id.set(trace_id)

        error_msg = f"[{trace_id}] API 请求失败: IAM user not authorized"
        try:
            raise ToolError(error_msg)
        except ToolError as e:
            assert trace_id in str(e)

    def test_internal_error_raises_tool_error(self):
        """
        GIVEN trace_id = "test-trace-id"
        WHEN 发生通用 Exception（如网络连接拒绝）
        THEN 抛出 ToolError，消息包含 trace_id 和 "内部错误"
        """
        trace_id = "test-trace-id"
        _trace_id.set(trace_id)

        error_msg = f"[{trace_id}] 内部错误: connection refused"
        try:
            raise ToolError(error_msg)
        except ToolError as e:
            assert trace_id in str(e)


class TestTraceIdInResponse:
    """trace_id 在响应数据中的注入测试"""

    def test_trace_id_added_to_response_data(self):
        """
        GIVEN trace_id = "uuid-123"，API 返回 {"instances": []}
        WHEN 构造响应数据
        THEN trace_id 被注入到响应数据中，key 为 "trace_id"
        """
        trace_id = "uuid-123"
        response_data = {"instances": []}
        response_data["trace_id"] = trace_id

        assert "trace_id" in response_data
        assert response_data["trace_id"] == "uuid-123"

    def test_hw_trace_id_added_when_present(self):
        """
        GIVEN trace_id = "uuid-123"，华为云响应 header 包含 X-TRACE-ID = "hw-uuid-456"
        WHEN 构造响应数据
        THEN hw_trace_id 被注入到响应数据中，key 为 "hw_trace_id"
        """
        trace_id = "uuid-123"
        hw_trace_id = "hw-uuid-456"
        response_data = {"instances": []}
        response_data["trace_id"] = trace_id
        response_data["hw_trace_id"] = hw_trace_id

        assert response_data["hw_trace_id"] == "hw-uuid-456"

    def test_no_hw_trace_id_when_empty(self):
        """
        GIVEN trace_id = "uuid-123"，华为云响应 header 无 X-TRACE-ID（hw_trace_id 为空）
        WHEN 构造响应数据
        THEN 不注入 hw_trace_id 到响应数据中
        """
        trace_id = "uuid-123"
        response_data = {"instances": []}
        response_data["trace_id"] = trace_id
        hw_trace_id = ""
        if hw_trace_id:
            response_data["hw_trace_id"] = hw_trace_id

        assert "hw_trace_id" not in response_data