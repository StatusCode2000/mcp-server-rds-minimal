import asyncio
import contextlib
import json
import logging.handlers
import time
import uuid
from pathlib import Path
from typing import Any, Optional, AsyncIterator
import contextvars

# 定义请求上下文变量，存储当前请求的 headers 和 trace_id
_request_headers: contextvars.ContextVar[dict] = contextvars.ContextVar('request_headers', default={})
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar('trace_id', default='')
import uvicorn
from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
from mcp.server import Server
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.logging import configure_logging, get_logger
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from .hwc_tools import (
    create_api_client,
    build_http_info,
    load_openapi,
    filter_parameters,
    load_config,
)
from .model import MCPConfig
from .openapi import OpenAPIToToolsConverter
from .variable import TRANSPORT_SSE, TRANSPORT_HTTP

logger = get_logger(__name__)
configure_logging("INFO")

# 日志写入文件配置：按天轮转，保留30天
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_DIR / "mcp_gateway.log",
    when='midnight',
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logging.getLogger().addHandler(log_handler)

class HeadersMiddleware:
    """提取 HTTP headers 并存入上下文变量"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers_dict = {}
            for key, value in scope.get('headers', []):
                headers_dict[key.decode('utf-8').lower()] = value.decode('utf-8')
            _request_headers.set(headers_dict)
            # 提取或生成 trace_id
            trace_id = headers_dict.get('x-trace-id') or headers_dict.get('trace-id') or str(uuid.uuid4())
            _trace_id.set(trace_id)
        await self.app(scope, receive, send)

class MCPServer:
    def __init__(self, config_path: Path):
        self.config_path = config_path

        self.config: Optional[MCPConfig] = None
        self.server: Optional[Server] = None
        self.tools: list[Tool] = []  # 带前缀的工具（返回给客户端）
        self.initialized: bool = False

        # 多服务存储
        self.openapi_dicts: dict[str, Any] = {}  # service_code → openapi /存储每个服务的 OpenAPI 原始内容
        self.original_tools: dict[str, list[Tool]] = {}  # service_code → 原始工具列表
        self.tool_service_map: dict[str, str] = {}  # prefixed_name → service_code

        self.active_clients: dict[str, Any] = {}
        self._clients_lock = asyncio.Lock()

        self.initialize()

    def initialize(self) -> None:
        """初始化服务器组件"""
        if self.initialized:
            return

        logger.info("开始初始化MCP服务器...")

        try:
            self.config = load_config(self.config_path)
            if not self.config:
                raise ValueError("无法加载服务器配置")

            # 服务器名称（取前3个服务名拼接）
            services_name = "-".join(self.config.service_codes[:3])
            self.server = Server(f"hwc-mcp-server-{services_name}")
            logger.info(
                f"初始化MCP服务器实例： hwc-mcp-server-{services_name}"
            )

            # 循环加载每个服务的 OpenAPI
            for service_code in self.config.service_codes:
                # 默认路径：openapi/{service_code}.json（统一目录）
                openapi_path = (
                    Path(self.config_path.parent) / "openapi" / f"{service_code}.json"
                )
                # 兜底：同目录下的 {service_code}.json
                if not openapi_path.exists():
                    openapi_path = (
                        Path(self.config_path.parent) / f"{service_code}.json"
                    )

                logger.info(f"加载服务 {service_code}，OpenAPI路径: {openapi_path}")

                openapi_dict = load_openapi(openapi_path)
                if not openapi_dict:
                    raise ValueError(
                        f"加载OpenAPI文档失败，请检查{openapi_path}文档内容是否有误"
                    )

                # 保存 OpenAPI
                self.openapi_dicts[service_code] = openapi_dict

                # 转换为工具（原始版本，用于 build_http_info）
                original_tools = OpenAPIToToolsConverter(openapi_dict).convert()

                # 应用工具过滤
                filter_config = self.config.tool_filters.get(service_code)
                if filter_config and filter_config.tools:
                    if filter_config.mode == "whitelist":
                        # 白名单：只保留指定工具
                        original_tools = [
                            t for t in original_tools if t.name in filter_config.tools
                        ]
                        logger.info(
                            f"服务 {service_code} 应用白名单过滤，保留 {len(original_tools)} 个工具: {filter_config.tools}"
                        )
                    elif filter_config.mode == "blacklist":
                        # 黑名单：排除指定工具
                        original_tools = [
                            t for t in original_tools if t.name not in filter_config.tools
                        ]
                        logger.info(
                            f"服务 {service_code} 应用黑名单过滤，排除 {len(filter_config.tools)} 个工具，剩余 {len(original_tools)} 个"
                        )

                self.original_tools[service_code] = original_tools

                # 创建带前缀版本（用于返回给客户端）
                for tool in original_tools:
                    prefixed_name = f"{service_code}_{tool.name}"
                    prefixed_tool = Tool(
                        name=prefixed_name,
                        description=f"[{service_code.upper()}] {tool.description}",
                        inputSchema=tool.inputSchema,
                    )
                    self.tools.append(prefixed_tool)
                    self.tool_service_map[prefixed_name] = service_code

                logger.info(f"服务 {service_code} 加载完成，工具数: {len(original_tools)}")

            logger.info(
                f"总共加载 {len(self.tools)} 个工具，来自 {len(self.config.service_codes)} 个服务"
            )

            # 注册工具处理函数
            self._register_tool_handlers()

            self.initialized = True
            logger.info("MCP服务器初始化完成")

        except Exception as e:
            logger.error(f"服务器初始化失败: {e}")
            raise

    async def register_client(self, client_id, request):
        async with self._clients_lock:
            self.active_clients[client_id] = {
                "request": request,
                "connected_at": time.time(),
            }
            logger.info(f"客户端注册成功: {client_id}")

    async def unregister_client(self, client_id):
        async with self._clients_lock:
            if client_id in self.active_clients:
                del self.active_clients[client_id]
                logger.info(f"客户端已注销: {client_id}")
            else:
                logger.warning(f"尝试注销不存在的客户端: {client_id}")

    def _register_tool_handlers(self) -> None:
        """注册工具处理函数"""
        if not self.server:
            raise RuntimeError("服务器未初始化")

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            self._ensure_initialized()
            return self.tools

        @self.server.call_tool()
        async def call_tool(
            name: str, arguments: dict
        ) -> list[TextContent | ImageContent | EmbeddedResource]:
            trace_id = _trace_id.get()
            logger.info(f"[{trace_id}] call_tool: name={name}")

            # 根据带前缀的工具名找到服务
            service_code = self.tool_service_map.get(name)
            if not service_code:
                logger.warning(f"[{trace_id}] UNKNOWN_TOOL: {name}")
                raise ToolError(f"[{trace_id}] 工具 '{name}' 不存在")

            # 获取原始工具名（去掉前缀）
            original_name = name.replace(f"{service_code}_", "")

            # 从原始工具列表中找到 Tool 对象
            original_tool = next(
                (t for t in self.original_tools[service_code] if t.name == original_name),
                None
            )
            if not original_tool:
                logger.warning(f"[{trace_id}] TOOL_NOT_FOUND: {original_name} in {service_code}")
                raise ToolError(f"[{trace_id}] 服务 '{service_code}' 中未找到工具 '{original_name}'")

            # 获取对应服务的 OpenAPI
            openapi_dict = self.openapi_dicts[service_code]
            x_host = openapi_dict["info"]["x-host"]
            region = arguments.get("region") or "cn-north-4"

            # 从上下文变量获取 headers
            headers = _request_headers.get()

            # 优先级：Headers > 请求参数 > 配置/环境变量
            ak = (
                headers.get('x-access-key') or
                headers.get('access-key') or
                arguments.get('access_key') or
                self.config.ak
            )
            sk = (
                headers.get('x-secret-key') or
                headers.get('secret-key') or
                arguments.get('secret_key') or
                self.config.sk
            )

            ak_source = "headers" if (headers.get('x-access-key') or headers.get('access-key')) else \
                        "arguments" if arguments.get('access_key') else "config"
            logger.info(f"[{trace_id}] AK/SK source: {ak_source}, service={service_code}, region={region}")

            if not ak or not sk:
                logger.warning(f"[{trace_id}] MISSING_CREDENTIALS")
                raise ToolError(f"[{trace_id}] 请在请求 Headers 中提供 X-Access-Key 和 X-Secret-Key")

            client = create_api_client(ak, sk, x_host, region)
            try:
                arguments = filter_parameters(arguments)

                # 传入原始工具和 trace_id
                http_info = build_http_info(
                    original_tool.name, arguments, openapi_dict, self.original_tools[service_code],
                    trace_id=trace_id
                )

                response = client.do_http_request(**http_info)

                # 提取华为云响应的 X-TRACE-ID 用于日志关联
                hw_trace_id = ""
                if response and hasattr(response, 'headers'):
                    hw_trace_id = response.headers.get("X-TRACE-ID", "") or response.headers.get("x-trace-id", "")
                if hw_trace_id:
                    logger.info(f"[{trace_id}] 华为云 X-TRACE-ID: {hw_trace_id}")

                response_data = response.json() if response and response.content else {}
                # trace_id 写入响应数据，返回给客户端
                response_data["trace_id"] = trace_id
                if hw_trace_id:
                    response_data["hw_trace_id"] = hw_trace_id

                logger.info(f"[{trace_id}] call_tool completed: name={name}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(response_data, indent=2, ensure_ascii=False),
                    )
                ]
            except ClientRequestException as ex:
                logger.error(f"[{trace_id}] API 请求失败: {ex.error_msg}")
                raise ToolError(f"[{trace_id}] API 请求失败: {ex.error_msg}")
            except Exception as ex:
                logger.error(f"[{trace_id}] 意外的错误: {str(ex)}")
                raise ToolError(f"[{trace_id}] 内部错误: {str(ex)}")

    def _ensure_initialized(self) -> None:
        """确保服务器已初始化"""
        if not self.initialized:
            raise RuntimeError("服务器未初始化")

    async def run_server(self):
        self._ensure_initialized()
        if self.config.transport == TRANSPORT_SSE:
            # await self.run_sse_server()
            logger.warning("SSE传输模式已被禁用，请切换到http或stdio模式")
        elif self.config.transport == TRANSPORT_HTTP:
            await self.run_http_server()
        else:
            await self.run_stdio_server()

    # async def run_sse_server(self):
    #     logger.info("启动SSE服务器")
    #     # 配置SSE服务器
    #     sse = SseServerTransport("/messages/")

    #     async def handle_sse_connection(request):
    #         logger.info(f"SSE连接请求来自: {request.client}")

    #         # 检查服务器状态
    #         if not self.initialized:
    #             return JSONResponse({"error": "Server initializing"}, status_code=503)

    #         client_id = str(uuid.uuid4())
    #         connection_active = True

    #         try:
    #             # 注册客户端连接（添加到活跃连接列表）
    #             await self.register_client(client_id, request)

    #             # 使用MCP的SSE连接工具建立连接
    #             async with sse.connect_sse(
    #                 request.scope, request.receive, request._send
    #             ) as streams:
    #                 input_stream, output_stream = streams

    #                 try:
    #                     await self.server.run(
    #                         input_stream,
    #                         output_stream,
    #                         self.server.create_initialization_options(),
    #                     )

    #                 except asyncio.CancelledError:
    #                     # 任务被取消（正常关闭）
    #                     logger.info(f"SSE任务被取消: {client_id}")
    #                     connection_active = False

    #                 except Exception as e:
    #                     # 处理其他异常
    #                     logger.error(f"SSE通信异常: {e}", exc_info=True)
    #                     connection_active = False

    #                     # 尝试向客户端发送错误信息（如果连接仍可用）
    #                     if not output_stream.closed:
    #                         try:
    #                             error_msg = {
    #                                 "event": "error",
    #                                 "data": {"message": str(e), "code": 500},
    #                             }
    #                             await output_stream.send(json.dumps(error_msg))
    #                         except Exception as send_error:
    #                             logger.warning(f"发送错误信息失败: {send_error}")

    #                 finally:
    #                     # 确保资源释放
    #                     if connection_active:
    #                         connection_active = False
    #                         await self.unregister_client(client_id)
    #                         logger.info(f"SSE连接已关闭: {client_id}")

    #         except Exception as e:
    #             logger.error(f"SSE连接建立失败: {e}", exc_info=True)

    #             return JSONResponse(
    #                 {"error": "Failed to establish SSE connection", "details": str(e)},
    #                 status_code=500,
    #             )

    #         # 如果没有异常，返回成功响应
    #         return JSONResponse(
    #             {"status": "SSE connection closed normally"}, status_code=200
    #         )

    #     app = Starlette(
    #         routes=[
    #             Route("/sse", endpoint=handle_sse_connection),
    #             Mount("/messages/", app=sse.handle_post_message),
    #         ],
    #         debug=True,
    #     )

    #     # 添加CORS中间件
    #     app.add_middleware(
    #         CORSMiddleware,
    #         allow_origins=["*"],
    #         allow_headers=["*"],
    #         allow_credentials=True,
    #         allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    #     )
    #     sse_config = uvicorn.Config(app, host="0.0.0.0", port=self.config.port)
    #     sse_server = uvicorn.Server(sse_config)
    #     await sse_server.serve()

    async def run_stdio_server(self):
        logger.info("启动STDIO服务器")
        async with stdio_server() as streams:
            await self.server.run(
                streams[0], streams[1], self.server.create_initialization_options()
            )

    async def run_http_server(self):
        logger.info("启动StreamableHTTP服务器")
        # Create the session manager with true stateless mode
        session_manager = StreamableHTTPSessionManager(
            app=self.server,
            event_store=None,
            stateless=True,
        )

        async def handle_streamable_http(
            scope: Scope, receive: Receive, send: Send
        ) -> None:
            await session_manager.handle_request(scope, receive, send)

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            """Context manager for session manager."""
            async with session_manager.run():
                logger.info("Application started with StreamableHTTP session manager!")
                try:
                    yield
                finally:
                    logger.info("Application shutting down...")

        # Create an ASGI application using the transport
        starlette_app = Starlette(
            debug=True,
            routes=[
                Mount("/mcp", app=handle_streamable_http),
            ],
            lifespan=lifespan,
        )
        # 添加 headers 中间件
        starlette_app.add_middleware(HeadersMiddleware)

        http_config = uvicorn.Config(
            starlette_app, host="0.0.0.0", port=self.config.port
        )
        http_server = uvicorn.Server(http_config)
        await http_server.serve()
