# AK/SK 动态注入实现文档

## 一、概述

本次改造实现了 MCP Server 的 AK/SK 动态注入功能，允许客户端通过 HTTP Headers 传递华为云认证信息，实现每次请求独立认证。

### 功能目标

- 支持通过 HTTP Headers 传递 AK/SK
- 支持通过请求参数传递 AK/SK
- 保持配置文件/环境变量的兜底机制
- 认证信息获取优先级：Headers > 请求参数 > 配置/环境变量

### 应用场景

| 场景 | 说明 |
|------|------|
| 多租户系统 | 不同用户使用不同的 AK/SK |
| 安全审计 | 每次请求独立认证，便于追踪 |
| 临时访问 | 无需修改配置文件即可访问 |

---

## 二、技术方案

### 核心技术：contextvars

使用 Python 的 `contextvars` 模块在异步请求链中传递 Headers：

```
HTTP 请求到达
    ↓
HeadersMiddleware 提取 Headers
    ↓
存入 contextvars（请求上下文变量）
    ↓
call_tool() 从 contextvars 获取
    ↓
用于华为云 API 认证
```

### 为什么选择 contextvars

| 原因 | 说明 |
|------|------|
| **异步安全** | Python asyncio 环境下，每个请求有独立的上下文 |
| **线程安全** | 不会跨请求污染数据 |
| **简洁** | 无需手动传递参数，自动继承 |

---

## 三、文件修改详情

### 3.1 server.py - 核心改动

**文件路径**: `assets/utils/server.py`

#### 改动 1：顶部添加导入和上下文变量定义

```python
# === 新增代码（第 8-11 行）===
import contextvars

# 定义请求上下文变量，存储当前请求的 headers
_request_headers: contextvars.ContextVar[dict] = contextvars.ContextVar('request_headers', default={})
```

**位置说明**：

```python
# server.py 顶部
import asyncio
import contextlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional, AsyncIterator
import contextvars  # ← 新增

# 定义请求上下文变量，存储当前请求的 headers
_request_headers: contextvars.ContextVar[dict] = contextvars.ContextVar('request_headers', default={})  # ← 新增

import uvicorn
# ... 其他导入
```

---

#### 改动 2：添加 HeadersMiddleware 中间件类

```python
# === 新增代码（第 41-53 行）===
class HeadersMiddleware:
    """提取 HTTP headers 并存入上下文变量"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers_dict = {}
            for key, value in scope.get('headers', []):
                header_name = key.decode('utf-8').lower()
                header_value = value.decode('utf-8')
                headers_dict[header_name] = header_value
            _request_headers.set(headers_dict)
        await self.app(scope, receive, send)
```

**位置说明**：放在 `MCPServer` 类定义之前，logger 配置之后。

---

#### 改动 3：在 HTTP app 上注册中间件

```python
# === 改动前 ===
starlette_app = Starlette(
    debug=True,
    routes=[
        Mount("/mcp", app=handle_streamable_http),
    ],
    lifespan=lifespan,
)

# === 改动后 ===
starlette_app = Starlette(
    debug=True,
    routes=[
        Mount("/mcp", app=handle_streamable_http),
    ],
    lifespan=lifespan,
)

# 添加 headers 中间件（新增）
starlette_app.add_middleware(HeadersMiddleware)
```

**位置说明**：在 `run_http_server()` 方法中，`Starlette` 创建之后，`uvicorn.Config` 创建之前。

---

#### 改动 4：修改 call_tool() 函数中的 AK/SK 获取逻辑

```python
# === 改动前 ===
@self.server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[TextContent | ImageContent | EmbeddedResource]:
    region = arguments.get("region") or "cn-north-4"
    x_host = self.openapi_dict["info"]["x-host"]

    ak = self.config.ak  # 直接从配置获取
    sk = self.config.sk

    if not ak or not sk:
        error_msg = {
            "code": "MISSING_CREDENTIALS",
            "message": "HUAWEI_ACCESS_KEY or HUAWEI_SECRET_KEY not configured",
        }
        raise ToolError(error_msg)

# === 改动后 ===
@self.server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[TextContent | ImageContent | EmbeddedResource]:
    # ... 服务路由逻辑 ...
    
    region = arguments.get("region") or "cn-north-4"
    x_host = openapi_dict["info"]["x-host"]

    # 从上下文变量获取 headers（新增）
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

    if not ak or not sk:
        error_msg = {
            "code": "MISSING_CREDENTIALS",
            "message": "请在请求 Headers 中提供 X-Access-Key 和 X-Secret-Key 或配置 HUAWEI_ACCESS_KEY 和 HUAWEI_SECRET_KEY",
        }
        raise ToolError(error_msg)
```

---

### 3.2 完整修改位置汇总

| 修改位置 | 行号（参考） | 修改内容 |
|----------|-------------|----------|
| 顶部导入 | 第 8 行 | `import contextvars` |
| 上下文变量定义 | 第 10-11 行 | `_request_headers` 定义 |
| HeadersMiddleware 类 | 第 41-53 行 | 新增中间件类 |
| HTTP app 注册中间件 | 第 338 行 | `starlette_app.add_middleware(HeadersMiddleware)` |
| call_tool() AK/SK 获取 | 第 144-166 行 | 优先级获取逻辑 |

---

## 四、Headers 字段命名

### 支持的 Header 名称

| Header 名称 | 说明 | 推荐程度 |
|-------------|------|----------|
| `X-Access-Key` | Access Key ID | ⭐⭐⭐ 推荐 |
| `X-Secret-Key` | Secret Key | ⭐⭐⭐ 推荐 |
| `Access-Key` | 无 X- 前缀 | ⭐⭐ 兼容支持 |
| `Secret-Key` | 无 X- 前缀 | ⭐⭐ 兼容支持 |

### Header 命名规范

推荐使用带 `X-` 前缀的标准命名：

```
X-Access-Key: your_access_key_id
X-Secret-Key: your_secret_key
```

**原因**：
- `X-` 前缀是 HTTP 自定义 Header 的常见惯例
- 避免与标准 HTTP Header 冲突
- 更容易识别为自定义认证信息

---

## 五、认证优先级

### 获取顺序

```
1. Headers (X-Access-Key/X-Secret-Key)
   ↓ 如果不存在
   
2. 请求参数 (access_key/secret_key)
   ↓ 如果不存在
   
3. 配置文件 (config.yaml 中的 ak/sk)
   ↓ 如果不存在
   
4. 环境变量 (HUAWEI_ACCESS_KEY/HUAWEI_SECRET_KEY)
   ↓ 如果仍不存在
   
报错：MISSING_CREDENTIALS
```

### 优先级表格

| 来源 | 字段名 | 优先级 | 适用场景 |
|------|--------|--------|----------|
| HTTP Headers | `X-Access-Key` / `X-Secret-Key` | 1（最高） | 每次请求独立认证 |
| 请求参数 | `access_key` / `secret_key` | 2 | MCP 协议参数传递 |
| 配置文件 | `ak` / `sk` | 3 | 默认配置 |
| 环境变量 | `HUAWEI_ACCESS_KEY` / `HUAWEI_SECRET_KEY` | 4 | 系统级配置 |

---

## 六、使用示例

### 6.1 通过 Headers 传递 AK/SK

```bash
curl -X POST http://localhost:8907/mcp/ \
  -H "X-Access-Key: your_access_key" \
  -H "X-Secret-Key: your_secret_key" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "rds_ListInstances",
      "arguments": {
        "region": "cn-north-4",
        "project_id": "your_project_id"
      }
    }
  }'
```

### 6.2 通过请求参数传递 AK/SK

```bash
curl -X POST http://localhost:8907/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "rds_ListInstances",
      "arguments": {
        "region": "cn-north-4",
        "project_id": "your_project_id",
        "access_key": "your_access_key",
        "secret_key": "your_secret_key"
      }
    }
  }'
```

### 6.3 MCP 客户端配置

```json
{
  "mcpServers": {
    "huaweicloud-rds": {
      "url": "http://localhost:8907/mcp/",
      "headers": {
        "X-Access-Key": "your_access_key",
        "X-Secret-Key": "your_secret_key"
      }
    }
  }
}
```

### 6.4 Python 客户端示例

```python
import requests

MCP_URL = "http://localhost:8907/mcp/"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "X-Access-Key": "your_access_key",
    "X-Secret-Key": "your_secret_key",
}

# 初始化连接
response = requests.post(
    MCP_URL,
    headers=HEADERS,
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        }
    }
)

# 调用工具
response = requests.post(
    MCP_URL,
    headers=HEADERS,
    json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "rds_ListInstances",
            "arguments": {
                "region": "cn-north-4",
                "project_id": "your_project_id"
            }
        }
    }
)
```

---

## 七、测试验证

### 7.1 测试场景

| 测试项 | 测试方法 | 预期结果 |
|--------|----------|----------|
| Headers AK/SK | 传递正确的 Headers | ✅ API 调用成功 |
| Headers 假 AK/SK | 传递错误的 Headers | ❌ 401 Unauthorized（证明使用了 Headers） |
| 参数 AK/SK | 在 arguments 中传递 | ✅ API 调用成功 |
| 无 AK/SK | 不传递任何认证信息 | ❌ MISSING_CREDENTIALS 错误 |
| 优先级验证 | Headers 正确 + 参数错误 | ✅ 使用 Headers（调用成功） |

### 7.2 测试命令

```bash
# 测试 1：Headers AK/SK（假值，验证提取逻辑）
curl -X POST http://localhost:8907/mcp/ \
  -H "X-Access-Key: fake_ak" \
  -H "X-Secret-Key: fake_sk" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"rds_ListInstances","arguments":{"region":"cn-north-4","project_id":"test"}}}'

# 预期返回：401 Unauthorized（证明 Headers AK/SK 被正确提取）
```

### 7.3 测试结果示例

```json
// Headers 传递假 AK/SK 的返回
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{
      "type": "text",
      "text": "SdkException - ... ClientRequestException - {status_code:401,error_code:APIGW.0301,error_msg:Incorrect IAM authentication information: Unauthorized}"
    }],
    "isError": true
  }
}
```

**说明**：返回 401 错误证明 Headers 中的假 AK/SK 被正确提取并用于 API 认证。

---

## 八、架构说明

### 8.1 HTTP 模式 vs SSE 模式

| 模式 | Headers 提取 | 动态 AK/SK 支持 |
|------|-------------|----------------|
| HTTP 模式 | ✅ HeadersMiddleware | ✅ 每次请求独立 |
| SSE 模式 | ⚠️ 需补充中间件 | ⚠️ 初始连接可用，POST 消息需补充 |
| STDIO 模式 | ❌ 无 HTTP Headers | ❌ 无法支持 |

### 8.2 HTTP 模式下的请求流程

```
客户端 HTTP 请求
    ↓
Starlette 接收请求
    ↓
HeadersMiddleware（中间件）
    ↓
提取 Headers → 存入 _request_headers
    ↓
StreamableHTTPSessionManager
    ↓
MCP 协议处理
    ↓
call_tool()
    ↓
从 _request_headers.get() 获取 Headers
    ↓
提取 AK/SK → 创建 API Client
    ↓
调用华为云 API
```

### 8.3 SSE 模式的补充说明

如果需要 SSE 模式也支持动态 AK/SK，需要在 SSE app 上也添加中间件：

```python
# run_sse_server() 方法中
app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse_connection),
        Mount("/messages/", app=sse.handle_post_message),
    ],
    debug=True,
)

# 添加 headers 中间件（补充）
app.add_middleware(HeadersMiddleware)

# 添加 CORS 中间件
app.add_middleware(CORSMiddleware, ...)
```

---

## 九、安全注意事项

### 9.1 Header 传输安全

| 注意点 | 说明 |
|--------|------|
| **HTTPS** | 生产环境必须使用 HTTPS，防止 Headers 明文传输 |
| **日志脱敏** | 日志中不应记录完整的 AK/SK |
| **临时存储** | contextvars 仅在请求期间有效，请求结束自动清理 |

### 9.2 推荐做法

```python
# 日志脱敏示例
if ak:
    logger.info(f"使用 AK: {ak[:8]}... (已截断)")  # 只显示前 8 位
```

### 9.3 不推荐的做法

```python
# 错误示例：完整记录 AK/SK
logger.info(f"AK: {ak}, SK: {sk}")  # ❌ 安全风险
```

---

## 十、错误处理

### 10.1 MISSING_CREDENTIALS 错误

当没有任何认证信息时返回：

```json
{
  "code": "MISSING_CREDENTIALS",
  "message": "请在请求 Headers 中提供 X-Access-Key 和 X-Secret-Key 或配置 HUAWEI_ACCESS_KEY 和 HUAWEI_SECRET_KEY"
}
```

### 10.2 认证失败错误

当 AK/SK 无效时，华为云 API 返回：

```json
{
  "status_code": 401,
  "error_code": "APIGW.0301",
  "error_msg": "Incorrect IAM authentication information: Unauthorized"
}
```

---

## 十一、与多服务的兼容性

### AK/SK 注入在多服务架构中的位置

```
mcp_gateway 统一入口
    ↓
HeadersMiddleware 提取 Headers（对所有服务生效）
    ↓
call_tool() 根据工具名路由到具体服务
    ↓
从 headers 获取 AK/SK（统一的优先级逻辑）
    ↓
创建对应服务的 API Client
    ↓
调用该服务的华为云 API
```

**关键点**：AK/SK 注入逻辑对所有服务通用，无需为每个服务单独配置。

---

## 十二、总结

### 改动清单

| 文件 | 改动行数 | 说明 |
|------|---------|------|
| `server.py` | 约 25 行 | 导入、中间件、AK/SK 获取逻辑 |

### 核心改动

1. **导入 contextvars**：定义请求上下文变量
2. **HeadersMiddleware**：提取 HTTP Headers
3. **中间件注册**：HTTP app 添加中间件
4. **call_tool()**：优先级获取 AK/SK

### 技术要点

- 使用 `contextvars` 实现异步安全的 Headers 传递
- 中间件模式统一提取 Headers
- 多级优先级保证灵活性
- HTTP 模式完全支持，SSE 需补充

---

## 十三、相关文档

- [多服务实现文档](multi-service-implementation.md)
- [测试脚本](../test_mcp_server.py)