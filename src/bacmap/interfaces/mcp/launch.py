"""MCP 服务启动（``bacmap mcp`` 与 ``python -m bacmap.interfaces.mcp`` 共用）。"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bacmap.interfaces.mcp.profiles import McpProfile, ProfileNotAllowedError, resolve_profile


def add_profile_argument(parser: Any) -> None:
    parser.add_argument(
        "--profile",
        choices=[p.value for p in McpProfile],
        default=McpProfile.CLOUD.value,
        help=(
            "数据级别 Profile（默认 cloud：工具输出 ≤ cloud_max_data_class；"
            "local-trusted 可见至 D4，需 config.toml [mcp] allow_local_trusted = true）"
        ),
    )


def serve(
    *,
    home: Path,
    profile_name: str,
    read_only: bool,
    transport: str,
    host: str,
    port: int,
    uds: str,
    token_env: str,
    engine_factory: Callable[[Path], Any],
) -> None:
    """解析 Profile → 构建服务 → 按传输运行。Profile 非法时拒绝启动（fail-closed）。"""
    from bacmap.interfaces.mcp.server import build_server

    try:
        profile = resolve_profile(profile_name, home, transport)
    except ProfileNotAllowedError as exc:
        raise SystemExit(str(exc)) from exc

    engine = None if read_only else engine_factory(home)
    server = build_server(engine, profile)

    if transport == "stdio":
        server.run(transport="stdio")
        return

    from bacmap.interfaces.mcp.http import run_http

    token = os.environ.get(token_env, "")
    if not token:
        raise SystemExit(f"HTTP 传输需要 Bearer token（ADR-12）：请先设置环境变量 {token_env}")
    run_http(server, token=token, host=host, port=port, uds=(uds or None))
