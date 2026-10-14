"""bacmap 控制台命令。

子命令：
- ``bacmap mcp``     MCP 服务器：stdio（默认）或 Streamable HTTP（Bearer 鉴权，ADR-12）
- ``bacmap web``     Web 任务页（默认 127.0.0.1:8800，ADR-16 只绑本机）
- ``bacmap version`` 版本号
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

from bacmap.config import BACMAP_HOME

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _warn_if_exposed(host: str) -> None:
    if host not in _LOCAL_HOSTS:
        print(
            f"[bacmap] 警告：绑定非本机地址 {host!r}（ADR-16 默认只绑本机；"
            "跨机访问请确认网络边界与鉴权）",
            file=sys.stderr,
        )


def _run_mcp(args: argparse.Namespace) -> None:
    from bacmap.interfaces.mcp.server import build_server
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    engine = None if args.read_only else DbosTaskEngine(Path(args.home))
    server = build_server(engine)

    if args.transport == "stdio":
        server.run(transport="stdio")
        return

    from bacmap.interfaces.mcp.http import run_http

    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(
            f"HTTP 传输需要 Bearer token（ADR-12）：请先设置环境变量 {args.token_env}"
        )
    _warn_if_exposed(args.host)
    run_http(server, token=token, host=args.host, port=args.port, uds=(args.uds or None))


def _run_web(args: argparse.Namespace) -> None:
    import uvicorn

    from bacmap.interfaces.web.app import create_app
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    token = os.environ.get(args.token_env, "")
    _warn_if_exposed(args.host)
    engine = DbosTaskEngine(Path(args.home))
    uvicorn.run(create_app(engine, auth_token=token or None), host=args.host, port=args.port)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bacmap", description="bacmap 本地病原菌基因组分析系统（architecture-frozen-v1）"
    )
    parser.add_argument("--version", action="version", version=f"bacmap {pkg_version('bacmap')}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_mcp = sub.add_parser("mcp", help="启动 MCP 服务器（stdio 或 Streamable HTTP）")
    p_mcp.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    p_mcp.add_argument("--read-only", action="store_true", help="只读模式（不暴露任务提交工具）")
    p_mcp.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio", help="传输（默认 stdio）"
    )
    p_mcp.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址（默认仅本机）")
    p_mcp.add_argument("--port", type=int, default=8765, help="HTTP 端口（默认 8765）")
    p_mcp.add_argument("--uds", default="", help="改用 unix socket 路径（与 host/port 互斥）")
    p_mcp.add_argument(
        "--token-env",
        default="BACMAP_MCP_TOKEN",
        help="读取 Bearer token 的环境变量名（ADR-12，HTTP 传输必需）",
    )
    p_mcp.set_defaults(func=_run_mcp)

    p_web = sub.add_parser("web", help="启动 Web 任务页")
    p_web.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    p_web.add_argument("--host", default="127.0.0.1", help="绑定地址（默认仅本机）")
    p_web.add_argument("--port", type=int, default=8800, help="端口（默认 8800）")
    p_web.add_argument(
        "--token-env",
        default="BACMAP_WEB_TOKEN",
        help="读取 Web Bearer token 的环境变量名（ADR-14；未设置则不启用鉴权）",
    )
    p_web.set_defaults(func=_run_web)

    args = parser.parse_args()
    args.func(args)
