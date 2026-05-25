self.openapi_dicts = {
    "rds": {
        "openapi": "3.0.0",
        "info": {
            "title": "RDS API",
            "version": "v3",
            "x-host": "rds.cn-north-4.myhuaweicloud.com"
        },
        "paths": {
            "/ListInstances": {
                "x-method": "GET",
                "x-url": "https://{endpoint}/v3/{project_id}/instances",
                "parameters": [...]
            },
            "/CreateInstance": {...},
            # ... 共 232 个 API
        }
    },
    
    "das": {
        "openapi": "3.0.0",
        "info": {
            "title": "DAS API",
            "version": "v1",
            "x-host": "das.cn-north-4.myhuaweicloud.com"
        },
        "paths": {
            "/ShowApiVersion": {...},
            "/ListFullSqlTasks": {...},
            # ... 共 61 个 API
        }
    }
}


self.original_tools = {
    "rds": [
        Tool(name="ListInstances", description="查询实例列表", inputSchema={...}),
        Tool(name="CreateInstance", description="创建实例", inputSchema={...}),
        Tool(name="DeleteInstance", description="删除实例", inputSchema={...}),
        # ... 共 232 个工具
    ],
    
    "das": [
        Tool(name="ShowApiVersion", description="查询API版本", inputSchema={...}),
        Tool(name="ListFullSqlTasks", description="查询全量SQL任务", inputSchema={...}),
        # ... 共 61 个工具
    ]
}


self.tool_service_map = {
    # RDS 工具
    "rds_ListInstances": "rds",
    "rds_CreateInstance": "rds",
    "rds_DeleteInstance": "rds",
    # ... 232 个映射
    
    # DAS 工具
    "das_ShowApiVersion": "das",
    "das_ListFullSqlTasks": "das",
    # ... 61 个映射
}
