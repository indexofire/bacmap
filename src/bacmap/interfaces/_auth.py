"""接口层共享的 Bearer 鉴权中间件（ADR-12 MCP HTTP / ADR-14 Web 局域网）。

纯 ASGI、无状态、常量时间比较；仅对 HTTP scope 生效。
"""

from __future__ import annotations

import hmac
from typing import Any

_UNAUTHORIZED_HEADERS = [
    (b"content-type", b"text/plain; charset=utf-8"),
    (b"www-authenticate", b"Bearer"),
]


class BearerTokenMiddleware:
    """校验 ``Authorization: Bearer <token>``，失败返回 401。"""

    def __init__(self, app: Any, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenMiddleware 需要非空 token")
        self._app = app
        self._token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        provided = b""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                provided = value
                break
        # 直接比较线字节：token 配置允许含非 latin-1 字符（此前 expected
        # 走 latin-1 编码，CJK token 会直接 UnicodeEncodeError → 500）。
        if not hmac.compare_digest(provided, f"Bearer {self._token}".encode()):
            await send(
                {"type": "http.response.start", "status": 401, "headers": _UNAUTHORIZED_HEADERS}
            )
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await self._app(scope, receive, send)
