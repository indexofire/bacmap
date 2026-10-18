"""Web 浏览器端鉴权（cookie 会话 + CSRF）与 Bearer 兼容（ADR-14；§10 v1.4.15）。

- ``BACMAP_WEB_AUTH=bearer``（默认，向后兼容）：仅 ``Authorization: Bearer``（API 客户端）；
- ``BACMAP_WEB_AUTH=cookie``：浏览器可登录（``/login``）→ 签名会话 cookie；每次状态变更
  POST 需 CSRF 同步令牌（``csrf`` 表单字段 == ``bacmap_csrf`` cookie）+ Origin/Referer 校验。
- 会话 cookie：``HttpOnly; SameSite=Strict; Path=/``，值为 ``sid.exp.sig``（HMAC-SHA256），
  无状态、无需服务端会话表；登录即换新 sid（防会话固定）。``BACMAP_WEB_COOKIE_SECURE=1``
  在 TLS 部署下加 ``Secure``。签名密钥取 ``BACMAP_WEB_SECRET``，缺省由 token 派生。
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import quote, urlparse

from starlette.requests import Request

SESSION_COOKIE = "bacmap_session"
CSRF_COOKIE = "bacmap_csrf"
SESSION_TTL_S = 12 * 3600
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _sign(secret: str, sid: str, exp: int) -> str:
    return hmac.new(secret.encode(), f"{sid}.{exp}".encode(), sha256).hexdigest()


def issue_session(secret: str, ttl: int = SESSION_TTL_S) -> str:
    """签发会话 cookie 值 ``sid.exp.sig``（登录时调用，登录即换新 sid）。"""
    sid = secrets.token_urlsafe(24)
    exp = int(time.time()) + ttl
    return f"{sid}.{exp}.{_sign(secret, sid, exp)}"


def verify_session(secret: str, value: str) -> bool:
    """校验签名与过期时间（常量时间比较签名）。"""
    parts = (value or "").split(".")
    if len(parts) != 3:
        return False
    sid, exp_s, sig = parts
    if not sid:
        return False
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign(secret, sid, exp))


@dataclass(frozen=True)
class WebAuthConfig:
    enabled: bool
    mode: str  # "bearer" | "cookie"
    token: str
    secret: str
    cookie_secure: bool
    ttl_s: int = SESSION_TTL_S

    @classmethod
    def from_env(
        cls, token: str | None, env: Mapping[str, str] | None = None
    ) -> WebAuthConfig:
        env = os.environ if env is None else env
        tok = token or ""
        mode = (env.get("BACMAP_WEB_AUTH") or "bearer").strip().lower()
        if mode not in ("bearer", "cookie"):
            mode = "bearer"
        secret = env.get("BACMAP_WEB_SECRET") or ""
        if not secret:
            secret = sha256(f"bacmap-web:{tok}".encode()).hexdigest() if tok else ""
        return cls(
            enabled=bool(tok),
            mode=mode,
            token=tok,
            secret=secret,
            cookie_secure=env.get("BACMAP_WEB_COOKIE_SECURE") == "1",
        )

    def bearer_ok(self, provided: str) -> bool:
        expected = f"Bearer {self.token}"
        return hmac.compare_digest(provided.encode("latin-1"), expected.encode("latin-1"))

    def cookie_ok(self, value: str) -> bool:
        return bool(self.secret) and verify_session(self.secret, value)

    def session_cookie_kwargs(self) -> dict[str, Any]:
        return {
            "httponly": True,
            "samesite": "strict",
            "secure": self.cookie_secure,
            "path": "/",
            "max_age": self.ttl_s,
        }

    def csrf_cookie_kwargs(self) -> dict[str, Any]:
        # CSRF cookie 需被页面读取填入表单，故 non-HttpOnly；SameSite=Strict 防跨站。
        return {
            "httponly": False,
            "samesite": "strict",
            "secure": self.cookie_secure,
            "path": "/",
        }


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in scope.get("headers", []):
        out[key.decode("latin-1").lower()] = value.decode("latin-1")
    return out


def _cookies(scope: dict[str, Any]) -> dict[str, str]:
    from http.cookies import SimpleCookie

    jar = SimpleCookie()
    try:
        jar.load(_headers(scope).get("cookie", ""))
    except Exception:  # noqa: BLE001 —— 畸形 Cookie 头按无 cookie 处理
        return {}
    return {k: v.value for k, v in jar.items()}


_UNAUTHORIZED_HTML = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>401 · bacmap</title>
<body style="font-family:system-ui,-apple-system,sans-serif;max-width:44em;
margin:3em auto;padding:0 1em;line-height:1.6">
<h1>401 · 需要认证</h1>
<p>当前 Web 控制台为 <b>bearer 模式</b>（仅 <code>Authorization: Bearer</code>）。
浏览器请任选：</p>
<ul>
  <li>设置 <code>BACMAP_WEB_AUTH=cookie</code> 后重启，再访问
      <a href="/login">/login</a> 登录；</li>
  <li>或用 API 方式：<code>curl -H "Authorization: Bearer &lt;token&gt;" …</code>。</li>
</ul>
<p><a href="/login">/login</a> · <a href="/">返回首页</a></p>
</body></html>""".encode()


class WebAuthMiddleware:
    """浏览器(cookie) + API(Bearer) 双通道鉴权；bearer 模式等价于纯 Bearer。"""

    def __init__(self, app: Any, cfg: WebAuthConfig) -> None:
        if not cfg.enabled:
            raise ValueError("WebAuthMiddleware 需要非空 token")
        self._app = app
        self._cfg = cfg

    def _authenticated(self, scope: dict[str, Any]) -> bool:
        header = _headers(scope).get("authorization", "")
        if header and self._cfg.bearer_ok(header):
            return True
        if self._cfg.mode == "cookie":
            return self._cfg.cookie_ok(_cookies(scope).get(SESSION_COOKIE, ""))
        return False

    @staticmethod
    def _accepts_html(scope: dict[str, Any]) -> bool:
        return "text/html" in _headers(scope).get("accept", "")

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/login" or path.startswith("/static/"):
            await self._app(scope, receive, send)
            return
        if self._authenticated(scope):
            await self._app(scope, receive, send)
            return
        method = str(scope.get("method", "GET")).upper()
        # 只有 cookie 模式存在"浏览器登录"：HTML 导航 303 到 /login。
        # bearer 模式若也跳转，会与 /login 的"非 cookie 模式回首页"形成重定向死循环
        #（v1.4.15 引入的缺陷，v1.4.25 修复）。
        if (
            method in SAFE_METHODS
            and self._accepts_html(scope)
            and self._cfg.mode == "cookie"
        ):
            location = "/login?next=" + quote(path, safe="/")
            await send(
                {
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [
                        (b"location", location.encode("latin-1")),
                        (b"content-type", b"text/plain; charset=utf-8"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"redirecting to /login"})
            return
        if self._accepts_html(scope):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"text/html; charset=utf-8"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _UNAUTHORIZED_HTML})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"unauthorized"})


def verify_csrf(request: Request, form_csrf: str) -> bool:
    """状态变更 POST 的 CSRF 校验：bearer 模式放行（无 cookie）；cookie 模式需
    同步令牌一致 + Origin/Referer 同源。"""
    cfg: WebAuthConfig = request.app.state.web_auth
    if not cfg.enabled or cfg.mode != "cookie":
        return True
    host = request.headers.get("host", "")
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    if origin:
        if urlparse(origin).netloc != host:
            return False
    elif referer:
        if urlparse(referer).netloc != host:
            return False
    cookie = request.cookies.get(CSRF_COOKIE, "")
    return bool(cookie) and hmac.compare_digest(cookie, form_csrf or "")


def safe_next(target: str, default: str = "/") -> str:
    """只允许站内路径（防开放重定向）。"""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return default
