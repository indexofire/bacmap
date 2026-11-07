"""MCP 服务启动（``bacmap start mcp`` 与 ``python -m bacmap.interfaces.mcp`` 共用）。"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.interfaces.mcp.profiles import McpProfile, ProfileNotAllowedError, resolve_profile


def add_profile_argument(parser: Any) -> None:
    parser.add_argument(
        "--profile",
        choices=[p.value for p in McpProfile],
        default=McpProfile.CLOUD.value,
        help=T(
            "data-class Profile (default cloud: tool outputs ≤ cloud_max_data_class; "
            "local-trusted sees up to D4 and requires config.toml "
            "[mcp] allow_local_trusted = true)",
            "数据级别 Profile（默认 cloud：工具输出 ≤ cloud_max_data_class；"
            "local-trusted 可见至 D4，需 config.toml [mcp] allow_local_trusted = true）",
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
    from bacmap.config import debug_mode, debug_warning
    from bacmap.interfaces.mcp.server import build_server

    if debug_mode():
        print(debug_warning("bacmap start mcp"), file=sys.stderr)
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
        raise SystemExit(
            T(
                f"HTTP transport requires a bearer token (ADR-12): "
                f"set the {token_env} environment variable first",
                f"HTTP 传输需要 Bearer token（ADR-12）：请先设置环境变量 {token_env}",
            )
        )
    run_http(server, token=token, host=host, port=port, uds=(uds or None))
