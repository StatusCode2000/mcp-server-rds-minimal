# MCP Server HTTP 请求启动时序详解

## 一、完整请求时序图

```
┌─────────┐  ┌──────────┐  ┌─────────────────┐  ┌──────────────────────────────┐  ┌───────────────┐  ┌─────────────┐  ┌───────────┐
│ 客户端  │  │ Starlette │  │ HeadersMiddleware│  │ StreamableHTTPSessionManager │  │ HTTP Transport│  │ MCP Server │  │华为云 API │
│         │  │ (ASGI)    │  │                 │  │                              │  │               │  │             │  │           │
└────┬────┘  └─────┬─────┘  └──────┬──────────┘  └──────┬───────────────────────┘  └───────┬───────┘  └─────┬──────┘  └─────┬─────┘
     │              │               │                    │                                │               │              │
     │  HTTP POST /mcp/             │                    │                                │               │              │
     │  Headers: AK/SK              │                    │                                │               │              │
     │─────────────>│               │                    │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │ 封装 ASGI scope│                    │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │ scope = {     │                    │                                │               │              │
     │              │   "type":"http│                    │                                │               │              │
     │              │   "headers":[ │                    │                                │               │              │
     │              │     (b"x-acc..│                    │                                │               │              │
     │              │     b"your_ak")│                   │                                │               │              │
     │              │   ]            │                    │                                │               │              │
     │              │ }              │                    │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │───────────────>│                    │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │               │ ★ 检查 scope["type"]│                                │               │              │
     │              │               │   == "http"        │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │               │ ★ 遍历 headers     │                                │               │              │
     │              │               │   decode bytes→str │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │               │ headers_dict = {   │                                │               │              │
     │              │               │   "x-access-key":  │                                │               │              │
     │              │               │   "your_ak",       │                                │               │              │
     │              │               │   "x-secret-key":  │                                │               │              │
     │              │               │   "your_sk"        │                                │               │              │
     │              │               │ }                  │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │               │ ★ 存入 contextvars │                                │               │              │
     │              │               │ _request_headers   │                                │               │              │
     │              │               │   .set(headers_dict│                               │               │              │
     │              │               │                    │                                │               │              │
     │              │               │                    │                                │               │              │
     │              │               │ await self.app(    │                                │               │              │
     │              │               │   scope, receive,  │                                │               │              │
     │              │               │   send)            │                                │               │              │
     │              │               │────────────────────>│                                │               │              │
     │              │               │                    │                                │               │              │
     │              │               │                    │ ★ handle_request()             │               │              │
     │              │               │                    │                                │               │              │
     │              │               │                    │ 检查 stateless 模式            │               │              │
     │              │               │                    │ ───────────────┐               │               │              │
     │              │               │                    │                │               │               │              │
     │              │               │                    │                │ stateless=True│               │              │
     │              │               │                    │                │ → 无状态模式  │               │              │
     │              │               │                    │                ▼               │               │              │
     │              │               │                    │                                │               │              │
     │              │               │                    │ ★ 创建 HTTP Transport          │               │              │
     │              │               │                    │ ─────────────────────────────────────────────>│               │              │
     │              │               │                    │                                │               │              │
     │              │               │                    │                                │ http_transport │              │
     │              │               │                    │                                │ = StreamableHT │              │
     │              │               │                    │                                │ TPServerTransp │              │
     │              │               │                    │                                │ ort(           │              │
     │              │               │                    │                                │   session_id=No│              │
     │              │               │                    │                                │ )              │              │
     │              │               │                    │                                │               │              │
     │              │               │                    │ ★ 启动 MCP Server 任务         │               │              │
     │              │               │                    │ ──────────────────────────────────────────────────────────────────>│
     │              │               │                    │                                │               │              │
     │              │               │                    │                                │               │ ★ app.run()  │
     │              │               │                    │                                │               │ ─────────────┐│
     │              │               │                    │                                │               │              ││
     │              │               │                    │                                │               │              ││ 等待 MCP 请求│
     │              │               │                    │                                │               │              ││
     │              │               │                    │ ★ transport.handle_request() │               │              ││
     │              │               │                    │ ──────────────────────────────>│               │              ││
     │              │               │                    │                                │               │              ││
     │              │               │                    │                                │ ★ 解析 HTTP 请求│              ││
     │              │               │                    │                                │ ─────────────┐ │              ││
     │              │               │                    │                                │              │ │              ││
     │              │               │                    │                                │              │ │ 解析 JSON-RPC│              ││
     │              │               │                    │                                │              │ │              ││
     │              │               │                    │                                │              │ │ method:      │              ││
     │              │               │                    │                                │              │ │ "tools/call" │              ││
     │              │               │                    │                                │              │ │              ││
     │              │               │                    │                                │              │ │ params:      │              ││
     │              │               │                    │                                │              │ │   name:      │              ││
     │              │               │                    │                                │              │ │   "rds_List.."│              ││
     │              │               │                    │                                │              │ │   arguments  │              ││
     │              │               │                    │                                │              │ ▼ │              ││
     │              │               │                    │                                │               │ │              ││
     │              │               │                    │                                │               │ │              ││
     │              │               │                    │                                │ ★ 发送到 MCP Server│              ││
     │              │               │                    │                                │───────────────────────────────────>│
     │              │               │                    │                                │               │ │              ││
     │              │               │                    │                                │               │ │              ││┌──────────────────────────────────
     │              │               │                    │                                │               │ │              │││ call_tool(name, arguments)
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              │││ ★ Step 1: 路由到服务
     │              │               │                    │                                │               │ │              │││ service_code = tool_service_map
     │              │               │                    │                                │               │ │              │││   .get(name) → "rds"
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              │││ ★ Step 2: 获取原始工具名
     │              │               │                    │                                │               │ │              │││ original_name = name.replace(
     │              │               │                    │                                │               │ │              │││   "rds_", "") → "ListInstances"
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              │││ ★ Step 3: 从 contextvars 获取 Headers
     │              │               │                    │                                │               │ │              │││ ─────────────────────────────────
     │              │               │                    │                                │               │ │              │││                                │
     │              │               │   <────────────────────────────────────────────────────────────────────────────────────────────────
     │              │               │                    │                                │               │ │              │││  _request_headers.get()
     │              │               │                    │                                │               │ │              │││  → {"x-access-key": "your_ak",
     │              │               │                    │                                │               │ │              │││      "x-secret-key": "your_sk"}
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              │││ ★ Step 4: 提取 AK/SK
     │              │               │                    │                                │               │ │              │││ ak = headers.get('x-access-key')
     │              │               │                    │                                │               │ │              │││   → "your_ak"
     │              │               │                    │                                │               │ │              │││ sk = headers.get('x-secret-key')
     │              │               │                    │                                │               │ │              │││   → "your_sk"
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              │││ ★ Step 5: 创建 API Client
     │              │               │                    │                                │               │ │              │││ create_api_client(ak, sk, ...)
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              │││ ★ Step 6: 调用华为云 API
     │              │               │                    │                                │               │ │─────────────────────────────────────>│
     │              │               │                    │                                │               │ │              │││                    │
     │              │               │                    │                                │               │ │              │││                    │
     │              │               │                    │                                │               │ │              │││<───────────────────│
     │              │               │                    │                                │               │ │              │││  返回 API 结果     │
     │              │               │                    │                                │               │ │              │││                    │
     │              │               │                    │                                │               │ │              │││ ★ Step 7: 返回结果
     │              │               │                    │                                │               │ │              │││ return [TextContent(...)]
     │              │               │                    │                                │               │ │              │││
     │              │               │                    │                                │               │ │              ││└──────────────────────────────────
     │              │               │                    │                                │               │ │              ││
     │              │               │                    │                                │<──────────────────────────────────────│
     │              │               │                    │                                │               │ │              ││
     │              │               │                    │                                │ ★ transport 返回响应│              ││
     │              │               │                    │                                │ ─────────────────────┐│              ││
     │              │               │                    │                                │                      ││              ││
     │              │               │                    │                                │ SSE/JSON Response    ││              ││
     │              │               │                    │                                │                      ▼│              ││
     │              │               │                    │                                │                       │              ││
     │              │               │                    │ ★ terminate transport          │                       │              ││
     │              │               │                    │ ──────────────────────────────>│                       │              ││
     │              │               │                    │                                │                       │              ││
     │              │               │                    │<───────────────────────────────│                       │              ││
     │              │               │                    │                                │                       │              ││
     │              │               │<───────────────────│                                │                       │              ││
     │              │               │                    │                                │                       │              ││
     │              │<──────────────│                    │                                │                       │              ││
     │              │               │                    │                                │                       │              ││
     │<─────────────│               │                    │                                │                       │              ││
     │              │               │                    │                                │                       │              ││
     │ HTTP Response│               │                    │                                │                       │              ││
     │──────────────│               │                    │                                │                       │              ││
     │              │               │                    │                                │                       │              ││
```

---

## 二、简化版时序图

```
客户端                 Starlette              HeadersMiddleware         MCP Server              华为云 API
   │                       │                        │                        │                        │
   │  POST /mcp/           │                        │                        │                        │
   │  Headers: AK/SK       │                        │                        │                        │
   │──────────────────────>│                        │                        │                        │
   │                       │                        │                        │                        │
   │                       │  scope['headers']      │                        │                        │
   │                       │  (bytes格式)           │                        │                        │
   │                       │───────────────────────>│                        │                        │
   │                       │                        │                        │                        │
   │                       │                        │  ★ 提取 Headers        │                        │
   │                       │                        │  decode bytes→str      │                        │
   │                       │                        │                        │                        │
   │                       │                        │  ★ 存入 contextvars    │                        │
   │                       │                        │  _request_headers.set()│                        │
   │                       │                        │                        │                        │
   │                       │                        │────────────────────────>│                        │
   │                       │                        │                        │                        │
   │                       │                        │                        │  call_tool()           │
   │                       │                        │                        │                        │
   │                       │                        │                        │  ★ 获取 Headers        │
   │                       │                        │                        │  _request_headers.get()│
   │                       │                        │                        │                        │
   │                       │                        │                        │  ★ 提取 AK/SK          │
   │                       │                        │                        │  ak = headers.get()    │
   │                       │                        │                        │  sk = headers.get()    │
   │                       │                        │                        │                        │
   │                       │                        │                        │  ★ 创建 Client         │
   │                       │                        │                        │  (ak, sk, x_host)      │
   │                       │                        │                        │                        │
   │                       │                        │                        │────────────────────────>│
   │                       │                        │                        │                        │
   │                       │                        │                        │                        │  API 请求
   │                       │                        │                        │                        │  (带签名)
   │                       │                        │                        │                        │
   │                       │                        │                        │                        │<────────
   │                       │                        │                        │                        │  API 响应
   │                       │                        │                        │                        │
   │                       │                        │                        │<────────────────────────│
   │                       │                        │                        │  返回结果               │
   │                       │                        │                        │                        │
   │                       │                        │<───────────────────────│                        │
   │                       │                        │                        │                        │
   │                       │<───────────────────────│                        │                        │
   │                       │                        │                        │                        │
   │<──────────────────────│                        │                        │                        │
   │                       │                        │                        │                        │
   │  HTTP Response        │                        │                        │                        │
   │                       │                        │                        │                        │
```

---

## 三、应用启动阶段时序

```
┌─────────────────────────────────────────────────────────────────────────
│                          应用启动阶段
├─────────────────────────────────────────────────────────────────────────
│
│ run.py
│     │
│     │  run_server(config)
│     ▼
│ MCPServer.__init__()
│     │
│     │  initialize() → 加载 OpenAPI、创建工具
│     ▼
│ MCPServer.run_http_server()
│     │
│     │  创建 session_manager = StreamableHTTPSessionManager(
│     │      app=self.server,  ← MCP Server 实例
│     │      stateless=True
│     │  )
│     │
│     │  创建 Starlette App
│     │  starlette_app = Starlette(
│     │      routes=[Mount("/mcp", handle_streamable_http)],
│     │      lifespan=lifespan
│     │  )
│     │
│     │  ★ 添加 HeadersMiddleware
│     │  starlette_app.add_middleware(HeadersMiddleware)
│     │
│     ▼
│ lifespan() 上下文管理器
│     │
│     │  ★ async with session_manager.run():
│     │      # 创建 _task_group（任务组）
│     │      # 准备好接收请求
│     │      yield
│     │
│     ▼
│ uvicorn.serve()
│     │
│     │  等待 HTTP 请求...
│
└─────────────────────────────────────────────────────────────────────────
```

---

## 四、请求处理阶段时序

```
┌─────────────────────────────────────────────────────────────────────────
│                          请求处理阶段
├─────────────────────────────────────────────────────────────────────────
│
│ HTTP 请求到达 /mcp/
│     │
│     │  HeadersMiddleware
│     │  ─────────────────────────────────────
│     │  │
│     │  │  ★ scope["type"] == "http"
│     │  │
│     │  │  ★ 遍历 scope['headers']
│     │  │      decode bytes → str
│     │  │
│     │  │  ★ _request_headers.set(headers_dict)
│     │  │
│     │  ─────────────────────────────────────
│     │
│     ▼
│ session_manager.handle_request()
│     │
│     │  检查 stateless=True
│     │  → _handle_stateless_request()
│     │
│     ▼
│ _handle_stateless_request()
│     │
│     │  ★ 创建 http_transport = StreamableHTTPServerTransport()
│     │
│     │  ★ 启动 MCP Server 任务
│     │  await _task_group.start(run_stateless_server)
│     │  │
│     │  │  run_stateless_server():
│     │  │      async with http_transport.connect():
│     │  │          await self.app.run(...)  ← MCP Server 运行
│     │  │
│     │  ★ await http_transport.handle_request()
│     │
│     │  ★ await http_transport.terminate()
│     │
│     ▼
│ MCP Server 处理请求
│     │
│     │  call_tool(name, arguments)
│     │  ─────────────────────────────────────
│     │  │
│     │  │  ★ Step 1: service_code = tool_service_map.get(name)
│     │  │
│     │  │  ★ Step 2: original_name = name.replace(prefix, "")
│     │  │
│     │  │  ★ Step 3: headers = _request_headers.get()  ← 从 contextvars
│     │  │
│     │  │  ★ Step 4: ak = headers.get('x-access-key')
│     │  │           sk = headers.get('x-secret-key')
│     │  │
│     │  │  ★ Step 5: 创建 API Client
│     │  │
│     │  │  ★ Step 6: 调用华为云 API
│     │  │
│     │  │  ★ Step 7: 返回结果
│     │  │
│     │  ─────────────────────────────────────
│     │
│     ▼
│ 返回 HTTP Response
│
└─────────────────────────────────────────────────────────────────────────────────
```

---

## 五、session_manager.handle_request 详解

### 核心逻辑

```python
async def handle_request(
    self,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    # 检查任务组是否初始化
    if self._task_group is None:
        raise RuntimeError("Task group is not initialized. Make sure to use run().")

    # 根据模式选择处理器
    if self.stateless:
        await self._handle_stateless_request(scope, receive, send)
    else:
        await self._handle_stateful_request(scope, receive, send)
```

### 无状态模式流程（当前使用）

```python
async def _handle_stateless_request(scope, receive, send):
    # 1. 创建 HTTP Transport（无会话 ID）
    http_transport = StreamableHTTPServerTransport(
        mcp_session_id=None,  # 无状态，不追踪会话
        is_json_response_enabled=self.json_response,
        event_store=None,     # 无事件存储
    )

    # 2. 启动 MCP Server 任务
    async def run_stateless_server(*, task_status):
        async with http_transport.connect() as streams:
            read_stream, write_stream = streams
            task_status.started()
            await self.app.run(
                read_stream,
                write_stream,
                self.app.create_initialization_options(),
                stateless=True,
            )

    await self._task_group.start(run_stateless_server)

    # 3. 处理 HTTP 请求
    await http_transport.handle_request(scope, receive, send)

    # 4. 终止 Transport
    await http_transport.terminate()
```

---

## 六、完整数据流

```
HTTP 请求
    │
    │  scope['headers'] = [(b"x-access-key", b"your_ak"), ...]
    │
    ▼
HeadersMiddleware
    │
    │  decode() → {"x-access-key": "your_ak"}
    │  _request_headers.set(...)
    │
    ▼
session_manager.handle_request()
    │
    │  检查 stateless 模式
    │
    ▼
创建 StreamableHTTPServerTransport
    │
    │  http_transport = StreamableHTTPServerTransport(...)
    │
    ▼
启动 MCP Server 任务
    │
    │  app.run(read_stream, write_stream, ...)
    │  ↑ 等待处理请求
    │
    ▼
http_transport.handle_request()
    │
    │  解析 JSON-RPC: {"method": "tools/call", "params": {...}}
    │  发送到 MCP Server
    │
    ▼
MCP Server.call_tool()
    │
    │  ★ _request_headers.get()
    │  ★ headers.get('x-access-key')
    │  ★ headers.get('x-secret-key')
    │
    ▼
调用华为云 API
    │
    │  create_api_client(ak, sk, ...)
    │  client.do_http_request(...)
    │
    ▼
返回结果 → transport → session_manager → middleware → 客户端
```

---

## 七、关键组件职责

| 组件 | 职责 | 文件位置 |
|------|------|----------|
| **HeadersMiddleware** | 提取 Headers → 存入 contextvars | `assets/utils/server.py` 第 41-53 行 |
| **session_manager.handle_request** | 选择处理器模式 | `.venv/.../streamable_http_manager.py` 第 139-162 行 |
| **http_transport** | 解析 HTTP/MCP 协议，双向通信 | `.venv/.../streamable_http.py` |
| **MCP Server** | 处理 MCP 请求，调用 call_tool() | `assets/utils/server.py` 第 164-211 行 |

---

## 八、关键代码位置汇总

| 步骤 | 文件 | 行号 | 代码 |
|------|------|------|------|
| 创建 Session Manager | server.py | 369-373 | `StreamableHTTPSessionManager(app=self.server)` |
| 初始化任务组 | server.py | 383 | `async with session_manager.run():` |
| HeadersMiddleware | server.py | 41-53 | 中间件类定义 |
| 注册中间件 | server.py | 338 | `starlette_app.add_middleware(HeadersMiddleware)` |
| handle_request | streamable_http_manager.py | 139-162 | 请求入口 |
| _handle_stateless_request | streamable_http_manager.py | 164-211 | 无状态处理 |
| call_tool AK/SK 获取 | server.py | 144-166 | 优先级获取逻辑 |

---

## 九、contextvars 传递机制

### 为什么 contextvars 能在多层传递后仍有效

```
HeadersMiddleware → session_manager → http_transport → MCP Server → call_tool()

所有这些都在同一个异步上下文中执行：
┌─────────────────────────────────────────────────────┐
│  异步请求上下文                                      │
│                                                     │
│  _request_headers.set({"ak": "xxx"}) ← Middleware   │
│                                                     │
│  _request_headers.get() → {"ak": "xxx"} ← call_tool │
│                                                     │
│  同一个上下文，数据共享                               │
└─────────────────────────────────────────────────────┘
```

### 多请求隔离示例

```
请求 A 的异步上下文          请求 B 的异步上下文
┌─────────────────────┐    ┌─────────────────────┐
│ _request_headers    │    │ _request_headers    │
│ = {"ak": "A的ak"}   │    │ = {"ak": "B的ak"}   │
│                     │    │                     │
│ call_tool() 使用    │    │ call_tool() 使用    │
│ → {"ak": "A的ak"}   │    │ → {"ak": "B的ak"}   │
└─────────────────────┘    └─────────────────────┘

每个请求有独立的上下文副本，互不干扰
```

---

## 十、总结

### 启动流程简化

```
1. 创建 MCP Server 实例
2. 创建 session_manager，持有 MCP Server 引用
3. lifespan 启动 session_manager.run() → 创建任务组
4. uvicorn 等待请求
5. 请求到达 → HeadersMiddleware 提取 Headers
6. session_manager.handle_request() → 选择处理器
7. 启动 MCP Server 任务 → self.app.run()
8. call_tool() → 从 contextvars 获取 AK/SK
9. 调用华为云 API → 返回结果
```

### 核心要点

1. **Headers 在中间件层提取**：一次提取，全链路可用
2. **contextvars 实现跨层传递**：异步安全的上下文变量
3. **无状态模式**：每次请求创建新的 transport，请求结束销毁
4. **任务组管理**：`_task_group.start()` 启动 MCP Server 任务