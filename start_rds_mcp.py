#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
华为云 RDS MCP 服务启动脚本
用法: python start_rds_mcp.py [--stdio|--http|--sse] [--port PORT]
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description='启动 RDS MCP Server')
    parser.add_argument(
        '--transport',
        choices=['stdio', 'http', 'sse'],
        default='http',
        help='传输模式: stdio, http 或 sse (默认: http)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8907,
        help='HTTP/SSE 模式使用的端口 (默认: 8907)'
    )
    return parser.parse_args()


def start_mcp_service(transport: str, port: int):
    """启动 MCP 服务"""
    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    print(f"当前目录: {os.getcwd()}")
    print(f"传输模式: {transport}")
    if transport != 'stdio':
        print(f"端口: {port}")
    print("-" * 50)

    # 构建启动命令
    cmd = ["uv", "run", "mcp-server-rds"]
    if transport != 'http':
        cmd.extend(["-t", transport])
    if transport != 'stdio' and port != 8907:
        cmd.extend(["-p", str(port)])

    print(f"启动命令: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"服务启动失败: {e}")
        return False
    except FileNotFoundError:
        print("未找到 uv 命令，请确保已安装 uv")
        print("安装方法: pip install uv")
        return False

    return True


def main():
    print("=" * 50)
    print("  华为云 RDS MCP 服务启动脚本")
    print("=" * 50)
    print()

    args = parse_args()
    success = start_mcp_service(args.transport, args.port)

    if success:
        print("\nRDS MCP 服务已停止")


if __name__ == "__main__":
    main()