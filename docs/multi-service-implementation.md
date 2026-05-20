# MCP Server 多服务支持实现文档

## 一、概述

本次改造实现了 MCP Server 的多服务统一入口功能，允许客户端通过一个地址访问多个华为云服务的 MCP 工具。

### 改造目标

- 单一进程、单一端口加载多个服务
- 工具名加服务前缀避免冲突（如 `rds_ListInstances`、`das_ShowApiVersion`）
- 统一的 AK/SK 动态注入机制
- 简化的配置和启动方式

### 改造前后对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 服务数量 | 单服务（RDS） | 多服务（RDS + DAS + ...） |
| 启动方式 | 每个服务单独启动 | 一个入口启动所有服务 |
| 工具数量 | 232 个（RDS） | 293 个（RDS 232 + DAS 61） |
| 客户端连接 | 多个地址 | 单一地址 |
| 工具标识 | 无前缀 | 服务前缀（rds_、das_） |

---

## 二、目录结构

### 改造后的目录结构

```
mcp-server-rds-minimal/
├── assets/
│   └── utils/
│       ├── model.py          # 配置模型（已修改）
│       ├── hwc_tools.py      # 配置加载（已修改）
│       ├── server.py         # 核心服务（已修改）
│       └── ...
│
├── huaweicloud_services_server/
│   ├── mcp_gateway/          # 统一入口（新增）
│   │   ├── __init__.py
│   │   ├── run.py            # 启动入口
│   │   └── config/
│   │       ├── __init__.py
│   │       ├── config.yaml   # 多服务配置
│   │       └── openapi/      # OpenAPI 文件目录
│   │           ├── rds.json  # RDS OpenAPI
│   │           └── das.json  # DAS OpenAPI
│   │   └── src/
│   │       └── mcp_gateway/
│   │           └── __init__.py
│   │
│   ├── mcp_server_rds/       # RDS 服务（保留）
│   │   └── src/mcp_server_rds/
│   │       └── config/
│   │           └── rds.json
│   │
│   ├── mcp_server_das/       # DAS 服务（新增）
│   │   └── src/mcp_server_das/
│   │       └── config/
│   │           └── das.json
│   │
│   └── ...
│
├── .gitignore                # 新增
└── ...
```

---

## 三、文件修改详情

### 3.1 model.py（配置模型）

**文件路径**: `assets/utils/model.py`

**改动**: `service_code` → `service_codes`（支持多服务列表）

```python
# === 改动前 ===
from dataclasses import dataclass
from typing import Optional, Literal

TransportType = Literal["sse", "stdio", "http"]

@dataclass
class MCPConfig:
    port: int
    service_code: str              # 单个服务
    transport: TransportType
    ak: Optional[str] = None
    sk: Optional[str] = None

    def check(self):
        if not self.service_code:
            raise ValueError("service_code必须已经初始化")
        if self.transport in ("sse", "http") and self.port == 0:
            raise ValueError("sse和http服务端口不能设为0")

# === 改动后 ===
from dataclasses import dataclass
from typing import Optional, Literal, List

TransportType = Literal["sse", "stdio", "http"]

@dataclass
class MCPConfig:
    port: int
    service_codes: List[str]       # 多个服务列表
    transport: TransportType
    ak: Optional[str] = None
    sk: Optional[str] = None

    def check(self):
        if not self.service_codes:
            raise ValueError("service_codes 必须至少包含一个服务")
        if self.transport in ("sse", "http") and self.port == 0:
            raise ValueError("sse和http服务端口不能设为0")
```

---

### 3.2 hwc_tools.py（配置加载）

**文件路径**: `assets/utils/hwc_tools.py`

**改动**: `load_config` 函数兼容新旧配置格式

```python
# === 改动前 ===
def load_config(config_path: Union[str, Path]) -> MCPConfig:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"YAML 文件未找到: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"无效的 YAML 格式: {e}")

    try:
        cfg = MCPConfig(
            service_code=config_dict.get("service_code", ""),
            transport=config_dict.get("transport", ""),
            port=config_dict.get("port", 8888),
            ak=config_dict.get("ak", ""),
            sk=config_dict.get("sk", ""),
        )
        # ... 环境变量处理 ...

# === 改动后 ===
def load_config(config_path: Union[str, Path]) -> MCPConfig:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"YAML 文件未找到: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"无效的 YAML 格式: {e}")

    try:
        # 支持多服务配置 service_codes 或单服务配置 service_code（兼容）
        service_codes = config_dict.get("service_codes", [])
        if not service_codes:
            single_code = config_dict.get("service_code", "")
            if single_code:
                service_codes = [single_code]

        cfg = MCPConfig(
            service_codes=service_codes,  # 新字段
            transport=config_dict.get("transport", ""),
            port=config_dict.get("port", 8888),
            ak=config_dict.get("ak", ""),
            sk=config_dict.get("sk", ""),
        )
        # ... 环境变量处理 ...
```

---

### 3.3 server.py（核心服务）- 改动最大

**文件路径**: `assets/utils/server.py`

#### 改动 3.1：类属性新增多服务存储

```python
# === 改动前 ===
class MCPServer:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config: Optional[MCPConfig] = None
        self.server: Optional[Server] = None
        self.tools: list[Tool] = []
        self.initialized: bool = False
        self.openapi_dict: dict[str, Any] = {}  # 单个 OpenAPI

        self.active_clients: dict[str, Any] = {}
        self._clients_lock = asyncio.Lock()
        self.initialize()

# === 改动后 ===
class MCPServer:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config: Optional[MCPConfig] = None
        self.server: Optional[Server] = None
        self.tools: list[Tool] = []  # 带前缀的工具（返回给客户端）
        self.initialized: bool = False

        # 多服务存储
        self.openapi_dicts: dict[str, Any] = {}      # service_code → openapi
        self.original_tools: dict[str, list[Tool]] = {}  # service_code → 原始工具列表
        self.tool_service_map: dict[str, str] = {}  # prefixed_name → service_code

        self.active_clients: dict[str, Any] = {}
        self._clients_lock = asyncio.Lock()
        self.initialize()
```

#### 改动 3.2：initialize() 方法 - 循环加载多服务

```python
# === 改动前 ===
def initialize(self) -> None:
    """初始化服务器组件"""
    if self.initialized:
        return

    logger.info("开始初始化MCP服务器...")

    try:
        self.config = load_config(self.config_path)
        if not self.config:
            raise ValueError("无法加载服务器配置")

        self.server = Server(f"hwc-mcp-server-{self.config.service_code.lower()}")
        logger.info(f"初始化MCP服务器实例： hwc-mcp-server-{self.config.service_code.lower()}")

        # 加载单个 OpenAPI
        openapi_path = (
            Path(self.config_path.parent) / f"{self.config.service_code}.json"
        )
        self.openapi_dict = load_openapi(openapi_path)
        if not self.openapi_dict:
            raise ValueError(f"加载OpenAPI文档失败")

        # 转换为 MCP 工具
        self.tools = OpenAPIToToolsConverter(self.openapi_dict).convert()
        logger.info(f"成功加载 {len(self.tools)} 个工具")

        self._register_tool_handlers()
        self.initialized = True
        logger.info("MCP服务器初始化完成")

    except Exception as e:
        logger.error(f"服务器初始化失败: {e}")
        raise

# === 改动后 ===
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
        logger.info(f"初始化MCP服务器实例： hwc-mcp-server-{services_name}")

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
                raise ValueError(f"加载OpenAPI文档失败: {openapi_path}")

            # 保存 OpenAPI
            self.openapi_dicts[service_code] = openapi_dict

            # 转换为工具（原始版本，用于 build_http_info）
            original_tools = OpenAPIToToolsConverter(openapi_dict).convert()
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

        logger.info(f"总共加载 {len(self.tools)} 个工具，来自 {len(self.config.service_codes)} 个服务")

        self._register_tool_handlers()
        self.initialized = True
        logger.info("MCP服务器初始化完成")

    except Exception as e:
        logger.error(f"服务器初始化失败: {e}")
        raise
```

#### 改动 3.3：call_tool() 方法 - 根据前缀路由

```python
# === 改动前 ===
@self.server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[TextContent | ImageContent | EmbeddedResource]:
    region = arguments.get("region") or "cn-north-4"
    x_host = self.openapi_dict["info"]["x-host"]

    # AK/SK 获取...
    
    client = create_api_client(ak, sk, x_host, region)
    try:
        arguments = filter_parameters(arguments)
        http_info = build_http_info(
            name, arguments, self.openapi_dict, self.tools
        )
        response = client.do_http_request(**http_info)
        # ... 返回结果 ...

# === 改动后 ===
@self.server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[TextContent | ImageContent | EmbeddedResource]:
    # 根据带前缀的工具名找到服务
    service_code = self.tool_service_map.get(name)
    if not service_code:
        raise ToolError({
            "code": "UNKNOWN_TOOL",
            "message": f"工具 '{name}' 不存在",
        })

    # 获取原始工具名（去掉前缀）
    original_name = name.replace(f"{service_code}_", "")

    # 从原始工具列表中找到 Tool 对象
    original_tool = next(
        (t for t in self.original_tools[service_code] if t.name == original_name),
        None
    )
    if not original_tool:
        raise ToolError({
            "code": "TOOL_NOT_FOUND",
            "message": f"服务 '{service_code}' 中未找到工具 '{original_name}'",
        })

    # 获取对应服务的 OpenAPI
    openapi_dict = self.openapi_dicts[service_code]
    x_host = openapi_dict["info"]["x-host"]
    region = arguments.get("region") or "cn-north-4"

    # AK/SK 获取（不变）...
    
    client = create_api_client(ak, sk, x_host, region)
    try:
        arguments = filter_parameters(arguments)

        # 传入原始工具，build_http_info 完全不用改
        http_info = build_http_info(
            original_tool.name, arguments, openapi_dict, self.original_tools[service_code]
        )
        response = client.do_http_request(**http_info)
        # ... 返回结果 ...
```

---

### 3.4 config.yaml（配置文件）

**文件路径**: `huaweicloud_services_server/mcp_gateway/config/config.yaml`

```yaml
# MCP Gateway 统一配置
# 支持多个华为云服务的 MCP 工具

service_codes: ["rds", "das"]
transport: http  # 支持 stdio, http 和 sse
port: 8907  # 统一入口端口

# OpenAPI 文件位于 config/openapi/ 目录下：
# - rds.json
# - das.json
# 后续添加新服务只需：
# 1. 添加服务名到 service_codes
# 2. 将对应的 OpenAPI json 文件放入 openapi/ 目录
```

---

### 3.5 run.py（启动入口）

**文件路径**: `huaweicloud_services_server/mcp_gateway/run.py`

```python
"""
MCP Gateway 统一入口启动脚本
启动所有配置的 MCP 服务（RDS, DAS 等）
"""
import asyncio
from pathlib import Path

from assets.utils import run_server


def main():
    config_folder = Path(__file__).parent / "config"
    config_file = "config.yaml"
    asyncio.run(run_server(config_folder / config_file))


if __name__ == "__main__":
    main()
```

---

### 3.6 .gitignore

**文件路径**: `.gitignore`（项目根目录）

```gitignore
# Python 编译缓存
__pycache__/
*.py[cod]
*$py.class
*.so

# IDE 和工具配置
.claude/
.vscode/
.idea/

# 日志文件
*.log
logs/

# 环境变量和敏感信息
.env
*.env.local

# 虚拟环境
.venv/
venv/
ENV/

# 测试和覆盖率
.pytest_cache/
.coverage
htmlcov/

# 打包产物
dist/
build/
*.egg-info/
```

---

## 四、核心数据结构

### 4.1 多服务存储结构

```python
# openapi_dicts: 服务名 → OpenAPI 内容
self.openapi_dicts = {
    "rds": {...},  # rds.json 的完整内容
    "das": {...},  # das.json 的完整内容
}

# original_tools: 服务名 → 原始工具列表（不带前缀）
self.original_tools = {
    "rds": [
        Tool(name="ListInstances", description="查询实例列表", inputSchema={...}),
        Tool(name="CreateInstance", description="创建实例", inputSchema={...}),
        # ... 232 个工具
    ],
    "das": [
        Tool(name="ShowApiVersion", description="查询API版本", inputSchema={...}),
        Tool(name="ListFullSqlTasks", description="查询全量SQL任务", inputSchema={...}),
        # ... 61 个工具
    ],
}

# tool_service_map: 带前缀工具名 → 服务名
self.tool_service_map = {
    "rds_ListInstances": "rds",
    "rds_CreateInstance": "rds",
    "das_ShowApiVersion": "das",
    "das_ListFullSqlTasks": "das",
    # ... 293 个映射
}
```

### 4.2 双版本存储设计

```
OpenAPI 解析一次 → Tool.inputSchema
    ↓
┌─────────────────┬─────────────────┐
│                 │                 │
│ self.tools      │ self.original_  │
│ (带前缀)        │ tools           │
│                 │ (不带前缀)      │
│                 │                 │
│ 同一个          │ 同一个          │
│ inputSchema     │ inputSchema     │
│                 │                 │
│ 用于 tools/list │ 用于 call_tool  │
│ 返回给客户端    │ build_http_info │
└─────────────────┴─────────────────┘
```

**关键点**: `build_http_info` 函数完全不需要修改，因为传入的是原始 Tool 对象，保持了 schema 一致性。

---

## 五、build_http_info 调用对比

### 函数定义（未改动）

```python
def build_http_info(name, arguments, openapi_spec, mcp_tools):
    # 根据 Path name 找到调用的 Tool
    invoked_tool = next((tool for tool in mcp_tools if tool.name == name), None)
    ...
```

### 参数对比

| 参数 | 改动前 | 改动后 | 说明 |
|------|--------|--------|------|
| `name` | `"ListInstances"`（客户端直接传） | `"ListInstances"`（去掉前缀后的原始名） | **逻辑相同** |
| `arguments` | arguments 字典 | arguments 字典 | **不变** |
| `openapi_spec` | `self.openapi_dict`（单个） | `self.openapi_dicts["rds"]`（按服务取） | **多服务时按服务取** |
| `mcp_tools` | `self.tools`（带前缀） | `self.original_tools["rds"]`（不带前缀） | **用原始列表查找** |

### build_http_info 返回值

```python
http_info = {
    "method": "GET",
    "resource_path": "/v3/{project_id}/instances",
    "path_params": {"project_id": "xxx"},
    "query_params": {"limit": 10},
    "header_params": {"Content-Type": "application/json;charset=UTF-8"},
    "body": {},
    ...
}
```

---

## 六、启动和使用方式

### 6.1 启动服务

```bash
# 运行这一个脚本，启动所有 MCP 服务
python huaweicloud_services_server/mcp_gateway/run.py
```

### 6.2 客户端连接

```json
// MCP 客户端配置
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

### 6.3 工具调用示例

```bash
# 调用 RDS 工具
curl -X POST http://localhost:8907/mcp/ \
  -H "X-Access-Key: your_ak" \
  -H "X-Secret-Key: your_sk" \
  -d '{"method":"tools/call","params":{"name":"rds_ListInstances","arguments":{...}}}'

# 调用 DAS 工具
curl -X POST http://localhost:8907/mcp/ \
  -H "X-Access-Key: your_ak" \
  -H "X-Secret-Key: your_sk" \
  -d '{"method":"tools/call","params":{"name":"das_ShowApiVersion","arguments":{...}}}'
```

---

## 七、添加新服务

### 步骤

1. 将 OpenAPI 文件复制到 `mcp_gateway/config/openapi/` 目录
2. 修改 `config.yaml` 中的 `service_codes`

```yaml
# 添加 ECS 服务
service_codes: ["rds", "das", "ecs"]
```

3. 重启服务即可

---

## 八、工具名前缀设计

### 为什么需要前缀

| 原因 | 说明 |
|------|------|
| **避免冲突** | 不同服务可能有同名工具（如 `ListInstances`） |
| **清晰标识** | 客户端一眼看出工具属于哪个服务 |
| **路由简单** | 通过前缀直接映射到服务名 |

### 前缀对用户体验的影响

**无影响**：客户端通过 `tools/list` 自动获取工具名，无需手动输入前缀。

```
客户端流程：
tools/list → 收到 "rds_ListInstances" → 直接用这个名字调用
```

---

## 九、AK/SK 动态注入

### Headers 中间件（已在 server.py 中实现）

```python
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
        await self.app(scope, receive, send)
```

### AK/SK 获取优先级

```
Headers (X-Access-Key/X-Secret-Key) → 最高优先级
请求参数 (access_key/secret_key) → 第二优先级
配置/环境变量 → 兜底
```

---

## 十、改动总结

| 维度 | 数据 |
|------|------|
| 修改文件 | 3 个（model.py, hwc_tools.py, server.py） |
| 新建文件 | 约 10 个（mcp_gateway 目录 + .gitignore） |
| 代码行数 | 约 80 行新增/修改 |
| 核心改动 | server.py 多服务加载和路由逻辑 |

---

## 十一、Git 提交记录

```
multi-service-support 分支：
├── 313e6bd 添加 DAS MCP 服务和 .gitignore
├── e70a68b 创建 MCP Gateway 统一入口
├── c079093 支持多服务动态加载
└── 56a55fc 更新测试脚本 (main)
```

---

## 十二、测试验证

### 启动日志

```
开始初始化MCP服务器...
初始化MCP服务器实例： hwc-mcp-server-rds-das
加载服务 rds，OpenAPI路径: .../openapi/rds.json
服务 rds 加载完成，工具数: 232
加载服务 das，OpenAPI路径: .../openapi/das.json
服务 das 加载完成，工具数: 61
总共加载 293 个工具，来自 2 个服务
MCP服务器初始化完成
Uvicorn running on http://0.0.0.0:8907
```

### tools/list 返回

```json
{
  "tools": [
    {"name": "rds_ListInstances", "description": "[RDS] 查询实例列表"},
    {"name": "rds_CreateInstance", "description": "[RDS] 创建实例"},
    {"name": "das_ShowApiVersion", "description": "[DAS] 查询API版本"},
    {"name": "das_ListFullSqlTasks", "description": "[DAS] 查询全量SQL任务"},
    ...
  ]
}
```

---

## 十三、注意事项

1. **OpenAPI 文件同步**: 各服务目录的 OpenAPI 文件需手动同步到 `mcp_gateway/config/openapi/`
2. **工具名冲突**: 前缀机制已避免冲突，无需担心
3. **向后兼容**: 旧的单服务配置（`service_code`）仍然可用
4. **schema 一致性**: 双版本存储确保 `build_http_info` 无需修改