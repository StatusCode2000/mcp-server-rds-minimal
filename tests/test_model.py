"""test_model.py — MCPConfig 和 ToolFilterConfig 测试"""
import pytest
from assets.utils.model import MCPConfig, ToolFilterConfig


class TestToolFilterConfig:
    def test_default_mode(self):
        cfg = ToolFilterConfig()
        assert cfg.mode == "whitelist"

    def test_default_tools(self):
        cfg = ToolFilterConfig()
        assert cfg.tools == []

    def test_custom_values(self):
        cfg = ToolFilterConfig(mode="blacklist", tools=["CreateInstance"])
        assert cfg.mode == "blacklist"
        assert cfg.tools == ["CreateInstance"]


class TestMCPConfigCheck:
    def test_empty_service_codes_raises(self):
        cfg = MCPConfig(port=8907, service_codes=[], transport="http")
        with pytest.raises(ValueError, match="service_codes"):
            cfg.check()

    def test_http_port_zero_raises(self):
        cfg = MCPConfig(port=0, service_codes=["rds"], transport="http")
        with pytest.raises(ValueError, match="端口"):
            cfg.check()

    def test_sse_port_zero_raises(self):
        cfg = MCPConfig(port=0, service_codes=["rds"], transport="sse")
        with pytest.raises(ValueError, match="端口"):
            cfg.check()

    def test_stdio_port_zero_ok(self):
        cfg = MCPConfig(port=0, service_codes=["rds"], transport="stdio")
        cfg.check()  # 不应该抛异常

    def test_valid_config_ok(self):
        cfg = MCPConfig(port=8907, service_codes=["rds", "das"], transport="http")
        cfg.check()  # 不应该抛异常