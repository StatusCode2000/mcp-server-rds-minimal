"""共享测试 fixtures"""
import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from assets.utils.model import MCPConfig, ToolFilterConfig


# ============================================================
# 最小化 OpenAPI spec fixture（用于 build_http_info 等测试）
# ============================================================

MINIMAL_OPENAPI = {
    "info": {
        "title": "TestService",
        "x-host": "test.myhuaweicloud.com",
        "version": "1.0",
    },
    "paths": {
        "/ListInstances": {
            "x-method": "GET",
            "x-url": "{endpoint}/v3/{project_id}/instances",
            "get": {
                "operationId": "ListInstances",
                "summary": "查询实例列表",
                "parameters": [
                    {
                        "name": "project_id",
                        "in": "path",
                        "required": True,
                        "type": "string",
                    },
                    {
                        "name": "region",
                        "in": "query",
                        "type": "string",
                    },
                    {
                        "name": "X-Auth-Token",
                        "in": "header",
                        "type": "string",
                    },
                ],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}

# 对应的 MCP Tool 对象
MINIMAL_TOOL = MagicMock()
MINIMAL_TOOL.name = "ListInstances"
MINIMAL_TOOL.inputSchema = {
    "properties": {
        "project_id": {"in": "path", "type": "string"},
        "region": {"in": "query", "type": "string"},
        "X-Auth-Token": {"in": "header", "type": "string"},
    },
    "required": ["project_id"],
}


@pytest.fixture
def minimal_openapi():
    """最小化 OpenAPI dict"""
    return MINIMAL_OPENAPI


@pytest.fixture
def minimal_tool():
    """最小化 MCP Tool mock"""
    return MINIMAL_TOOL


@pytest.fixture
def minimal_tools_list():
    """包含一个 Tool 的列表"""
    return [MINIMAL_TOOL]


@pytest.fixture
def config_dir(tmp_path):
    """创建完整的配置目录结构（config.yaml + openapi + filters）"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "service_codes: [rds]\ntransport: http\nport: 8907\n"
    )

    openapi_dir = tmp_path / "openapi"
    openapi_dir.mkdir()
    openapi_file = openapi_dir / "rds.json"
    openapi_file.write_text(json.dumps(MINIMAL_OPENAPI))

    filters_dir = tmp_path / "filters"
    filters_dir.mkdir()
    # 默认不过滤
    rds_filter = filters_dir / "rds.yaml"
    rds_filter.write_text("mode: whitelist\ntools: []\n")

    return tmp_path


@pytest.fixture
def config_with_filter(tmp_path):
    """带 whitelist 过滤的配置目录"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "service_codes: [rds]\ntransport: http\nport: 8907\n"
    )

    openapi_dir = tmp_path / "openapi"
    openapi_dir.mkdir()
    openapi_file = openapi_dir / "rds.json"
    openapi_file.write_text(json.dumps(MINIMAL_OPENAPI))

    filters_dir = tmp_path / "filters"
    filters_dir.mkdir()
    rds_filter = filters_dir / "rds.yaml"
    rds_filter.write_text("mode: whitelist\ntools: [ListInstances]\n")

    return tmp_path


@pytest.fixture
def mock_response():
    """模拟华为云 API 响应"""
    resp = MagicMock()
    resp.content = b'{"instances": []}'
    resp.json.return_value = {"instances": []}
    resp.headers = {"X-TRACE-ID": "hw-trace-uuid-123"}
    return resp


@pytest.fixture
def mock_client(mock_response):
    """模拟华为云 SDK client"""
    client = MagicMock()
    client.do_http_request.return_value = mock_response
    return client


@pytest.fixture
def clean_env():
    """清理环境变量，防止干扰测试"""
    env_keys = [
        "HUAWEI_ACCESS_KEY",
        "HUAWEI_SECRET_KEY",
        "MCP_SERVER_MODE",
        "MCP_SERVER_PORT",
    ]
    original = {}
    for key in env_keys:
        original[key] = os.environ.pop(key, None)
    yield
    for key in env_keys:
        if original[key] is not None:
            os.environ[key] = original[key]
        elif key in os.environ:
            del os.environ[key]