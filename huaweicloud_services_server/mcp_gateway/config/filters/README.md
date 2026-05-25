# 工具过滤配置目录

每个服务的工具过滤规则放在独立的 YAML 文件中。

## 文件命名规则

文件名 = 服务名 + `.yaml`

例如：
- `rds.yaml` → RDS 服务的过滤配置
- `das.yaml` → DAS 服务的过滤配置
- `ecs.yaml` → ECS 服务的过滤配置

## 配置格式

```yaml
mode: whitelist  # 或 blacklist
tools:
  - ToolName1    # 原始工具名（不带服务前缀）
  - ToolName2
  - ToolName3
```

## 过滤模式

| 模式 | 效果 |
|------|------|
| `whitelist` | 白名单，只保留指定工具 |
| `blacklist` | 黑名单，排除指定工具 |

## 注意事项

1. **工具名用原始名**：不要带服务前缀（如写 `ListInstances`，不是 `rds_ListInstances`）
2. **不创建文件 = 不过滤**：如果某个服务没有对应的 filter 文件，则使用全部工具
3. **空 tools 列表 = 不过滤**：如果 tools 列表为空，也使用全部工具

## 示例

### 白名单（只保留 4 个工具）

```yaml
mode: whitelist
tools:
  - ListInstances
  - CreateInstance
  - DeleteInstance
  - ShowInstanceConfiguration
```

### 黑名单（排除危险操作）

```yaml
mode: blacklist
tools:
  - DeleteInstance
  - DropDatabase
```