"""gaxis upstream adapter: expose the gaxis MCP server as ``bacmap_chart_*`` tools.

Enabled by environment (unset ⇒ no tools, bacmap behaves exactly as before):


    BACMAP_GAXIS_URL=http://127.0.0.1:8770/mcp
    BACMAP_GAXIS_TOKEN=<token from gaxis>





Design constraints (see gaxis AGENTS.md, ADR-03/ADR-05):
  * thin: no paper/chart business logic lives here, only mapping and gating;
  * fail-closed: a tool whose data class exceeds the profile ceiling is never
    registered at all, and a second check runs at call time;
  * bacmap habit: handlers return JSON strings, errors are ``{"error": ...}``;
  * no cache: reproduction is expensive, caching belongs to the knowledge base.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from gaxis.client import DEFAULT_URL, GaxisClient
from gaxis.errors import GaxisError
from gaxis.models.tools import TOOL_SPECS, ToolSpec
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, create_model

from bacmap.interfaces.mcp.profiles import ProfileSpec
from bacmap.tools.spec import DataClass

_logger = logging.getLogger(__name__)

RANK = {"D0": 0, "D1": 1, "D2": 2, "D3": 3, "D4": 4}
JSON_TYPES: dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _input_model(spec: ToolSpec) -> type[BaseModel]:
    """JSON Schema -> pydantic model, so the MCP SDK can rebuild the same schema."""
    properties = spec.input_schema.get("properties", {}) or {}
    required = set(spec.input_schema.get("required", []) or [])
    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        base = JSON_TYPES.get(str(prop.get("type", "string")), str)
        fields[name] = (base, ...) if name in required else (base | None, prop.get("default"))
    return create_model(f"{re.sub(r'\\W', '_', spec.name)}Input", **fields)


def build_upstream(profile: ProfileSpec) -> GaxisUpstream | None:
    """Read BACMAP_GAXIS_* and build the adapter for this profile (None ⇒ disabled)."""
    import os

    url = (os.environ.get("BACMAP_GAXIS_URL") or "").strip()
    if not url:
        return None
    token = (os.environ.get("BACMAP_GAXIS_TOKEN") or "").strip() or None
    host = urlparse(url).hostname or ""
    if not _local_or_private(host):
        if os.environ.get("BACMAP_GAXIS_ALLOW_REMOTE") != "1":
            _logger.warning(
                "gaxis upstream disabled: %r is not loopback/private; "
                "set BACMAP_GAXIS_ALLOW_REMOTE=1 only for D0-D1 public chart services",
                host,
            )
            return None
        if profile.max_data_class > DataClass.D1:
            _logger.warning(
                "gaxis upstream disabled: remote endpoint %r is only allowed at D0-D1",
                host,
            )
            return None
    return GaxisUpstream(
        url=url,
        token=token,
        max_data_class=profile.max_data_class.name,
    )


def _local_or_private(host: str) -> bool:
    """只允许回环/私网/链路本地地址；公网端点需显式开关且限 D0-D1。"""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        return False
    for raw in addresses:
        try:
            ip = ip_address(raw)
        except ValueError:
            return False
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return True


class GaxisUpstream:
    """Maps one gaxis server into the tools visible under a bacmap profile."""

    def __init__(
        self,
        *,
        url: str = DEFAULT_URL,
        token: str | None = None,
        max_data_class: str = "D1",
        prefix: str = "bacmap_chart_",
        timeout_s: float = 600.0,
    ) -> None:
        self.url = url
        self.token = token
        self.max_data_class = max_data_class
        self.prefix = prefix
        self.timeout_s = timeout_s
        if max_data_class not in RANK:
            raise ValueError(f"unknown data class {max_data_class!r}")

    def visible_specs(self) -> list[ToolSpec]:
        ceiling = RANK[self.max_data_class]
        return [spec for spec in TOOL_SPECS if RANK[str(spec.data_class)] <= ceiling]

    def allows(self, spec: ToolSpec) -> bool:
        return RANK[str(spec.data_class)] <= RANK[self.max_data_class]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Call one gaxis tool by its bare name; always returns a JSON string."""
        upstream_name = name.removeprefix(self.prefix)
        spec = next((s for s in TOOL_SPECS if s.name == upstream_name), None)
        if spec is None:
            return json.dumps({"error": f"unknown gaxis tool {upstream_name!r}"})
        if not self.allows(spec):
            return json.dumps(
                {
                    "error": (
                        f"{spec.name} is {spec.data_class}, above the profile ceiling "
                        f"{self.max_data_class}"
                    )
                }
            )
        try:
            self.preflight()
        except OSError as exc:
            return json.dumps({"error": f"gaxis unreachable at {self.url}: {exc}"})
        try:
            async with GaxisClient(self.url, token=self.token, timeout_s=self.timeout_s) as client:
                payload = await client.call_tool(upstream_name, arguments)
        except GaxisError as exc:
            return json.dumps({"error": exc.message, **exc.as_dict()}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": f"gaxis unreachable at {self.url}: {exc}"})
        return json.dumps(payload, ensure_ascii=False)

    def preflight(self, timeout_s: float = 2.0) -> None:
        """Cheap TCP probe: an unreachable gaxis must fail cleanly, not inside anyio teardown."""
        parsed = urlparse(self.url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout_s):
            return

    def call_sync(self, name: str, arguments: dict[str, Any]) -> str:
        """Sync wrapper for bacmap's sync tool handlers."""
        return asyncio.run(self.call(name, arguments))

    def _handler(self, spec: ToolSpec, tool_name: str) -> Any:
        def handler(params: Any) -> str:
            return self.call_sync(tool_name, params.model_dump(exclude_none=True))

        # The MCP SDK reads the runtime annotation to build the JSON Schema.
        handler.__annotations__["params"] = _input_model(spec)
        handler.__name__ = re.sub(r"\W", "_", tool_name)
        handler.__doc__ = f"[gaxis/{spec.data_class}] {spec.summary}"
        return handler

    def register(self, server: MCPServer) -> list[str]:
        registered: list[str] = []
        for spec in self.visible_specs():
            tool_name = f"{self.prefix}{spec.name}"
            description = f"[gaxis/{spec.data_class}] {spec.summary}"
            server.tool(name=tool_name, description=description)(self._handler(spec, tool_name))
            registered.append(tool_name)
        return registered
