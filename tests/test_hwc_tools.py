"""test_hwc_tools.py — hwc_tools 核心函数测试"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from assets.utils.hwc_tools import (
    build_http_info,
    create_api_client,
    filter_parameters,
    load_openapi,
    load_config,
)


class TestFilterParameters:
    def test_removes_none_values(self):
        result = filter_parameters({"a": 1, "b": None, "c": "hello"})
        assert result == {"a": 1, "c": "hello"}

    def test_removes_empty_list(self):
        result = filter_parameters({"a": 1, "b": [], "c": [1, 2]})
        assert result == {"a": 1, "c": [1, 2]}

    def test_keeps_zero_and_false(self):
        result = filter_parameters({"a": 0, "b": False, "c": ""})
        assert result == {"a": 0, "b": False, "c": ""}

    def test_empty_dict(self):
        result = filter_parameters({})
        assert result == {}


class TestLoadOpenapi:
    def test_load_valid_json(self, tmp_path):
        data = {"info": {"title": "Test"}, "paths": {}}
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        result = load_openapi(str(json_file))
        assert result["info"]["title"] == "Test"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="未找到"):
            load_openapi("/nonexistent/path.json")

    def test_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json}")

        with pytest.raises(json.JSONDecodeError):
            load_openapi(str(bad_file))


class TestLoadConfig:
    def test_load_basic_config(self, config_dir):
        config_path = config_dir / "config.yaml"
        cfg = load_config(str(config_path))
        assert cfg.service_codes == ["rds"]
        assert cfg.transport == "http"
        assert cfg.port == 8907

    def test_single_service_code_compat(self, tmp_path):
        """单服务 service_code → 自动转成 service_codes 列表"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("service_code: rds\ntransport: stdio\nport: 8888\n")

        # 需要openapi目录
        openapi_dir = tmp_path / "openapi"
        openapi_dir.mkdir()
        openapi_file = openapi_dir / "rds.json"
        openapi_file.write_text(json.dumps({"info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"}, "paths": {}}))

        cfg = load_config(str(config_file))
        assert cfg.service_codes == ["rds"]

    def test_env_var_override_ak(self, config_dir, clean_env):
        """环境变量覆盖 AK"""
        os.environ["HUAWEI_ACCESS_KEY"] = "env_ak_123"
        config_path = config_dir / "config.yaml"
        cfg = load_config(str(config_path))
        assert cfg.ak == "env_ak_123"

    def test_env_var_override_port(self, config_dir, clean_env):
        """环境变量覆盖 port（int 类型转换）"""
        os.environ["MCP_SERVER_PORT"] = "9999"
        config_path = config_dir / "config.yaml"
        cfg = load_config(str(config_path))
        assert cfg.port == 9999

    def test_env_var_invalid_transport(self, config_dir, clean_env):
        """无效 transport 值 → ValueError"""
        os.environ["MCP_SERVER_MODE"] = "websocket"
        config_path = config_dir / "config.yaml"
        with pytest.raises(ValueError, match="无效值"):
            load_config(str(config_path))

    def test_yaml_file_not_found(self):
        """YAML 文件不存在 → FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="YAML"):
            load_config("/nonexistent/config.yaml")

    def test_yaml_invalid_format(self, tmp_path):
        """YAML 格式错误 → ValueError"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("service_codes: [rds\ntransport: http\n")  # 缺少闭合括号

        with pytest.raises(ValueError, match="YAML"):
            load_config(str(config_file))

    def test_config_value_error(self, tmp_path):
        """配置值校验失败 → ValueError"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("service_codes: []\ntransport: http\nport: 0\n")

        with pytest.raises(ValueError):
            load_config(str(config_file))

    def test_load_whitelist_filter(self, config_with_filter):
        """加载 whitelist 过滤配置"""
        config_path = config_with_filter / "config.yaml"
        cfg = load_config(str(config_path))
        assert "rds" in cfg.tool_filters
        assert cfg.tool_filters["rds"].mode == "whitelist"
        assert cfg.tool_filters["rds"].tools == ["ListInstances"]


class TestBuildHttpInfo:
    def test_basic_build(self, minimal_openapi, minimal_tools_list):
        """基本参数路由"""
        arguments = {"project_id": "abc123", "region": "cn-east-2"}
        http_info = build_http_info(
            "ListInstances", arguments, minimal_openapi, minimal_tools_list
        )

        assert http_info["method"] == "GET"
        assert http_info["resource_path"] == "/v3/{project_id}/instances"
        assert http_info["path_params"]["project_id"] == "abc123"
        assert http_info["query_params"]["region"] == "cn-east-2"

    def test_trace_id_in_header(self, minimal_openapi, minimal_tools_list):
        """trace_id 注入 X-Trace-Id header"""
        http_info = build_http_info(
            "ListInstances", {"project_id": "abc123"}, minimal_openapi, minimal_tools_list,
            trace_id="test-trace-123"
        )
        assert http_info["header_params"]["X-Trace-Id"] == "test-trace-123"

    def test_no_trace_id_no_header(self, minimal_openapi, minimal_tools_list):
        """无 trace_id → 不注入 header"""
        http_info = build_http_info(
            "ListInstances", {"project_id": "abc123"}, minimal_openapi, minimal_tools_list
        )
        assert "X-Trace-Id" not in http_info["header_params"]

    def test_required_param_missing_raises(self, minimal_openapi, minimal_tools_list):
        """必填参数缺失 → Exception"""
        with pytest.raises(Exception, match="必填参数"):
            build_http_info(
                "ListInstances", {}, minimal_openapi, minimal_tools_list
            )

    def test_x_auth_token_skipped_in_required_check(self, minimal_openapi, minimal_tools_list):
        """X-Auth-Token 参数在必填检查中被跳过（即使 required 列表包含它也不报错）"""
        arguments = {"project_id": "abc123"}
        # 不传 X-Auth-Token 但它在 required 列表中 → 不报错因为被 pass 跳过
        http_info = build_http_info(
            "ListInstances", arguments, minimal_openapi, minimal_tools_list
        )
        assert http_info is not None

    def test_tool_not_found_raises(self, minimal_openapi, minimal_tools_list):
        """工具名不在列表中 → Exception"""
        with pytest.raises(Exception, match="MCP工具"):
            build_http_info(
                "NonExistentTool", {}, minimal_openapi, minimal_tools_list
            )


class TestCreateApiClient:
    @patch("assets.utils.hwc_tools.ClientBuilder")
    def test_endpoint_with_com(self, mock_builder_cls):
        """x_host 含 com → 拼接 https://"""
        mock_builder = MagicMock()
        mock_builder.with_credentials.return_value = mock_builder
        mock_builder.with_region.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        create_api_client("ak", "sk", "rds.cn-east-2.myhuaweicloud.com", "cn-east-2")
        # 验证 Region 传入的 endpoint 包含 https://
        call_args = mock_builder.with_region.call_args
        endpoint = call_args[0][0].endpoint if call_args else None
        assert endpoint is not None
        assert "https://" in endpoint

    @patch("assets.utils.hwc_tools.ClientBuilder")
    def test_endpoint_with_region_placeholder(self, mock_builder_cls):
        """x_host 含 {region} → 替换为 region 参数"""
        mock_builder = MagicMock()
        mock_builder.with_credentials.return_value = mock_builder
        mock_builder.with_region.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        create_api_client("ak", "sk", "service.{region}.myhuaweicloud.com", "cn-east-2")
        call_args = mock_builder.with_region.call_args
        endpoint = call_args[0][0].endpoint if call_args else None
        assert endpoint is not None
        assert "{region}" not in endpoint
        assert "cn-east-2" in endpoint

    @patch("assets.utils.hwc_tools.ClientBuilder")
    def test_endpoint_without_com(self, mock_builder_cls):
        """x_host 不含 com → 不拼接 https://"""
        mock_builder = MagicMock()
        mock_builder.with_credentials.return_value = mock_builder
        mock_builder.with_region.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        create_api_client("ak", "sk", "10.0.1.50:8907", "cn-north-4")
        # 不含 com → endpoint 就是原始 x_host，不拼接 https://
        # 但 with_region 的 endpoint 应该不含 https://
        call_args = mock_builder.with_region.call_args
        endpoint = call_args[0][0].endpoint if call_args else None
        assert endpoint == "10.0.1.50:8907"


class TestBuildHttpInfoBodyProperty:
    """覆盖 build_http_info 中 property_in is None 的分支（请求体参数）"""

    def test_property_in_none_maps_to_body(self):
        """property_in 为 None → 参数放入 request_body"""
        openapi = {
            "info": {"title": "TestService", "x-host": "test.myhuaweicloud.com"},
            "paths": {
                "/CreateInstance": {
                    "x-method": "POST",
                    "x-url": "{endpoint}/v3/instances",
                },
            },
        }

        tool = MagicMock()
        tool.name = "CreateInstance"
        tool.inputSchema = {
            "properties": {
                "name": {"type": "string"},          # property_in=None → body
                "flavor": {"type": "string"},        # property_in=None → body
                "project_id": {"in": "path", "type": "string"},
            },
            "required": ["name"],
        }

        arguments = {"name": "mydb", "flavor": "large", "project_id": "abc123"}
        http_info = build_http_info("CreateInstance", arguments, openapi, [tool])

        assert http_info["body"]["name"] == "mydb"
        assert http_info["body"]["flavor"] == "large"
        assert http_info["path_params"]["project_id"] == "abc123"


class TestLoadOpenapiIOError:
    """覆盖 load_openapi 中 IOError 分支"""

    def test_io_error(self):
        """IOError → 抛出 IOError"""
        # 使用 mock 模拟 open() 抛出 IOError
        with patch("builtins.open", side_effect=IOError("Permission denied")):
            with pytest.raises(IOError, match="加载OpenAPI文件失败"):
                load_openapi("/fake/unreadable.json")


class TestLoadConfigFilterEdgeCases:
    """覆盖 load_config 中 filter 加载的边界分支"""

    def test_filter_yaml_error(self, tmp_path):
        """filter 文件 YAML 格式错误 → 跳过，不抛异常"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("service_codes: [rds]\ntransport: http\nport: 8888\n")

        openapi_dir = tmp_path / "openapi"
        openapi_dir.mkdir()
        openapi_file = openapi_dir / "rds.json"
        openapi_file.write_text(json.dumps({
            "info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"},
            "paths": {},
        }))

        filters_dir = tmp_path / "filters"
        filters_dir.mkdir()
        # 写一个 YAML 格式错误的 filter 文件
        rds_filter = filters_dir / "rds.yaml"
        rds_filter.write_text("mode: [invalid\ntools: broken\n")

        cfg = load_config(str(config_file))
        # filter 加载失败但不应抛异常
        assert "rds" not in cfg.tool_filters

    def test_inline_tool_filters(self, tmp_path):
        """config.yaml 中有 inline tool_filters → 合并到配置"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "service_codes: [rds]\ntransport: http\nport: 8888\n"
            "tool_filters:\n"
            "  rds:\n"
            "    mode: whitelist\n"
            "    tools: [ListInstances]\n"
        )

        openapi_dir = tmp_path / "openapi"
        openapi_dir.mkdir()
        openapi_file = openapi_dir / "rds.json"
        openapi_file.write_text(json.dumps({
            "info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"},
            "paths": {},
        }))

        # 不创建 filters 目录，让 inline filter 生效
        cfg = load_config(str(config_file))
        assert "rds" in cfg.tool_filters
        assert cfg.tool_filters["rds"].mode == "whitelist"
        assert cfg.tool_filters["rds"].tools == ["ListInstances"]

    def test_inline_filter_invalid_mode_ignored(self, tmp_path):
        """inline filter 的 mode 不是 whitelist/blacklist → 忽略"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "service_codes: [rds]\ntransport: http\nport: 8888\n"
            "tool_filters:\n"
            "  rds:\n"
            "    mode: invalid\n"
            "    tools: [ListInstances]\n"
        )

        openapi_dir = tmp_path / "openapi"
        openapi_dir.mkdir()
        openapi_file = openapi_dir / "rds.json"
        openapi_file.write_text(json.dumps({
            "info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"},
            "paths": {},
        }))

        cfg = load_config(str(config_file))
        assert "rds" not in cfg.tool_filters

    def test_inline_filter_empty_tools_ignored(self, tmp_path):
        """inline filter 的 tools 为空列表 → 忽略"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "service_codes: [rds]\ntransport: http\nport: 8888\n"
            "tool_filters:\n"
            "  rds:\n"
            "    mode: whitelist\n"
            "    tools: []\n"
        )

        openapi_dir = tmp_path / "openapi"
        openapi_dir.mkdir()
        openapi_file = openapi_dir / "rds.json"
        openapi_file.write_text(json.dumps({
            "info": {"title": "RDS", "x-host": "rds.myhuaweicloud.com"},
            "paths": {},
        }))

        cfg = load_config(str(config_file))
        assert "rds" not in cfg.tool_filters