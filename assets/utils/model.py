from dataclasses import dataclass
from typing import Optional, Literal, List

TransportType = Literal["sse", "stdio", "http"]


@dataclass
class MCPConfig:
    port: int
    service_codes: List[str]  # 改：支持多个服务
    transport: TransportType
    ak: Optional[str] = None
    sk: Optional[str] = None

    def check(self):
        if not self.service_codes:  # 改：检查列表
            raise ValueError("service_codes 必须至少包含一个服务")

        if self.transport in ("sse", "http") and self.port == 0:
            raise ValueError("sse和http服务端口不能设为0")
