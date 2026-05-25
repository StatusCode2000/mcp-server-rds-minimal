---
name: add-new-mcp-service
description: 新增 MCP 服务的完整步骤指南
---

# 新增 MCP 服务指南

## 概述

将新的华为云服务添加到 MCP Gateway，只需 3-4 个步骤。

---

## 步骤清单

| 步骤 | 必需/可选 | 说明 |
|------|----------|------|
| ① 添加 OpenAPI 文件 | **必需** | 服务的 API 定义 |
| ② 修改 config.yaml | **必需** | 注册服务名 |
| ③ 创建过滤配置 | 可选 | 限制暴露的工具 |
| ④ 重启服务 | **必需** | 加载新配置 |

---

## 步骤 ① 添加 OpenAPI 文件

### 文件来源

OpenAPI 文件定义了服务的所有 API 接口。获取方式：

1. **华为云官方**：从华为云 API 文档导出
2. **自行生成**：根据华为云 API 文档手动编写
3. **已有服务目录**：复制 `mcp_server_xxx/config/xxx.json`

### 文件格式

```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "ECS",
    "version": "2025-01-01",
    "x-host": "ecs.{region}.myhuaweicloud.com"  // ← 必须有 x-host
  },
  "paths": {
    "/ListServers": {
      "get": {
        "operationId": "ListServers",
        "description": "查询云服务器列表",
        "parameters": [...],
        "x-method": "GET",
        "x-url": "{endpoint}/v1/{project_id}/cloudservers"
      },
      ...
    }
  }
}
```

### 放置位置

```
config/openapi/{service_code}.json

示例:
config/openapi/ecs.json     ← ECS 服务
config/openapi/vpc.json     ← VPC 服务
config/openapi/iam.json     ← IAM 服务
```

---

## 步骤 ② 修改 config.yaml

打开 `config/config.yaml`，添加服务名到 `service_codes`：

```yaml
# 改动前
service_codes: ["rds", "das"]

# 改动后（添加 ecs）
service_codes: ["rds", "das", "ecs"]
```

**注意**：
- 服务名必须与 OpenAPI 文件名一致（如 `ecs` → `ecs.json`）
- 服务名用于生成工具前缀（如 `ecs_ListServers`）

---

## 步骤 ③ 创建过滤配置（可选）

### 为什么需要过滤？

某些服务有数百个 API，你可能只想暴露部分工具给用户。

### 创建过滤文件

```
config/filters/{service_code}.yaml

示例:
config/filters/ecs.yaml
```

### 白名单示例（只保留指定工具）

```yaml
mode: whitelist
tools:
  - ListServers           # 查询服务器列表
  - CreateServer          # 创建服务器
  - DeleteServer          # 删除服务器
  - ShowServer            # 查询服务器详情
```

### 黑名单示例（排除危险工具）

```yaml
mode: blacklist
tools:
  - DeleteServer          # 禁止删除
  - BatchDeleteServers    # 禁止批量删除
```

### 不创建文件 = 使用全部工具

如果不需要过滤：
- 不创建 `filters/ecs.yaml`
- 或创建空文件（tools 为空）

---

## 步骤 ④ 重启服务

```bash
# 停止当前服务
# (Ctrl+C 或 kill 进程)

# 重新启动
python huaweicloud_services_server/mcp_gateway/run.py
```

### 验证加载成功

启动日志应显示：

```
加载服务 ecs，OpenAPI路径: config/openapi/ecs.json
服务 ecs 加载完成，工具数: 200
总共加载 265 个工具，来自 3 个服务
```

---

## 完整示例：添加 ECS 服务

### ① 放置 OpenAPI

```bash
# 假设你已有 ecs.json
cp ecs.json config/openapi/ecs.json
```

### ② 修改配置

```yaml
# config/config.yaml
service_codes: ["rds", "das", "ecs"]
transport: http
port: 8907
```

### ③ 创建过滤（可选）

```yaml
# config/filters/ecs.yaml
mode: whitelist
tools:
  - ListServers
  - CreateServer
  - DeleteServer
  - ShowServer
```

### ④ 重启

```bash
python huaweicloud_services_server/mcp_gateway/run.py
```

### 验证

```bash
python test_list_tools.py

# 应看到:
# 工具总数: 68
# RDS 工具: 4 个
# DAS 工具: 61 个
# ECS 工具: 4 个  ← 新增的
```

---

## 文件命名规则

| 文件类型 | 文件名 | 必须匹配 |
|---------|--------|---------|
| OpenAPI | `{service_code}.json` | 与 config.yaml 中的服务名一致 |
| 过滤配置 | `{service_code}.yaml` | 与 OpenAPI 文件名一致 |

示例：
- config.yaml: `service_codes: ["ecs"]`
- openapi: `config/openapi/ecs.json`
- filter: `config/filters/ecs.yaml`

---

## 常见问题

### Q1: 服务名写什么？

A: 使用华为云服务的英文缩写：
- `rds` = 关系型数据库
- `das` = 数据管理服务
- `ecs` = 弹性云服务器
- `vpc` = 虚拟私有云
- `iam` = 身份认证服务

### Q2: OpenAPI 文件从哪来？

A: 三种方式：
1. 从华为云官方 API 文档导出
2. 参考 `rds.json` / `das.json` 手动编写
3. 使用 OpenAPI 生成工具

### Q3: x-host 字段是什么？

A: 华为云 API 的域名模板：
```
rds.{region}.myhuaweicloud.com  → RDS
ecs.{region}.myhuaweicloud.com  → ECS
```
程序会自动替换 `{region}` 为实际区域。

### Q4: 工具名需要带前缀吗？

A: **不需要**。过滤文件中写原始工具名：
```yaml
tools:
  - ListServers    # 正确（原始名）
  # - ecs_ListServers  # 错误（不要带前缀）
```

### Q5: 不想过滤某些服务怎么办？

A: 不创建对应的 filter 文件，或留空：
```yaml
# filters/iam.yaml（空文件）
# 暂不限制 IAM 工具
```

---

## 目录结构总览

```
mcp_gateway/config/
├── config.yaml           # 主配置（注册服务名）
│
├── openapi/              # OpenAPI 文件目录
│   ├── rds.json          # RDS API 定义
│   ├── das.json          # DAS API 定义
│   └── ecs.json          # ECS API 定义（新增）
│
└── filters/              # 过滤配置目录（可选）
    ├── rds.yaml          # RDS 工具过滤
    ├── das.yaml          # DAS 工具过滤
    └── ecs.yaml          # ECS 工具过滤（新增）
```

---

## 一句话总结

**新增服务只需：放 OpenAPI → 加服务名到 config.yaml → (可选) 创建 filter → 重启**