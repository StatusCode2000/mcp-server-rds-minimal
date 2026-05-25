---
name: uvicorn-http-architecture
description: Uvicorn 启动架构及两层 HTTP 请求流程
---

# Uvicorn HTTP 架构

## 核心概念

本项目使用 **两层 HTTP** 架构：
- **外层 HTTP**: MCP 客户端 → Uvicorn（MCP JSON-RPC 协议）
- **内层 HTTP**: MCPServer → 华为云 API（华为云 REST API）

## Uvicorn 启动内容

```python
# assets/utils/server.py run_http_server()
starlette_app = Starlette(
    routes=[Mount("/mcp", app=handle_streamable_http)],
    lifespan=lifespan,
)
starlette_app.add_middleware(HeadersMiddleware)

http_config = uvicorn.Config(starlette_app, host="0.0.0.0", port=self.config.port)
http_server = uvicorn.Server(http_config)
await http_server.serve()
```

Uvicorn 启动的是 **Starlette ASGI 应用**，监听指定端口（默认 8907）。

## 组件层级

```
Uvicorn (HTTP 服务器)
    │  监听端口，处理 HTTP 连接
    │
    ▼
Starlette (ASGI 应用框架)
    │  路由分发、中间件处理
    │
    ├── HeadersMiddleware
    │      提取 HTTP headers → contextvars
    │
    ├── /mcp 路由
    │      │
    │      ▼
    │  StreamableHTTPSessionManager
    │      MCP 协议处理，JSON-RPC 解析
    │      │
    │      ▼
    │  Server (mcp 库)
    │      工具路由：list_tools / call_tool
    │      │
    │      ▼
    │  MCPServer.call_tool()
    │      业务逻辑：AK/SK 获取、华为云 API 调用
    │      │
    │      ▼
    │  华为云 SDK Client
    │      build_http_info() → 构建 HTTP 请求参数
    │      do_http_request() → 发送 HTTP 请求
    │
    ▼
华为云 API 服务器
    https://rds.cn-north-4.myhuaweicloud.com/v3/instances
```

## 两层 HTTP 对比

### 外层 HTTP（MCP 协议）

| 属性 | 值 |
|------|---|
| 方向 | MCP 客户端 → Uvicorn |
| URL | `http://localhost:8907/mcp/` |
| 格式 | JSON-RPC 2.0 |
| Content-Type | `application/json` |
| Accept | `application/json, text/event-stream` |

请求示例：
```json
POST http://localhost:8907/mcp/
Content-Type: application/json
Accept: application/json, text/event-stream

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "rds_ListInstances",
    "arguments": {
      "project_id": "xxx",
      "region": "cn-north-4"
    }
  }
}
```

响应示例（SSE 格式）：
```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"instances\":[]}"}]}}
```

### 内层 HTTP（华为云 API）

| 属性 | 值 |
|------|---|
| 方向 | MCPServer → 华为云服务器 |
| URL | `https://rds.{region}.myhuaweicloud.com/v3/{project_id}/instances` |
| 格式 | REST API |
| 认证 | AK/SK 签名 |

请求构建流程：
```python
# 1. build_http_info() 构建 HTTP 参数
http_info = {
    "method": "GET",
    "resource_path": "/v3/{project_id}/instances",
    "path_params": {"project_id": "xxx"},
    "query_params": {},
    "header_params": {"Content-Type": "application/json"},
    "body": {},
}

# 2. client.do_http_request() 发送请求
response = client.do_http_request(**http_info)
# SDK 内部：
#   - 使用 AK/SK 对请求签名
#   - 发送 HTTPS 请求到华为云
#   - 返回响应
```

## 请求处理流程

```
1. MCP 客户端发送 HTTP 请求
   POST /mcp/ {"method": "tools/call", "params": {"name": "rds_ListInstances"}}
   
2. Uvicorn 接收请求，传递给 Starlette

3. HeadersMiddleware 提取 headers
   X-Access-Key, X-Secret-Key → contextvars

4. StreamableHTTPSessionManager 解析 JSON-RPC

5. Server 路由到 call_tool 处理函数

6. MCPServer.call_tool() 执行业务逻辑
   a. 从 contextvars 获取 AK/SK
   b. 根据工具名前缀路由到对应服务 (rds_)
   c. build_http_info() 构建华为云请求参数
   d. create_api_client() 创建华为云 SDK 客户端
   e. client.do_http_request() 调用华为云 API

7. 华为云返回响应

8. MCPServer 将响应封装为 MCP 格式返回

9. StreamableHTTPSessionManager 封装为 SSE 格式

10. Uvicorn 返回 HTTP 响应给 MCP 客户端
```

## 关键文件

| 文件 | 职责 |
|------|------|
| `assets/utils/server.py` | MCPServer 类、run_http_server()、中间件 |
| `assets/utils/hwc_tools.py` | build_http_info()、create_api_client()、do_http_request() |
| `huaweicloud_services_server/mcp_gateway/run.py` | 入口，启动 MCPServer |

## 相关文档

- [[multi-service-implementation]] - 多服务架构实现
- [[ak-sk-dynamic-injection]] - AK/SK 动态注入机制
- [[http-request-sequence]] - HTTP 请求时序图