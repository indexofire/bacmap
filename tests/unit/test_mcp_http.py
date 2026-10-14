"""MCP Streamable HTTP 传输 + Bearer 鉴权测试（ADR-12）。

- 无/错 token → 401；正确 token → initialize 200。
- 中间件：非 HTTP scope 透传；常量时间比较。
- stdio 默认不变（见 test_mcp_interface.py）。
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from bacmap.interfaces._auth import BearerTokenMiddleware
from bacmap.interfaces.mcp.http import build_http_app
from bacmap.interfaces.mcp.server import build_server

_ACCEPT = {"Accept": "application/json, text/event-stream"}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


class TestBearerTokenMiddleware:
    def test_empty_token_rejected(self):
        with pytest.raises(ValueError):
            BearerTokenMiddleware(app=None, token="")

    def test_missing_and_wrong_token_401_and_right_passes(self):
        seen = {"called": False}

        async def inner(scope, receive, send):
            seen["called"] = True
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = BearerTokenMiddleware(inner, token="tok")

        import anyio

        def call(headers):
            scope = {"type": "http", "headers": headers}
            out = {}

            async def receive():
                return {"type": "http.request"}

            async def send(msg):
                out.update(msg)

            anyio.run(mw, scope, receive, send)
            return out

        assert call([])["status"] == 401
        assert call([(b"authorization", b"Bearer nope")])["status"] == 401
        assert call([(b"authorization", b"Bearer tok")])["status"] == 204
        assert seen["called"] is True

    def test_non_http_scope_passthrough(self):
        import anyio

        seen = {}

        async def inner(scope, receive, send):
            seen["type"] = scope["type"]

        anyio.run(BearerTokenMiddleware(inner, token="tok"), {"type": "lifespan"}, None, None)
        assert seen["type"] == "lifespan"


class TestStreamableHttpEndpoint:
    @pytest.fixture
    def app(self):
        return build_http_app(build_server(), token="s3cr3t")

    def test_build_requires_token(self):
        with pytest.raises(ValueError):
            build_http_app(build_server(), token="")

    def test_initialize_requires_bearer(self, app):
        with TestClient(app, base_url="http://127.0.0.1") as c:
            assert c.post("/mcp", json=_INIT, headers=_ACCEPT).status_code == 401
            bad = {**_ACCEPT, "Authorization": "Bearer wrong"}
            assert c.post("/mcp", json=_INIT, headers=bad).status_code == 401

    def test_initialize_with_valid_bearer(self, app):
        with TestClient(app, base_url="http://127.0.0.1") as c:
            r = c.post(
                "/mcp", json=_INIT, headers={**_ACCEPT, "Authorization": "Bearer s3cr3t"}
            )
        assert r.status_code == 200

    def test_tools_list_over_session(self, app):
        auth = {"Authorization": "Bearer s3cr3t"}
        with TestClient(app, base_url="http://127.0.0.1") as c:
            init = c.post("/mcp", json=_INIT, headers={**_ACCEPT, **auth})
            sid = init.headers.get("mcp-session-id")
            assert sid
            r = c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers={**_ACCEPT, **auth, "mcp-session-id": sid},
            )
        assert r.status_code == 200
        assert "bio_seq_stats" in r.text
        # 只读/计算工具暴露；write 工具不暴露（V11④）
        assert "bio_add_metadata" not in r.text
