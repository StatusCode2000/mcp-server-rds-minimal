# 部署网络方案：公网 vs 内网

## 公网方案

适用场景：DAS OpenAPI 和 MCP Gateway 不在同一 VPC，跨公网通信。

```
AI Agent ──HTTPS──▶ 负载均衡器(ELB) ──HTTPS──▶ DAS OpenAPI ──HTTPS──▶ Ingress ──HTTP──▶ MCP Gateway ──HTTPS──▶ 华为云 API
                  mcp.example.com               das.example.com           mcp-gw.example.com        (VPC内网)       (华为云API)
                  (公网入口,TLS终止)             (DAS服务)                (MCP网关TLS终止)                          (SDK默认HTTPS)
```

### 需要什么

| 项目 | 说明 |
|------|------|
| 域名 | DAS 和 MCP Gateway 各需独立域名 |
| TLS 证书 | 每个公网域名绑定证书，华为云 SSL 证书服务购买或自签名 |
| 公网 ELB | 暴露公网入口，绑定证书，转发到后端服务 |
| Ingress | MCP Gateway 前的 TLS 终止，也可用另一个 ELB 替代 |
| 安全组 | 只开放 443 端口（HTTPS），关闭服务端口 |
| 代码改动 | 无，TLS 在 ELB/Ingress 层终止，服务内部走 HTTP |

### 各段传输安全

| 段 | 协议 | 安全保障 |
|----|------|----------|
| AI Agent → ELB | HTTPS | TLS 加密，AK/SK 安全 |
| ELB → DAS OpenAPI | HTTPS | TLS 加密 |
| DAS OpenAPI → Ingress | HTTPS | TLS 加密 |
| Ingress → MCP Gateway | HTTP | VPC 内网，网络隔离 |
| MCP Gateway → 华为云 API | HTTPS | SDK 默认 HTTPS，certifi 验证证书 |

---

## 内网方案

适用场景：DAS OpenAPI 和 MCP Gateway 在华为云同一 VPC 内。

```
AI Agent ──HTTPS──▶ 负载均衡器(ELB) ──HTTP──▶ DAS OpenAPI ──HTTP──▶ MCP Gateway ──HTTPS──▶ 华为云 API
                  mcp.example.com               (VPC内网)           (VPC内网IP直连)               (华为云API)
                  (公网入口,TLS终止)             (10.0.x.x:port)     (10.0.x.x:8907)              (SDK默认HTTPS)
```

### 需要什么

| 项目 | 说明 |
|------|------|
| 同一 VPC | DAS OpenAPI 和 MCP Gateway 必须在同一 VPC，内网互通 |
| 内网 IP + 端口 | DAS OpenAPI 配置 MCP Gateway 的内网地址，不需要域名 |
| 公网 ELB | 仅 AI Agent 入口需要，TLS 在这里终止 |
| 安全组 | MCP Gateway 的 8907 端口只允许 DAS OpenAPI 的内网 IP 访问 |
| 证书 | 仅公网入口需要，内网不需要 |
| 代码改动 | 无 |

### 各段传输安全

| 段 | 协议 | 安全保障 |
|----|------|----------|
| AI Agent → ELB | HTTPS | TLS 加密，AK/SK 安全 |
| ELB → DAS OpenAPI | HTTP | VPC 内网，网络隔离 |
| DAS OpenAPI → MCP Gateway | HTTP | VPC 内网，IP 直连，安全组限制 |
| MCP Gateway → 华为云 API | HTTPS | SDK 默认 HTTPS，certifi 验证证书 |

---

## 对比

| | 公网方案 | 内网方案 |
|---|---|---|
| 需要 | 域名、TLS 证书、公网 ELB、Ingress | 同一 VPC、内网 IP、仅入口 ELB |
| AK/SK 安全 | 全链路 HTTPS | 公网段 HTTPS，内网段 VPC 隔离 |
| 代码改动 | 无 | 无 |
| 成本 | 证书费用 + 多个 ELB | 仅入口 ELB（内网免费） |
| 复杂度 | 高（多域名、证书管理、续期） | 低（IP 直连） |

优先走内网方案，成本低、复杂度低、同样安全。只有跨 VPC 或跨云的场景才用公网方案。

---

## MCP Gateway → 华为云 API 说明

无论哪种部署方案，MCP Gateway 到华为云 API 这段都是 HTTPS。代码中 `create_api_client` 将 x_host 拼接为 `https://` endpoint，华为云 SDK 使用 certifi 证书库验证 TLS 证书。

当前代码中 `hwc_tools.py:178` 的 `http_config.ignore_ssl_verification = True` 关闭了证书验证，生产环境需移除此行。