"""接口层共享安全响应头（Web/MCP HTTP）。

CSP 面向"自包含、零外联"（ADR-16）：只允许同源资源；脚本/样式不外链；
禁止被 iframe 嵌入、禁止 ``<base>`` 篡改、表单只提交到本机。
"""

from __future__ import annotations

from typing import Any

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-security-policy", CSP.encode("latin-1")),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


def _apply(headers: list[tuple[bytes, bytes]]) -> None:
    """附加安全头（已存在同名者不重复添加）。"""
    present = {h[0].lower() for h in headers}
    for name, value in _SECURITY_HEADERS:
        if name not in present:
            headers.append((name, value))


class SecurityHeadersMiddleware:
    """纯 ASGI：为所有 HTTP 响应附加安全头（含鉴权 401）。"""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                _apply(message.setdefault("headers", []))
            await send(message)

        await self._app(scope, receive, send_wrapper)
