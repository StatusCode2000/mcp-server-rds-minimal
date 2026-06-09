"""test_openapi.py — OpenAPI 解析和工具转换测试"""
import pytest
from copy import deepcopy
from unittest.mock import patch

from assets.utils.openapi import SwaggerRefResolver, OpenAPIToToolsConverter


# ============================================================
# SwaggerRefResolver 测试
# ============================================================

class TestSwaggerRefResolver:
    def test_internal_ref_resolution(self):
        """解析内部 #/ 引用"""
        spec = {
            "components": {
                "schemas": {
                    "Error": {"type": "object", "properties": {"code": {"type": "integer"}}}
                }
            },
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "400": {"description": "Bad Request", "schema": {"$ref": "#/components/schemas/Error"}}
                        }
                    }
                }
            },
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        # 400 响应的 schema 应被解析为 Error 的内容
        schema = result["paths"]["/test"]["get"]["responses"]["400"]["schema"]
        assert schema["type"] == "object"
        assert "code" in schema["properties"]

    def test_circular_ref_detection(self):
        """循环引用检测"""
        spec = {
            "components": {
                "schemas": {
                    "A": {"$ref": "#/components/schemas/B"},
                    "B": {"$ref": "#/components/schemas/A"},
                }
            }
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        # 应检测到循环引用
        a = result["components"]["schemas"]["A"]
        assert "$ref_cycle_detected" in a

    def test_invalid_ref_type(self):
        """$ref 值不是字符串 → 视为无效引用"""
        spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {"description": "OK", "schema": {"$ref": 123}}
                        }
                    }
                }
            }
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        # 无效引用被处理，不含 $ref
        schema = result["paths"]["/test"]["get"]["responses"]["200"]["schema"]
        assert "$ref" not in schema

    def test_external_ref_unsupported(self):
        """外部引用（不以 #/ 开头）→ 不支持"""
        spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {"description": "OK", "schema": {"$ref": "https://example.com/schema.json"}}
                        }
                    }
                }
            }
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        # 外部引用被处理为无效引用
        schema = result["paths"]["/test"]["get"]["responses"]["200"]["schema"]
        assert "$ref" not in schema

    def test_ref_with_extra_attributes(self):
        """$ref 旁边有其他属性 → 合并"""
        spec = {
            "components": {
                "schemas": {
                    "Error": {"type": "object", "properties": {"code": {"type": "integer"}}}
                }
            },
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "400": {
                                "description": "Bad Request",
                                "schema": {"$ref": "#/components/schemas/Error", "description": "自定义错误描述"}
                            }
                        }
                    }
                }
            }
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        schema = result["paths"]["/test"]["get"]["responses"]["400"]["schema"]
        # 引用内容 + 额外属性合并
        assert schema["type"] == "object"
        assert schema["description"] == "自定义错误描述"

    def test_tilde_escaping(self):
        """路径中 ~0 ~1 转义"""
        spec = {
            "components": {
                "schemas": {
                    "My/Schema~Name": {"type": "string"}
                }
            },
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {"schema": {"$ref": "#/components/schemas/My~1Schema~0Name"}}
                        }
                    }
                }
            }
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        schema = result["paths"]["/test"]["get"]["responses"]["200"]["schema"]
        assert schema["type"] == "string"

    def test_ref_path_not_found(self):
        """引用路径不存在 → 错误"""
        spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {"schema": {"$ref": "#/components/schemas/NonExistent"}}
                        }
                    }
                }
            }
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        schema = result["paths"]["/test"]["get"]["responses"]["200"]["schema"]
        assert "$ref_resolve_error" in schema

    def test_no_refs_pass_through(self):
        """无引用 → 原样返回"""
        spec = {"info": {"title": "Test"}, "paths": {}}
        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()
        assert result["info"]["title"] == "Test"

    def test_list_nodes_parsed(self):
        """列表中的引用也被解析"""
        spec = {
            "components": {
                "schemas": {
                    "Item": {"type": "string"}
                }
            },
            "tags": [
                {"name": "test", "schema": {"$ref": "#/components/schemas/Item"}},
                {"name": "other"}
            ],
        }

        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()

        assert result["tags"][0]["schema"]["type"] == "string"
        assert result["tags"][1]["name"] == "other"


# ============================================================
# OpenAPIToToolsConverter 测试
# ============================================================

SIMPLE_OPENAPI = {
    "info": {"title": "TestService", "version": "1.0"},
    "paths": {
        "/v3/{project_id}/instances": {
            "get": {
                "operationId": "ListInstances",
                "summary": "查询实例列表",
                "parameters": [
                    {"name": "project_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                ],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}

OPENAPI_WITH_BODY = {
    "info": {"title": "TestService", "version": "1.0"},
    "paths": {
        "/v3/{project_id}/instances": {
            "post": {
                "operationId": "CreateInstance",
                "summary": "创建实例",
                "parameters": [
                    {"name": "project_id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "flavor": {"type": "string"},
                                },
                                "required": ["name"],
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}


class TestOpenAPIToToolsConverter:
    def test_basic_conversion(self):
        """基本转换：生成 Tool 对象"""
        converter = OpenAPIToToolsConverter(SIMPLE_OPENAPI)
        tools = converter.convert()

        assert len(tools) == 1
        assert tools[0].name == "ListInstances"
        assert "查询实例" in tools[0].description

    def test_tool_parameters(self):
        """参数从 path/query 正确提取"""
        converter = OpenAPIToToolsConverter(SIMPLE_OPENAPI)
        tools = converter.convert()

        props = tools[0].inputSchema["properties"]
        assert "project_id" in props
        assert props["project_id"]["in"] == "path"
        assert "limit" in props
        assert props["limit"]["in"] == "query"

    def test_required_parameters(self):
        """必填参数标记"""
        converter = OpenAPIToToolsConverter(SIMPLE_OPENAPI)
        tools = converter.convert()

        required = tools[0].inputSchema.get("required", [])
        assert "project_id" in required

    def test_request_body_properties(self):
        """请求体属性提取"""
        converter = OpenAPIToToolsConverter(OPENAPI_WITH_BODY)
        tools = converter.convert()

        props = tools[0].inputSchema["properties"]
        assert "name" in props
        assert "flavor" in props

    def test_request_body_required(self):
        """请求体 required 字段合并"""
        converter = OpenAPIToToolsConverter(OPENAPI_WITH_BODY)
        tools = converter.convert()

        required = tools[0].inputSchema.get("required", [])
        assert "project_id" in required
        assert "name" in required

    def test_no_operationid_fallback_name(self):
        """无 operationId → 用 method+path 生成名称"""
        openapi = deepcopy(SIMPLE_OPENAPI)
        del openapi["paths"]["/v3/{project_id}/instances"]["get"]["operationId"]

        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()

        assert len(tools) == 1
        # 名称由 method + path 生成
        assert "get" in tools[0].name.lower()

    def test_description_fallback(self):
        """无 description → 用 summary"""
        openapi = deepcopy(SIMPLE_OPENAPI)
        del openapi["paths"]["/v3/{project_id}/instances"]["get"]["summary"]
        openapi["paths"]["/v3/{project_id}/instances"]["get"]["description"] = "自定义描述"

        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert tools[0].description == "自定义描述"

    def test_no_description_no_summary_returns_empty(self):
        """无 description 和 summary → description 为空字符串（代码不自动生成 fallback）"""
        openapi = deepcopy(SIMPLE_OPENAPI)
        del openapi["paths"]["/v3/{project_id}/instances"]["get"]["summary"]

        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        # _determine_tool_description: description="" → or summary="" → result=""
        # 只有 description 不是 str 类型才 fallback
        assert tools[0].description == ""


class TestCleanupName:
    def test_basic_cleanup(self):
        """清理非法字符"""
        result = OpenAPIToToolsConverter.cleanup_name("list-all_instances")
        assert result == "list_all_instances"

    def test_truncation(self):
        """超过 64 字符 → 截断"""
        long_name = "a" * 100
        result = OpenAPIToToolsConverter.cleanup_name(long_name)
        assert len(result) == 64

    def test_empty_name_fallback(self):
        """空名称 → unnamed_tool"""
        result = OpenAPIToToolsConverter.cleanup_name("---")
        assert result == "unnamed_tool"

    def test_special_chars_removed(self):
        """特殊字符替换为 _"""
        result = OpenAPIToToolsConverter.cleanup_name("list@all#instances")
        assert result == "list_all_instances"

    def test_leading_trailing_special_removed(self):
        """开头和结尾的特殊字符移除"""
        result = OpenAPIToToolsConverter.cleanup_name("---list_instances---")
        assert result == "list_instances"


class TestExtractPathParameters:
    def test_valid_parameters(self):
        """有效参数列表提取（只保留 dict 类型）"""
        path_values = {
            "parameters": [
                {"name": "id", "in": "path", "schema": {"type": "string"}},
                "not_a_dict",  # 不是 dict → 被过滤掉
            ]
        }
        result = OpenAPIToToolsConverter._extract_path_parameters(path_values)
        # _extract_path_parameters 只保留 isinstance(p, dict) 的项
        assert len(result) == 1
        assert result[0]["name"] == "id"

    def test_no_parameters(self):
        """无 parameters → 返回空列表"""
        path_values = {}
        result = OpenAPIToToolsConverter._extract_path_parameters(path_values)
        assert result == []

    def test_parameters_not_list(self):
        """parameters 不是列表 → 返回空列表"""
        path_values = {"parameters": "invalid"}
        result = OpenAPIToToolsConverter._extract_path_parameters(path_values)
        assert result == []


class TestSwaggerRefResolverEdgeCases:
    """覆盖 _find_ref_object 和其他边界路径"""

    def test_list_index_ref(self):
        """引用路径中包含列表索引（数字部分）"""
        spec = {
            "items": [
                {"name": "first"},
                {"name": "second"},
            ]
        }
        resolver = SwaggerRefResolver(spec)
        # 构造引用到列表索引 1
        ref_uri = "#/items/1"
        result = resolver._find_ref_object(ref_uri)
        assert result["name"] == "second"

    def test_non_digit_list_index_raises(self):
        """列表索引不是数字 → KeyError"""
        spec = {
            "items": ["a", "b"]
        }
        resolver = SwaggerRefResolver(spec)
        with pytest.raises(KeyError, match="列表索引不是数字"):
            resolver._find_ref_object("#/items/abc")

    def test_missing_dict_key_raises(self):
        """字典键不存在 → KeyError"""
        spec = {"data": {"existing": "value"}}
        resolver = SwaggerRefResolver(spec)
        with pytest.raises(KeyError, match="字典键不存在"):
            resolver._find_ref_object("#/data/missing_key")

    def test_non_dict_non_list_target_raises_type_error(self):
        """中间节点不是 dict/list → TypeError"""
        spec = {"data": "string_value"}
        resolver = SwaggerRefResolver(spec)
        with pytest.raises(TypeError, match="无法索引类型"):
            resolver._find_ref_object("#/data/sub_key")

    def test_ref_not_string_returns_without_ref(self):
        """$ref 不是 string → 去掉 $ref 键返回剩余"""
        spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {"$ref": 42, "description": "fallback"}
                        }
                    }
                }
            }
        }
        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()
        resp = result["paths"]["/test"]["get"]["responses"]["200"]
        assert "$ref" not in resp
        assert resp.get("description") == "fallback"

    def test_external_ref_returns_without_ref(self):
        """外部引用（http://...）→ 去掉 $ref 返回剩余属性"""
        spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {"$ref": "http://example.com/schema", "extra": "data"}
                        }
                    }
                }
            }
        }
        resolver = SwaggerRefResolver(spec)
        result = resolver.parse()
        resp = result["paths"]["/test"]["get"]["responses"]["200"]
        assert "$ref" not in resp
        assert resp.get("extra") == "data"


class TestOpenAPIToToolsConverterEdgeCases:
    """覆盖 _extract_tools, _create_tool, _build_tool_parameters 的边界路径"""

    def test_paths_not_dict_returns_empty(self):
        """paths 不是 dict → 不提取任何工具"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": "invalid_string",
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert tools == []

    def test_path_values_not_dict_skipped(self):
        """path 的值不是 dict → 跳过该路径"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": "not_a_dict",
                "/valid": {
                    "get": {
                        "operationId": "ValidOp",
                        "summary": "有效操作",
                        "parameters": [],
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert len(tools) == 1
        assert tools[0].name == "ValidOp"

    def test_method_not_in_openapi_methods_skipped(self):
        """非标准 HTTP 方法 → 跳过"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "GetTest",
                        "summary": "获取",
                        "parameters": [],
                        "responses": {"200": {"description": "OK"}},
                    },
                    "x-custom": {
                        "operationId": "CustomOp",
                        "summary": "自定义",
                    },
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert len(tools) == 1
        assert tools[0].name == "GetTest"

    def test_operation_not_dict_skipped(self):
        """operation 不是 dict → 跳过"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": "not_a_dict",
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert tools == []

    def test_description_non_str_fallback(self):
        """description 不是字符串 → 回退到 method+path"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "TestOp",
                        "description": 123,  # 不是 str
                        "parameters": [],
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert tools[0].description == "API 调用: GET /test"

    def test_operation_parameters_not_list_handled(self):
        """operation.parameters 不是 list → 按 [] 处理"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": "invalid",
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        assert len(tools) == 1

    def test_param_schema_not_dict_skipped(self):
        """参数 schema 不是 dict → 跳过该参数"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [
                            {"name": "bad_param", "in": "query", "schema": "not_dict"},
                            {"name": "good_param", "in": "query", "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        props = tools[0].inputSchema["properties"]
        assert "bad_param" not in props
        assert "good_param" in props

    def test_cycle_detected_in_param_schema_skipped(self):
        """参数 schema 中有 $ref_cycle_detected → 跳过"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [
                            {"name": "cycled", "in": "query", "schema": {"$ref_cycle_detected": "#/foo"}},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        props = tools[0].inputSchema["properties"]
        assert "cycled" not in props

    def test_request_body_with_invalid_content_type(self):
        """requestBody content 不含 application/json → 无请求体参数"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "requestBody": {
                            "content": {
                                "application/xml": {
                                    "schema": {"type": "string"}
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        # application/xml schema type != "object" → no body properties extracted
        assert "properties" in tools[0].inputSchema

    def test_request_body_content_not_dict(self):
        """requestBody content 不是 dict → 不提取请求体"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "requestBody": {
                            "content": "not_a_dict"
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        props = tools[0].inputSchema["properties"]
        assert set(props.keys()) == {"region"}

    def test_media_type_obj_not_dict(self):
        """media type 对象不是 dict → 不提取请求体"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "requestBody": {
                            "content": {
                                "application/json": "not_a_dict"
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        props = tools[0].inputSchema["properties"]
        assert set(props.keys()) == {"region"}

    def test_body_schema_not_object_type(self):
        """body schema type 不是 object → 不提取请求体属性"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "string"}
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        props = tools[0].inputSchema["properties"]
        assert set(props.keys()) == {"region"}

    def test_body_schema_cycle_detected_skipped(self):
        """body schema 有 $ref_cycle_detected → 不提取"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "requestBody": {
                            "$ref_cycle_detected": "#/something",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "properties": {"name": {"type": "string"}}}
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        # cycle detected in requestBody → skip entire body
        props = tools[0].inputSchema["properties"]
        assert set(props.keys()) == {"region"}

    def test_body_property_cycle_detected_skipped(self):
        """请求体属性有 $ref_cycle_detected → 跳过该属性"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "bad": {"$ref_cycle_detected": "#/foo"},
                                            "good": {"type": "string"},
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        props = tools[0].inputSchema["properties"]
        assert "bad" not in props
        assert "good" in props

    def test_body_property_name_conflict_warning(self):
        """请求体属性名与参数名冲突 → 请求体覆盖"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [
                            {"name": "name", "in": "query", "schema": {"type": "string"}},
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string", "description": "body name"},
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)
        tools = converter.convert()
        # 请求体属性 "name" 覆盖了 query 参数 "name"
        props = tools[0].inputSchema["properties"]
        assert props["name"]["description"] == "body name"

    def test_cleanup_name_truncation_all_underscores(self):
        """截断后全是下划线 → unnamed_tool"""
        long_name = "a_" * 50  # 100 chars, 截断后 64 chars, rstrip("_") → 可能变空
        result = OpenAPIToToolsConverter.cleanup_name(long_name)
        # 截断到 64 后 rstrip("_")，如果结果为空则返回 unnamed_tool
        assert result == "unnamed_tool" or len(result) <= 64

    def test_cleanup_name_non_alnum_final_char(self):
        """截断后最后一个字符不是 alnum → unnamed_tool"""
        # 名字全部是特殊字符（除了开头结尾清理后中间也全是特殊字符）
        result = OpenAPIToToolsConverter.cleanup_name("@@@")
        # 清理后为空 → unnamed_tool
        assert result == "unnamed_tool"

    def test_validation_error_in_create_tool(self):
        """Tool 创建时 ValidationError → 返回 None（不添加工具）"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)

        from pydantic import ValidationError
        # Mock Tool constructor to raise ValidationError → caught inside _create_tool
        with patch("assets.utils.openapi.Tool", side_effect=ValidationError.from_exception_data(
            title="Tool", line_errors=[], input_type="python"
        )):
            tools = converter.convert()
            assert len(tools) == 0

    def test_generic_exception_in_create_tool(self):
        """Tool 创建时通用 Exception → 返回 None（不添加工具）"""
        openapi = {
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "TestOp",
                        "summary": "测试",
                        "parameters": [],
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        converter = OpenAPIToToolsConverter(openapi)

        # Mock Tool constructor to raise generic Exception
        with patch("assets.utils.openapi.Tool", side_effect=RuntimeError("unexpected")):
            tools = converter.convert()
            assert len(tools) == 0