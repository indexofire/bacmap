"""MCP 入口：``python -m bacmap.interfaces.mcp [--transport stdio|http]``。

stdio 为默认（本机客户端）；http 走 Streamable HTTP + Bearer 鉴权（ADR-12）。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from bacmap.config import BACMAP_HOME
from bacmap.interfaces.mcp.server import build_server
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="bacmap MCP server")
    parser.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="只读模式：不暴露任务提交工具（纯查询）",
    )
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
    run_http(server, token=token, host=args.host, port=args.port, uds=(args.uds or None))


if __name__ == "__main__":
    main()
