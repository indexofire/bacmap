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
import logging
import os
import secrets
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import quote, urlparse

from starlette.requests import Request

from bacmap.interfaces._security import consteq

_logger = logging.getLogger(__name__)

SESSION_COOKIE = "bacmap_session"
CSRF_COOKIE = "bacmap_csrf"
SESSION_TTL_S = 12 * 3600
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 回环绑定（文档化的免鉴权单机形态；ADR-16 默认只绑本机）
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})
_WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::"})  # noqa: S104 — 仅用于识别通配绑定
ALLOWED_HOSTS_ENV = "BACMAP_WEB_ALLOWED_HOSTS"


def require_auth_when_exposed(
    host: str, token: str | None, *, prog: str = "bacmap start web"
) -> None:
    """非回环绑定且未配置 token 时拒绝启动（对齐 MCP HTTP 的 fail-fast，ADR-14/16）。

    ``BACMAP_DEBUG=1`` 或 ``[debug] enabled=true`` 时放行（开发模式），但会打印醒目警告。
    回环免鉴权是文档化的单机形态；非回环一旦放开，任务提交/审批签名就
    暴露给整个网段——漏配 token 不应静默降级为无鉴权（v1.4.13 巡检后收紧）。
    """
    from bacmap.config import debug_mode, debug_warning

    if debug_mode():
        _logger.warning(debug_warning(prog))
        return
    if token or host in _LOOPBACK_HOSTS:
        return
    from bacmap.interfaces.i18n import T

    raise SystemExit(
        T(
            f"[{prog}] refusing to start: bound to non-loopback address {host!r} "
            "without an auth token.\n"
            f"Set BACMAP_WEB_TOKEN (or the env var named by --token-env) and restart, "
            "or bind a loopback address (--host 127.0.0.1).",
            f"[{prog}] 拒绝启动：绑定非本机地址 {host!r} 但未设置鉴权 token。\n"
            "请设置 BACMAP_WEB_TOKEN（或 --token-env 指定的环境变量）后重启，"
            "或改绑回环地址（--host 127.0.0.1）。",
        )
    )


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
        from bacmap.config import debug_mode

        if debug_mode():
            # 开发模式：完全免鉴权/免 CSRF。中间件不会挂载，Web 页面直接可访问。
            return cls(
                enabled=False,
                mode="bearer",
                token="",
                secret="",
                cookie_secure=False,
            )
        tok = token or ""
        mode = (env.get("BACMAP_WEB_AUTH") or "bearer").strip().lower()
        if mode not in ("bearer", "cookie"):
            # 静默回退会掩盖配置错误（如 cookie 拼错落回 bearer，浏览器 401 难排查）。
            _logger.warning(
                "invalid BACMAP_WEB_AUTH=%r (expected 'bearer' or 'cookie');"
                " falling back to 'bearer'",
                mode,
            )
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
        # provided 来自 latin-1 解码的请求头，重新编码即还原线字节；
        # expected 走 UTF-8——token 含非 latin-1 字符不再编码崩溃 → 500。
        return hmac.compare_digest(
            provided.encode("latin-1"), f"Bearer {self.token}".encode()
        )

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
    except Exception:
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


def normalize_host(value: str) -> str:
    """Host 头/绑定地址 → 小写主机名（去端口、IPv6 方括号与末尾点）。"""
    v = value.strip().lower()
    if v.startswith("["):
        end = v.find("]")
        v = v[1:end] if end != -1 else v[1:]
    elif v.count(":") == 1:
        v = v.split(":", 1)[0]
    return v.rstrip(".")


def web_allowed_hosts(
    bind_host: str, *, allow_any: bool, env: Mapping[str, str] | None = None
) -> frozenset[str] | None:
    """Web 控制台 Host 白名单（防 DNS rebinding）；``None`` = 不校验。

    回环名 + 绑定地址（通配绑定时加本机主机名）+ ``BACMAP_WEB_ALLOWED_HOSTS``
    （逗号分隔，反向代理/局域网域名用）。``*`` 仅在已启用鉴权时生效：无鉴权
    的控制台关掉 Host 校验等于把数据交给任意网页。
    """
    env = os.environ if env is None else env
    hosts = set(_LOOPBACK_HOSTS)
    bind = normalize_host(bind_host)
    if bind in _WILDCARD_BINDS:
        hosts.update(normalize_host(n) for n in (socket.gethostname(), socket.getfqdn()))
    else:
        hosts.add(bind)
    for item in (env.get(ALLOWED_HOSTS_ENV) or "").split(","):
        item = item.strip()
        if item == "*":
            if allow_any:
                return None
            _logger.warning(
                "%s='*' ignored: Web auth is disabled, Host checking stays on",
                ALLOWED_HOSTS_ENV,
            )
        elif item:
            hosts.add(normalize_host(item))
    hosts.discard("")
    return frozenset(hosts)


class HostAllowlistMiddleware:
    """纯 ASGI：Host 头不在白名单即 400（DNS rebinding 防护，对齐 MCP HTTP）。"""

    def __init__(self, app: Any, allowed_hosts: frozenset[str]) -> None:
        self._app = app
        self._allowed = allowed_hosts

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        host = normalize_host(_headers(scope).get("host", ""))
        if host and host in self._allowed:
            await self._app(scope, receive, send)
            return
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": b"invalid host header"})


def _cross_site_browser_request(request: Request) -> bool:
    """无鉴权模式下识别浏览器跨站请求（Sec-Fetch-Site → 自定义头 → Origin/Referer）。

    自定义 ``X-CSRF-Token`` 头跨源必须过 CORS 预检（本应用不开 CORS），带它即
    同源或非浏览器客户端；``Origin: null``（no-referrer/沙箱 iframe）视为跨站。
    """
    site = request.headers.get("sec-fetch-site", "")
    if site:
        return site not in ("same-origin", "none")
    if "x-csrf-token" in request.headers:
        return False
    source = request.headers.get("origin", "") or request.headers.get("referer", "")
    if not source:
        return False
    return urlparse(source).netloc != request.headers.get("host", "")


def verify_csrf(request: Request, form_csrf: str) -> bool:
    """状态变更 POST 的 CSRF 校验：无鉴权时拒绝浏览器跨站请求；bearer 模式放行
    （无 cookie）；cookie 模式需同步令牌一致 + Origin/Referer 同源。"""
    cfg: WebAuthConfig = request.app.state.web_auth
    if not cfg.enabled:
        return not _cross_site_browser_request(request)
    if cfg.mode != "cookie":
        return True
    host = request.headers.get("host", "")
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    source = origin or referer
    if source and urlparse(source).netloc != host:
        return False
    cookie = request.cookies.get(CSRF_COOKIE, "")
    return bool(cookie) and consteq(cookie, form_csrf or "")


def safe_next(target: str, default: str = "/") -> str:
    """只允许站内路径（防开放重定向）。

    浏览器会把 ``/\\evil.com`` 规范化为协议相对 URL（等同 ``//evil.com``），
    只检查 ``//`` 前缀仍可被绕过（v1.9.2 巡检）；控制字符还会污染 Location 头。
    """
    if not target.startswith("/") or target.startswith("//"):
        return default
    if "\\" in target or any(ch in target for ch in "\r\n\0"):
        return default
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return default
    return target
