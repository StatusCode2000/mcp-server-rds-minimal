---
name: http-request-sequence
description: 从 HTTPS 请求到客户端收到返回的完整顺序图
---

# HTTPS 请求完整时序图

## 从发送请求到客户端收到返回

```
  MCP 客户端                Uvicorn               Starlette             HeadersMiddleware        SessionManager          mcp Server           MCPServer            华为云SDK             华为云API
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │  POST /mcp/            │                     │                     │                       │                     │                   │                    │                    │
     │  JSON-RPC body         │                     │                     │                       │                     │                   │                    │                    │
     │  Headers:              │                     │                     │                       │                     │                   │                    │                    │
     │  X-Access-Key=AK       │                     │                     │                       │                     │                   │                    │                    │
     │  X-Secret-Key=SK       │                     │                     │                       │                     │                   │                    │                    │
     │──────────────────────►│                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │ 接收TCP连接          │                     │                       │                     │                   │                    │                    │
     │                        │ 解析HTTP请求         │                     │                       │                     │                   │                    │                    │
     │                        │ 构建ASGI scope      │                     │                       │                     │                   │                    │                    │
     │                        │────────────────────►│                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │ Starlette.__call__ │                       │                     │                   │                    │                    │
     │                        │                     │────────────────────►│                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │ 遍历scope["headers"]   │                     │                   │                    │                    │
     │                        │                     │                     │ decode bytes→string    │                     │                   │                    │                    │
     │                        │                     │                     │                        │                     │                   │                    │                    │
     │                        │                     │                     │ _request_headers.set() │                     │                   │                    │                    │
     │                        │                     │                     │ {"x-access-key":AK,    │                     │                   │                    │                    │
     │                        │                     │                     │  "x-secret-key":SK}    │                     │                   │                    │                    │
     │                        │                     │                     │                        │                     │                   │                    │                    │
     │                        │                     │                     │────────────────────────►│                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │ 路由匹配             │                   │                    │                    │
     │                        │                     │                     │                       │ /mcp → handle_req   │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │────────────────────►│                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │ 解析JSON-RPC      │                    │                    │
     │                        │                     │                     │                       │                     │ method:tools/call │                    │                    │
     │                        │                     │                     │                       │                     │──────────────────►│                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ①前缀路由          │                    │
     │                        │                     │                     │                       │                     │                   │ rds_ListInstances  │                    │
     │                        │                     │                     │                       │                     │                   │ → service_code=rds │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ②去前缀            │                    │
     │                        │                     │                     │                       │                     │                   │ → ListInstances    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ③找原始Tool        │                    │
     │                        │                     │                     │                       │                     │                   │ original_tools[rds] │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ④取AK/SK           │                    │
     │                        │                     │                     │                       │                     │                   │ _request_headers    │                    │
     │                        │                     │                     │                       │                     │                   │ .get() → AK, SK    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ⑤取OpenAPI         │                    │
     │                        │                     │                     │                       │                     │                   │ openapi_dicts[rds]  │                    │
     │                        │                     │                     │                       │                     │                   │ → x-host           │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ⑥build_http_info() │                    │
     │                        │                     │                     │                       │                     │                   │ → http_info字典    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ ⑦create_api_client │                    │
     │                        │                     │                     │                       │                     │                   │ (AK,SK,x_host)    │                    │
     │                        │                     │                     │                       │                     │                   │──────────────────►│                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │ AK/SK签名请求      │
     │                        │                     │                     │                       │                     │                   │                    │ SK不在网络传输     │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │ HTTPS请求          │
     │                        │                     │                     │                       │                     │                   │                    │──────────────────►│
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │ 华为云处理请求
     │                        │                     │                     │                       │                     │                   │                    │                    │ 验证签名
     │                        │                     │                     │                       │                     │                   │                    │                    │ 返回JSON
     │                        │                     │                     │                       │                     │                   │                    │◄──────────────────│
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │ response对象       │
     │                        │                     │                     │                       │                     │                   │◄──────────────────│                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │ 封装TextContent    │                    │
     │                        │                     │                     │                       │                     │◄──────────────────│                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │ 封装MCP格式         │                   │                    │                    │
     │                        │                     │                     │                       │ {jsonrpc,result}    │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │ 封装SSE格式         │                   │                    │                    │
     │                        │                     │                     │                       │ event:message       │                   │                    │                    │
     │                        │                     │                     │                       │ data:{...}          │                   │                    │                    │
     │                        │                     │                     │◄────────────────────────│                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │ 中间件放行响应       │                       │                     │                   │                    │                    │
     │                        │◄────────────────────│                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │                        │ 发送HTTP响应         │                     │                       │                     │                   │                    │                    │
     │◄──────────────────────│                     │                     │                       │                     │                   │                    │                    │
     │                        │                     │                     │                       │                     │                   │                    │                    │
     │  客户端收到响应         │                     │                     │                       │                     │                   │                    │                    │
     │  SSE: event:message    │                     │                     │                       │                     │                   │                    │                    │
     │  data: {result:{...}}  │                     │                     │                       │                     │                   │                    │                    │
     ▼                        ▼                     ▼                     ▼                       ▼                     ▼                   ▼                    ▼                    ▼
```

---

## 时序编号说明

| 序号 | 步骤 | 说明 |
|------|------|------|
| ① | 前缀路由 | `rds_ListInstances` → `tool_service_map["rds"]` → `service_code = "rds"` |
| ② | 去前缀 | `name.replace("rds_", "")` → `original_name = "ListInstances"` |
| ③ | 找原始 Tool | `original_tools["rds"]` 中查找 `Tool(name="ListInstances")` |
| ④ | 取 AK/SK | `_request_headers.get()` → headers 优先级获取 |
| ⑤ | 取 OpenAPI | `openapi_dicts["rds"]` → `x-host = "rds.{region}.myhuaweicloud.com"` |
| ⑥ | 构建请求 | `build_http_info()` → `{method, resource_path, params, ...}` |
| ⑦ | 创建客户端 | `create_api_client(AK, SK, x_host, region)` → 华为云 SDK Client |
| ⑧ | AK/SK 签名 | SDK 内部用 SK 签名请求，SK 不在网络传输 |
| ⑨ | HTTPS 请求 | `client.do_http_request()` → 华为云 API |
| ⑩ | 返回响应 | 华为云 → SDK → MCPServer → 封装 MCP → 封装 SSE → 客户端 |