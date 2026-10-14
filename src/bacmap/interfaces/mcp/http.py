"""MCP Streamable HTTP 传输（ADR-12：stdio + Streamable HTTP，仅绑本机）。

- 传输：Streamable HTTP，默认 ``127.0.0.1``（或 unix socket）。
- 鉴权：**Bearer token 强制**（ADR-12）；常量时间比较，缺 token 即 401。
- DNS-rebinding 防护：复用 mcp SDK 的 ``TransportSecuritySettings``，只放行
  配置的 host。

stdio 仍是默认传输（本机客户端，如 Hermes/Claude/Codex）；HTTP 用于需要
多客户端/远程隧道的场景，且必须带 token。
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from bacmap.interfaces._auth import BearerTokenMiddleware


def build_http_app(
    server: MCPServer,
    token: str,
    host: str = "127.0.0.1",
    port: int | None = None,
    allowed_hosts: list[str] | None = None,
) -> Any:
    """构建带 Bearer 鉴权的 Streamable HTTP ASGI 应用（ADR-12）。

    ``allowed_hosts`` 默认放行 ``host``、``host:port`` 与回环名，配合 mcp SDK
    的 DNS-rebinding 防护（Host 头校验包含端口）。
    """
    if allowed_hosts is None:
        # 通配端口模式（mcp SDK 支持 "host:*"）——绑定回环时放行任意本地端口。
        allowed_hosts = [host, f"{host}:*", "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]
        if port is not None:
            allowed_hosts.append(f"{host}:{port}")
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
    )
    app = server.streamable_http_app(host=host, transport_security=security)
    return BearerTokenMiddleware(app, token)


def run_http(
    server: MCPServer,
    token: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    uds: str | None = None,
) -> None:
    """在 127.0.0.1:port 或 unix socket 上运行 MCP Streamable HTTP。"""
    import uvicorn

    app = build_http_app(server, token=token, host=host, port=None if uds else port)
    if uds:
        uvicorn.run(app, uds=uds)
    else:
        uvicorn.run(app, host=host, port=port)
