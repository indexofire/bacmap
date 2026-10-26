"""MCP 入口：``python -m bacmap.interfaces.mcp [--transport stdio|http] [--profile ...]``。

stdio 为默认（本机客户端）；http 走 Streamable HTTP + Bearer 鉴权（ADR-12）。
Profile 默认 ``cloud``（v1.5，ADR-16）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bacmap.config import BACMAP_HOME
from bacmap.interfaces.mcp.launch import add_profile_argument, serve
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="bacmap MCP server")
    parser.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="只读模式：不暴露任务提交工具（纯查询）",
    )
    add_profile_argument(parser)
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio", help="传输（默认 stdio）"
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 端口（默认 8765）")
    parser.add_argument("--uds", default="", help="改用 unix socket 路径")
    parser.add_argument(
        "--token-env", default="BACMAP_MCP_TOKEN", help="Bearer token 的环境变量名"
    )
    args = parser.parse_args()
    serve(
        home=Path(args.home),
        profile_name=args.profile,
        read_only=args.read_only,
        transport=args.transport,
        host=args.host,
        port=args.port,
        uds=args.uds,
        token_env=args.token_env,
        engine_factory=DbosTaskEngine,
    )


if __name__ == "__main__":
    main()
