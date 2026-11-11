"""接口层共享安全响应头（Web/MCP HTTP）。

CSP 面向"自包含、零外联"（ADR-16）：只允许同源资源；脚本/样式不外链；
禁止被 iframe 嵌入、禁止 ``<base>`` 篡改、表单只提交到本机。
"""

from __future__ import annotations

from typing import Any

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    # Vue 3 控制台使用少量一次性 style 属性（间距/尺寸）；脚本仍禁止内联与 eval。
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    # v1.10.24：SPA 用 <base href="/console/"> 解析懒加载资源路径——
    # 允许同源 base（DSH 代理改写为 /bacmap/console/ 后仍同源）。
    "base-uri 'self'; "
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


def _csp_with_frame_sources(sources: list[str]) -> str:
    """default-src 'self' 下跨源 iframe 会被拦——追加 frame-src 白名单。"""
    if not sources:
        return CSP
    return CSP + f"; frame-src 'self' {' '.join(sources)}"


def _apply(headers: list[tuple[bytes, bytes]]) -> None:
    """附加安全头（已存在同名者不重复添加）。"""
    present = {h[0].lower() for h in headers}
    for name, value in _SECURITY_HEADERS:
        if name not in present:
            headers.append((name, value))


class SecurityHeadersMiddleware:
    """纯 ASGI：为所有 HTTP 响应附加安全头（含鉴权 401）。

    ``extra_frame_sources``（v1.10.24）：显式放行进 CSP ``frame-src`` 的
    origin（bacmap 页面里嵌入本机智能体 UI 用；缺省为空 = 沿用
    default-src 'self' 的最严格行为）。
    """

    def __init__(self, app: Any, extra_frame_sources: list[str] | None = None) -> None:
        self._app = app
        sources = [s for s in (extra_frame_sources or []) if s]
        self._headers: list[tuple[bytes, bytes]] = [
            (b"content-security-policy", _csp_with_frame_sources(sources).encode("latin-1")),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"cross-origin-opener-policy", b"same-origin"),
        ]

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {h[0].lower() for h in headers}
                for name, value in self._headers:
                    if name not in present:
                        headers.append((name, value))
            await send(message)

        await self._app(scope, receive, send_wrapper)
