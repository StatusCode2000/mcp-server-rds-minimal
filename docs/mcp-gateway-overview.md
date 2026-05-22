---
name: mcp-gateway-overview
description: MCP Gateway 多服务架构总览流程图，用于串讲需求
---

# MCP Gateway 多服务架构总览

## 架构全景图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP 客户端 (Claude / Cursor / IDE)                │
│                                                                             │
│   连接配置: http://localhost:8907/mcp/                                      │
│   Headers:  X-Access-Key=AK, X-Secret-Key=SK                               │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        │  HTTP POST (JSON-RPC)
        │  {"method": "tools/list"} 或 {"method": "tools/call", "name": "rds_ListInstances"}
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Uvicorn (HTTP 服务器)                               │
│                          监听 0.0.0.0:8907                                   │
│                                                                             │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                    Starlette (ASGI 应用)                              │ │
│   │                                                                       │ │
│   │   ┌─────────────────────────────────────────────────────────────┐     │ │
│   │   │  HeadersMiddleware                                          │     │ │
│   │   │  提取 X-Access-Key / X-Secret-Key → contextvars             │     │ │
│   │   └─────────────────────────────────────────────────────────────┘     │ │
│   │         │                                                             │ │
│   │         ▼                                                             │ │
│   │   ┌─────────────────────────────────────────────────────────────┐     │ │
│   │   │  路由: /mcp → handle_streamable_http                        │     │ │
│   │   └─────────────────────────────────────────────────────────────┘     │ │
│   │         │                                                             │ │
│   │         ▼                                                             │ │
│   │   ┌─────────────────────────────────────────────────────────────┐     │ │
│   │   │  StreamableHTTPSessionManager                                │     │ │
│   │   │  解析 JSON-RPC，封装 SSE 响应                                │     │ │
│   │   └─────────────────────────────────────────────────────────────┘     │ │
│   │         │                                                             │ │
│   │         ▼                                                             │ │
│   │   ┌─────────────────────────────────────────────────────────────┐     │ │
│   │   │  Server (mcp 库)                                             │     │ │
│   │   │  路由: tools/list → list_tools()                             │     │ │
│   │   │  路由: tools/call → call_tool()                              │     │ │
│   │   └─────────────────────────────────────────────────────────────┘     │ │
│   │         │                                                             │ │
│   │         ▼                                                             │ │
│   │   ┌─────────────────────────────────────────────────────────────┐     │ │
│   │   │  MCPServer (业务逻辑)                                        │     │ │
│   │   │                                                             │     │ │
│   │   │  ┌─────────────────────────────────────────────────────┐     │     │ │
│   │   │  │  初始化阶段:                                          │     │     │ │
│   │   │  │                                                       │     │     │ │
│   │   │  │  config.yaml → service_codes: ["rds", "das"]          │     │     │ │
│   │   │  │                                                       │     │     │ │
│   │   │  │  循环加载:                                             │     │     │ │
│   │   │  │    rds.json → 232 工具 → 加前缀 → rds_ListInstances  │     │     │ │
│   │   │  │    das.json → 61 工具  → 加前缀 → das_ShowApiVersion │     │     │ │
│   │   │  │                                                       │     │     │ │
│   │   │  │  总计 293 工具                                         │     │     │ │
│   │   │  └─────────────────────────────────────────────────────┘     │     │ │
│   │   │                                                             │     │ │
│   │   │  ┌─────────────────────────────────────────────────────┐     │     │ │
│   │   │  │  call_tool 执行:                                     │     │     │ │
│   │   │  │                                                       │     │     │ │
│   │   │  │  ① 前缀路由: rds_ListInstances → service_code=rds   │     │     │ │
│   │   │  │  ② 去前缀:   rds_ListInstances → ListInstances      │     │     │ │
│   │   │  │  ③ 取 AK/SK: contextvars → headers → AK/SK          │     │     │ │
│   │   │  │  ④ 取 OpenAPI: openapi_dicts["rds"]                  │     │     │ │
│   │   │  │  ⑤ build_http_info(original_tool, ...)               │     │     │ │
│   │   │  │  ⑥ create_api_client(AK, SK, x_host, region)        │     │     │ │
│   │   │  │  ⑦ do_http_request(**http_info)                      │     │     │ │
│   │   │  └─────────────────────────────────────────────────────┘     │     │ │
│   │   └─────────────────────────────────────────────────────────────┘     │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        │  HTTPS (AK/SK 签名)
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         华为云 API                                          │
│                                                                             │
│   rds.cn-north-4.myhuaweicloud.com    →  RDS 服务 (232 API)                │
│   das.cn-north-4.myhuaweicloud.com    →  DAS 服务 (61 API)                 │
│   ecs.cn-north-4.myhuaweicloud.com    →  ECS 服务 (待扩展)                  │
│   ...                                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
mcp-server-rds-minimal/
│
├── assets/utils/              ← 公共核心代码
│   ├── model.py               ← MCPConfig (service_codes: List[str])
│   ├── hwc_tools.py           ← build_http_info, create_api_client, load_config
│   ├── server.py              ← MCPServer, HeadersMiddleware, call_tool
│   ├── openapi.py             ← OpenAPIToToolsConverter
│   └── variable.py            ← 常量定义
│
├── huaweicloud_services_server/
│   ├── mcp_gateway/           ← ★ 统一入口（新）
│   │   ├── run.py             ← 启动脚本
│   │   └── config/
│   │       ├── config.yaml    ← service_codes: ["rds", "das"]
│   │       └── openapi/
│   │           ├── rds.json   ← RDS OpenAPI
│   │           └── das.json   ← DAS OpenAPI
│   │
│   ├── mcp_server_rds/        ← RDS 单服务（保留）
│   │   └── config/rds.json
│   │
│   └── mcp_server_das/        ← DAS 单服务（保留）
│       └── config/das.json
│
└── docs/                      ← 文档
```

---

## 启动流程

```
python mcp_gateway/run.py
        │
        ▼
  asyncio.run(run_server(config_path))
        │
        ▼
  MCPServer(config_path).__init__()
        │
        ├─► load_config()        → service_codes: ["rds", "das"]
        │
        ├─► 循环加载每个服务:
        │     ├─► rds.json → 232 原始工具 → 加前缀 → rds_xxx
        │     ├─► das.json → 61 原始工具  → 加前缀 → das_xxx
        │     └─► 总计 293 工具，存入三个字典
        │
        ├─► _register_tool_handlers()
        │     ├─► @server.list_tools() → 返回 self.tools (293 带前缀)
        │     └─► @server.call_tool()  → 路由 + AK/SK + API调用
        │
        └─► run_http_server()
              ├─► StreamableHTTPSessionManager(app=self.server, stateless=True)
              ├─► Starlette(routes, lifespan, middleware)
              ├─► HeadersMiddleware → 提取 headers → contextvars
              └─► uvicorn.serve() → 监听 8907 端口
```

---

## 请求处理流程

```
客户端请求 POST /mcp/
        │
        ▼
  HeadersMiddleware 提取 AK/SK → contextvars
        │
        ▼
  session_manager 解析 JSON-RPC
        │
        ▼
  tools/list  ─────────────────►  返回 293 工具 (rds_xxx, das_xxx)
  tools/call  ─────────────────►  call_tool(name, arguments)
        │
        ├─① tool_service_map["rds_ListInstances"] → service_code = "rds"
        │
        ├─② name.replace("rds_", "") → original_name = "ListInstances"
        │
        ├─③ original_tools["rds"] → 找到 Tool 对象
        │
        ├─④ contextvars.get() → 获取 AK/SK
        │
        ├─⑤ openapi_dicts["rds"]["info"]["x-host"] → rds.cn-north-4.myhuaweicloud.com
        │
        ├─⑥ build_http_info(ListInstances, args, rds_openapi, rds_tools)
        │      → {"method": "GET", "resource_path": "/v3/instances", ...}
        │
        ├─⑦ create_api_client(AK, SK, x_host, region)
        │      → CustomClient (华为云 SDK)
        │
        └─⑧ client.do_http_request(**http_info)
               → HTTPS → rds.cn-north-4.myhuaweicloud.com/v3/instances
               → 返回 response
               → 封装为 MCP TextContent
               → 返回给客户端
```

---

## 三个核心字典

```
openapi_dicts          original_tools           tool_service_map
─────────              ───────────              ─────────────────
"rds" → rds.json       "rds" → [                "rds_ListInstances" → "rds"
"das" → das.json           Tool(name=              "rds_CreateInstance" → "rds"
                            "ListInstances"),       "das_ShowApiVersion" → "das"
                            Tool(name=              "das_ListFullSqlTasks" → "das"
                            "CreateInstance"),
                            ...232个],
                        "das" → [
                            Tool(name=
                            "ShowApiVersion"),
                            ...61个]

用途:                   用途:                    用途:
查 x-host 和            传给                     前缀路由
API 路径                 build_http_info          找到 service_code
```

---

## AK/SK 动态注入流程

```
  MCP 客户端发送 HTTP 请求
       │
       │  Headers 中携带:
       │  X-Access-Key: UAKXXXXXXXXXXXX
       │  X-Secret-Key: USKXXXXXXXXXXXX
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  HeadersMiddleware (ASGI 中间件)                         │
  │                                                         │
  │  scope["headers"] = [                                   │
  │    (b"content-type", b"application/json"),               │
  │    (b"x-access-key", b"UAKXXXXXXXXXXXX"),    ← bytes    │
  │    (b"x-secret-key", b"USKXXXXXXXXXXXX"),    ← bytes    │
  │  ]                                                      │
  │                                                         │
  │  处理:                                                   │
  │    ① 解码: key.decode() → "x-access-key"               │
  │    ② 解码: value.decode() → "UAKXXXXXXXXXXXX"          │
  │    ③ 存入: _request_headers.set({"x-access-key": ...})  │
  │                                                         │
  │  关键: 每个请求独立 context，互不干扰                     │
  └─────────────────────────────────────────────────────────┘
       │
       │ await self.app(scope, receive, send)  ← 放行请求
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  MCPServer.call_tool(name, arguments)                    │
  │                                                         │
  │  headers = _request_headers.get()  ← 从 contextvars 取  │
  │                                                         │
  │  AK = headers.get('x-access-key')    ← 最高优先级       │
  │      or headers.get('access-key')                         │
  │      or arguments.get('access_key')  ← 第二优先级       │
  │      or self.config.ak               ← 兜底             │
  │                                                         │
  │  SK = headers.get('x-secret-key')    ← 最高优先级       │
  │      or headers.get('secret-key')                         │
  │      or arguments.get('secret_key')  ← 第二优先级       │
  │      or self.config.sk               ← 兜底             │
  │                                                         │
  │  ① AK/SK → create_api_client(AK, SK, x_host, region)   │
  │     SDK 内部: AK/SK 签名请求，SK 不在网络传输            │
  │                                                         │
  │  ② client.do_http_request(**http_info)                   │
  │     HTTPS 加密 → 华为云 API                              │
  └─────────────────────────────────────────────────────────┘
       │
       │ HTTPS (AK/SK 签名认证)
       ▼
  华为云 API 验证签名 → 放行请求
```

---

## 网关路由机制

```
  客户端调用: name = "rds_ListInstances"
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Step 1: 前缀路由                                       │
  │                                                         │
  │  tool_service_map = {                                   │
  │    "rds_ListInstances"  → "rds",                        │
  │    "rds_CreateInstance" → "rds",                        │
  │    "das_ShowApiVersion" → "das",                        │
  │    ...                                                  │
  │  }                                                      │
  │                                                         │
  │  service_code = tool_service_map["rds_ListInstances"]   │
  │              = "rds"                                    │
  └─────────────────────────────────────────────────────────┘
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Step 2: 去前缀，找原始 Tool                             │
  │                                                         │
  │  original_name = "rds_ListInstances".replace("rds_","") │
  │               = "ListInstances"                         │
  │                                                         │
  │  original_tool = next(t for t in                        │
  │    self.original_tools["rds"] if t.name == "ListInstances")
  │                  = Tool(name="ListInstances", ...)       │
  └─────────────────────────────────────────────────────────┘
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Step 3: 取对应服务的 OpenAPI                            │
  │                                                         │
  │  openapi_dict = self.openapi_dicts["rds"]                │
  │                                                         │
  │  x_host = openapi_dict["info"]["x-host"]                 │
  │         = "rds.{region}.myhuaweicloud.com"              │
  │                                                         │
  │  为什么需要原始名?                                       │
  │  OpenAPI paths 用原始名定义:                             │
  │    "/ListInstances" → x-method="GET", x-url=...         │
  │  传入 "rds_ListInstances" 会找不到!                     │
  └─────────────────────────────────────────────────────────┘
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Step 4: 构建请求 + 调用华为云                           │
  │                                                         │
  │  build_http_info(original_tool.name, args,              │
  │                  openapi_dict, original_tools["rds"])    │
  │  → http_info = {method, resource_path, params, ...}     │
  │                                                         │
  │  create_api_client(AK, SK, x_host, region)              │
  │  → client (华为云 SDK)                                  │
  │                                                         │
  │  client.do_http_request(**http_info)                    │
  │  → HTTPS → rds.cn-north-4.myhuaweicloud.com            │
  └─────────────────────────────────────────────────────────┘
```

---

## AK/SK 获取优先级

```
  ┌─ Headers ────────────── 最高优先级 ──────────────┐
  │  X-Access-Key / X-Secret-Key                      │
  │  (每请求不同，支持多用户)                           │
  └───────────────────────────────────────────────────┘
        │ 没有？ ↓
  ┌─ 请求参数 ───────────── 第二优先级 ──────────────┐
  │  arguments.access_key / arguments.secret_key       │
  └───────────────────────────────────────────────────┘
        │ 没有？ ↓
  ┌─ 配置/环境变量 ──────── 兜底 ────────────────────┐
  │  config.yaml 的 ak/sk 或 HUAWEI_ACCESS_KEY 环境变量│
  │  (所有请求共用，测试用)                             │
  └───────────────────────────────────────────────────┘
```

---

## 添加新服务只需两步

```
步骤1: 放 OpenAPI 文件
  mcp_gateway/config/openapi/ecs.json

步骤2: 改 config.yaml
  service_codes: ["rds", "das", "ecs"]    ← 加一个就行

重启 → 自动加载 ECS 的 200+ 工具 → ecs_xxx
```

---

## 客户端使用方式

```json
{
  "mcpServers": {
    "huaweicloud": {
      "url": "http://localhost:8907/mcp/",
      "headers": {
        "X-Access-Key": "your_ak",
        "X-Secret-Key": "your_sk"
      }
    }
  }
}
```

客户端看到:
- `rds_ListInstances`  → 调用 RDS 查询实例列表
- `das_ShowApiVersion` → 调用 DAS 查询 API 版本
- `ecs_CreateServer`   → 调用 ECS 创建云服务器 (扩展后)

---

## 简要架构图

```
  MCP 客户端
  (Claude / Cursor / IDE)
       │
       │  POST /mcp/  (JSON-RPC)
       │  Headers: X-Access-Key=AK  X-Secret-Key=SK
       │
       ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                        MCP Gateway (:8907)                       │
  │                                                                  │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  ① Uvicorn (HTTP 服务器)                                   │ │
  │  │     接收 HTTP 请求 → 构建 ASGI scope                        │ │
  │  │     scope = {type:"http", headers:[(x-access-key, AK),...]} │ │
  │  └────────────────────────────────────────────────────────────┘ │
  │       │                                                          │
  │       ▼                                                          │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  ② HeadersMiddleware (中间层拦截)                            │ │
  │  │                                                             │ │
  │  │     遍历 scope["headers"] (bytes 格式)                      │ │
  │  │     key.decode() → "x-access-key"                           │ │
  │  │     val.decode() → "UAKXXXXXX"                              │ │
  │  │                                                             │ │
  │  │     _request_headers.set({"x-access-key":"AK",              │ │
  │  │                           "x-secret-key":"SK"})             │ │
  │  │     ↑ 存入 contextvars (每请求独立隔离)                      │ │
  │  │                                                             │ │
  │  │     await self.app(scope, receive, send)  ← 放行            │ │
  │  └────────────────────────────────────────────────────────────┘ │
  │       │                                                          │
  │       ▼                                                          │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  ③ Starlette 路由匹配                                       │ │
  │  │     path="/mcp" → handle_streamable_http                    │ │
  │  └────────────────────────────────────────────────────────────┘ │
  │       │                                                          │
  │       ▼                                                          │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  ④ StreamableHTTPSessionManager                             │ │
  │  │     解析 JSON-RPC: {method:"tools/call", params:{...}}      │ │
  │  └────────────────────────────────────────────────────────────┘ │
  │       │                                                          │
  │       ▼                                                          │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  ⑤ MCPServer.call_tool(name, arguments)                     │ │
  │  │                                                             │ │
  │  │     ┌── 网关路由 ──────────────────────────────────────┐   │ │
  │  │     │ tool_service_map["rds_ListInstances"] → "rds"    │   │ │
  │  │     │ name.replace("rds_","") → "ListInstances"        │   │ │
  │  │     │ original_tools["rds"] → 找到 Tool 对象           │   │ │
  │  │     │ openapi_dicts["rds"] → 取 x-host 和路径          │   │ │
  │  │     └──────────────────────────────────────────────────┘   │ │
  │  │                                                             │ │
  │  │     ┌── AK/SK 获取 (优先级) ──────────────────────────┐   │ │
  │  │     │  AK = headers["x-access-key"]  ← 最高           │   │ │
  │  │     │     or arguments["access_key"] ← 第二           │   │ │
  │  │     │     or self.config.ak          ← 兜底           │   │ │
  │  │     │  SK = headers["x-secret-key"]  ← 最高           │   │ │
  │  │     │     or arguments["secret_key"] ← 第二           │   │ │
  │  │     │     or self.config.sk          ← 兜底           │   │ │
  │  │     │  ↑ headers 来自 contextvars._request_headers   │   │ │
  │  │     └──────────────────────────────────────────────────┘   │ │
  │  │                                                             │ │
  │  │     ┌── 华为云调用 ───────────────────────────────────┐   │ │
  │  │     │ build_http_info(original_tool, args, openapi) → │   │ │
  │  │     │   {method:"GET", resource_path:"/v3/..."}      │   │ │
  │  │     │                                                    │   │ │
  │  │     │ create_api_client(AK, SK, x_host, region) →     │   │ │
  │  │     │   SDK 内部用 SK 签名请求 (SK 不在网络上传输)     │   │ │
  │  │     │                                                    │   │ │
  │  │     │ client.do_http_request(**http_info)               │   │ │
  │  │     └──────────────────────────────────────────────────┘   │ │
  │  └────────────────────────────────────────────────────────────┘ │
  └──────────────────────────────────────────────────────────────────┘
       │              │              │
       │ HTTPS        │ HTTPS        │ HTTPS
       │ AK/SK 签名认证│              │
       ▼              ▼              ▼
   ┌───────┐    ┌───────┐    ┌───────┐
   │  RDS  │    │  DAS  │    │  ECS  │
   │ 云API │    │ 云API │    │ 云API │
   └───────┘    └───────┘    └───────┘
   (已有)       (已有)       (扩展中)
```

---

## 数据流转简图

```
OpenAPI JSON ──► 转换 ──► MCP Tools ──► 加前缀 ──► 返回客户端
   │                                              │
   │              call_tool 请求到达               │
   │                                              ▼
   │           前缀路由 → 去前缀 → 找原始 Tool
   │                                      │
   │◄─────── openapi_dicts ──────────────┤
   │         original_tools              │
   │                                      │
   │              build_http_info ──► 华为云 SDK ──► 华为云 API
   │                                      │
   │                              response ──► 封装 MCP ──► 返回客户端
```