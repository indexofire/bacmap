"""bacmap 控制台命令。

子命令：
- ``bacmap mcp``     stdio MCP 服务器（Hermes/Claude/Codex 等本机客户端接入）
- ``bacmap web``     Web 任务页（默认 127.0.0.1:8800，ADR-16 只绑本机）
- ``bacmap version`` 版本号
"""

from __future__ import annotations

import argparse
from importlib.metadata import version as pkg_version
from pathlib import Path

from bacmap.config import BACMAP_HOME


def _run_mcp(args: argparse.Namespace) -> None:
    from bacmap.interfaces.mcp.server import build_server
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    engine = None if args.read_only else DbosTaskEngine(Path(args.home))
    build_server(engine).run(transport="stdio")


def _run_web(args: argparse.Namespace) -> None:
    import uvicorn

    from bacmap.interfaces.web.app import create_app
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    engine = DbosTaskEngine(Path(args.home))
    uvicorn.run(create_app(engine), host=args.host, port=args.port)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bacmap", description="bacmap 本地病原菌基因组分析系统（architecture-frozen-v1）"
    )
    parser.add_argument("--version", action="version", version=f"bacmap {pkg_version('bacmap')}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_mcp = sub.add_parser("mcp", help="启动 stdio MCP 服务器")
    p_mcp.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    p_mcp.add_argument("--read-only", action="store_true", help="只读模式（不暴露任务提交工具）")
    p_mcp.set_defaults(func=_run_mcp)

    p_web = sub.add_parser("web", help="启动 Web 任务页")
    p_web.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    p_web.add_argument("--host", default="127.0.0.1", help="绑定地址（默认仅本机）")
    p_web.add_argument("--port", type=int, default=8800, help="端口（默认 8800）")
    p_web.set_defaults(func=_run_web)

    args = parser.parse_args()
    args.func(args)
