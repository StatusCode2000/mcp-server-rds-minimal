from dataclasses import dataclass, field
from typing import Optional, Literal, List, Dict

TransportType = Literal["sse", "stdio", "http"]


@dataclass
class ToolFilterConfig:
    """单个服务的工具过滤配置"""
    mode: Literal["whitelist", "blacklist"] = "whitelist"
    tools: List[str] = field(default_factory=list)


@dataclass
class MCPConfig:
    port: int
    service_codes: List[str]
    transport: TransportType
    ak: Optional[str] = None
    sk: Optional[str] = None
    tool_filters: Dict[str, ToolFilterConfig] = field(default_factory=dict)

    def check(self):
        if not self.service_codes:
            raise ValueError("service_codes 必须至少包含一个服务")

        if self.transport in ("sse", "http") and self.port == 0:
            raise ValueError("sse和http服务端口不能设为0")
