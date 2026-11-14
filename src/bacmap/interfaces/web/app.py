"""bacmap Web 应用（ADR-14）。

FastAPI 托管 Vue 3 控制台（静态产物）、JSON API `/api/v1`、登录/认证与样本 HTML 报告。
旧 Jinja 任务台已移除，旧路径 307 重定向到 `/console/...`；高级研究写操作暂留 Jinja。
路由一律同步 def——引擎的 DBOS 同步 API 不得在事件循环内调用
（retrieve_workflow 会 RuntimeError），FastAPI 把同步路由放线程池执行。
create_app(engine) 与 build_server(engine) 同构——引擎注入，测试可换。
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from bacmap.interfaces._security import SecurityHeadersMiddleware, consteq
from bacmap.interfaces.views import report_path
from bacmap.interfaces.web.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    HostAllowlistMiddleware,
    WebAuthConfig,
    WebAuthMiddleware,
    issue_session,
    safe_next,
    verify_csrf,
    web_allowed_hosts,
)
from bacmap.interfaces.web.static import STATIC_DIR
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tools._common import _validate_sample_id


class _Templates(Jinja2Templates):
    """注入 CSRF 令牌与鉴权模式（表单隐藏字段、登出入口用）。"""

    def TemplateResponse(
        self,
        request: Request,
        name: str,
        context: dict[str, Any] | None = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Any:
        ctx = dict(context or {})
        ctx.setdefault("csrf", request.cookies.get(CSRF_COOKIE, ""))
        cfg = getattr(request.app.state, "web_auth", None)
        ctx.setdefault("auth_mode", cfg.mode if cfg else "bearer")
        ctx.setdefault("auth_enabled", bool(cfg and cfg.enabled))
        return super().TemplateResponse(
            request,
            name,
            ctx,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )


_TEMPLATES = _Templates(directory=str(Path(__file__).parent / "templates"))

logger = logging.getLogger(__name__)

# 报告模板版本标记：旧模板生成的 HTML 在首次访问时原地重渲染。
_REPORT_MARKER = b'name="bacmap-report" content="12"'
_REPORT_LOCK = threading.Lock()


def _report_is_current(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return _REPORT_MARKER in fh.read(4096)
    except OSError:
        return False


def _ensure_current_report(engine: DbosTaskEngine, sample_id: str, path: Path) -> None:
    """把旧版浅色报告升级为当前暗色模板（有 summary 才重渲染）。

    只读请求触发一次幂等写入；失败时保留旧文件继续可读。
    """
    if _report_is_current(path):
        return
    summary = path.parent / f"{sample_id}_summary.json"
    if not summary.is_file():
        return
    if not _REPORT_LOCK.acquire(blocking=False):
        return  # 另一个请求正在重渲染；先返回现有文件
    try:
        if _report_is_current(path):
            return
        from bacmap.tools.pipeline import generate_report

        out = generate_report(
            {"sample_id": sample_id, "results_dir": str(Path(engine.home) / "results")}
        )
        if not _report_is_current(path):
            logger.warning("报告重渲染未生效 sample=%s out=%s", sample_id, out[:300])
    except Exception:
        logger.warning("报告重渲染失败 sample=%s", sample_id, exc_info=True)
    finally:
        _REPORT_LOCK.release()



def _ensure_prelim_report(engine: DbosTaskEngine, sample_id: str) -> Path | None:
    """从 prelim summary 按需生成初步报告 HTML（幂等缓存；无 prelim 返回 None）。"""
    base = Path(engine.home) / "results" / sample_id / "report"
    prelim_html = base / f"{sample_id}_report.prelim.html"
    prelim_summary = base / f"{sample_id}_summary.prelim.json"
    if not prelim_summary.is_file():
        return None
    if prelim_html.is_file():
        return prelim_html
    if not _REPORT_LOCK.acquire(blocking=False):
        return prelim_html if prelim_html.is_file() else None
    try:
        if prelim_html.is_file():
            return prelim_html
        import json as _json

        from bacmap.core.verify.deterministic_verifier import DeterministicVerifier
        from bacmap.tools._scripts.generate_report import generate_html

        summary = _json.loads(prelim_summary.read_text(encoding="utf-8"))
        verification = DeterministicVerifier().verify_all(summary)
        generate_html(sample_id, summary, verification, prelim_html)
        return prelim_html
    except Exception:
        logger.warning("prelim 报告生成失败 sample=%s", sample_id, exc_info=True)
        return None
    finally:
        _REPORT_LOCK.release()


def _build_auth_routes(app: FastAPI, cfg: WebAuthConfig) -> None:
    """登录/登出（cookie 模式登录；bearer/未启用模式给说明页）。"""

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/") -> HTMLResponse:
        # 始终渲染（不重定向）：cookie 模式给登录表单；bearer/未启用模式给说明页。
        # 旧实现在非 cookie 模式 303 回首页，与中间件"HTML→/login"形成死循环（v1.4.25 修复）。
        return _TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {
                "next": safe_next(next),
                "error": None,
                "mode": cfg.mode if cfg.enabled else "disabled",
            },
        )

    @app.post("/login", response_class=HTMLResponse)
    def login_submit(
        request: Request, token: str = Form(...), next: str = Form("/")
    ) -> Response:
        if not (cfg.enabled and cfg.mode == "cookie"):
            return RedirectResponse("/", status_code=303)
        host = request.headers.get("host", "")
        origin = request.headers.get("origin", "")
        if origin and urlparse(origin).netloc != host:
            raise HTTPException(403, "cross-origin login rejected")
        if not consteq(token, cfg.token):
            return _TEMPLATES.TemplateResponse(
                request,
                "login.html",
                {"next": safe_next(next), "error": "令牌不正确"},
                status_code=401,
            )
        resp = RedirectResponse(safe_next(next), status_code=303)
        resp.set_cookie(
            SESSION_COOKIE, issue_session(cfg.secret, cfg.ttl_s), **cfg.session_cookie_kwargs()
        )
        resp.set_cookie(
            CSRF_COOKIE, secrets.token_urlsafe(24), **cfg.csrf_cookie_kwargs()
        )
        return resp

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")) -> RedirectResponse:
        # 登出也过 CSRF（bearer 模式放行）：跨站不得强制登出用户（骚扰面）。
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        resp.delete_cookie(CSRF_COOKIE, path="/")
        return resp


def _build_sample_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    """样本 HTML 报告：内嵌到 SPA 样本页，旧深链重定向回面板。"""

    @app.get("/samples/{sample_id}/report")
    def sample_report(
        sample_id: str, download: int = 0, embed: int = 0, theme: str = ""
    ) -> Response:
        if not _validate_sample_id(sample_id):
            raise HTTPException(400, "非法样本 ID")
        final_path = report_path(engine, sample_id)
        # v1.10.24 流式首屏：最终报告缺失时——有最终 summary 先按需重渲染，
        # 否则 prelim summary 存在则生成/提供初步报告（注释完成前 web 即可
        # 查看分型与 AMR 结果）。选定产物后统一走下面的 sandbox CSP /
        # 主题注入 / 嵌套控制——prelim 分支此前直接 return 裸 FileResponse，
        # 被外层默认 frame-ancestors 'none' + X-Frame-Options: DENY 拦截，
        # 控制台“完整报告”页签在流式阶段空白（浏览器 framing 策略单测不可见）。
        path = final_path
        if not path.is_file() and not download:
            if (path.parent / f"{sample_id}_summary.json").is_file():
                _ensure_current_report(engine, sample_id, path)
            if not path.is_file():
                prelim_html = _ensure_prelim_report(engine, sample_id)
                if prelim_html is not None:
                    path = prelim_html
        if not path.is_file():
            raise HTTPException(404, "该样本尚未生成 HTML 报告")
        if path == final_path:
            _ensure_current_report(engine, sample_id, path)
        # v1.10.29：完整报告是独立页面（自带目录/返回控制台），不再 iframe 嵌入。
        # 直接访问即内联展示；?download=1 仍为附件。
        # 报告是自包含 HTML，用 sandbox CSP 隔离：禁脚本、禁外联、禁同源读取；
        # 只允许同源页面把它嵌入（样本详情的报告页签）。
        csp = (
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:; frame-ancestors 'self'"
        )
        headers = {
            "Content-Security-Policy": csp,
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Disposition": (
                f'attachment; filename="{sample_id}_report.html"'
                if download
                else f'inline; filename="{sample_id}_report.html"'
            ),
        }
        # 控制台浅色/灰色主题：按请求注入 report token，不修改磁盘产物。
        if theme in {"light", "gray"}:
            html = path.read_text(encoding="utf-8")
            html = html.replace(
                '<html lang="zh-CN">',
                f'<html lang="zh-CN" data-report-theme="{theme}">',
                1,
            )
            return HTMLResponse(html, headers=headers)
        return FileResponse(
            path,
            media_type="text/html",
            content_disposition_type="attachment" if download else "inline",
            headers=headers,
        )


def _build_redirect_routes(app: FastAPI) -> None:  # noqa: C901
    """旧 HTML 路径 → Vue SPA 客户端路由（保留书签，不再渲染旧模板）。"""

    def _q(request: Request) -> str:
        return f"?{request.url.query}" if request.url.query else ""

    @app.get("/legacy", include_in_schema=False)
    def legacy_redirect() -> RedirectResponse:
        return RedirectResponse("/console/", status_code=307)

    @app.get("/tasks", include_in_schema=False)
    def tasks_redirect() -> RedirectResponse:
        return RedirectResponse("/console/tasks", status_code=307)

    @app.get("/tasks/{task_id}", include_in_schema=False)
    def task_redirect(task_id: str, request: Request) -> RedirectResponse:
        return RedirectResponse(f"/console/tasks/{task_id}{_q(request)}", status_code=307)

    @app.get("/tasks/{task_id}/fragment", include_in_schema=False)
    def task_fragment_redirect(task_id: str) -> RedirectResponse:
        return RedirectResponse(f"/console/tasks/{task_id}", status_code=307)

    @app.get("/plans", include_in_schema=False)
    def plans_redirect() -> RedirectResponse:
        return RedirectResponse("/console/plans", status_code=307)

    @app.get("/plans/{plan_id}", include_in_schema=False)
    def plan_redirect(plan_id: str, request: Request) -> RedirectResponse:
        return RedirectResponse(f"/console/plans/{plan_id}{_q(request)}", status_code=307)

    @app.get("/records", include_in_schema=False)
    def records_redirect() -> RedirectResponse:
        return RedirectResponse("/console/records", status_code=307)

    @app.get("/runs", include_in_schema=False)
    def runs_redirect() -> RedirectResponse:
        return RedirectResponse("/console/runs", status_code=307)

    @app.get("/runs/{run_id}", include_in_schema=False)
    def run_redirect(run_id: str, request: Request) -> RedirectResponse:
        return RedirectResponse(f"/console/runs/{run_id}{_q(request)}", status_code=307)

    @app.get("/gom", include_in_schema=False)
    def gom_redirect() -> RedirectResponse:
        return RedirectResponse("/console/gom", status_code=307)

    @app.get("/gom/{object_id}", include_in_schema=False)
    def gom_object_redirect(object_id: str, request: Request) -> RedirectResponse:
        return RedirectResponse(f"/console/gom/{object_id}{_q(request)}", status_code=307)

    @app.get("/samples", include_in_schema=False)
    def samples_redirect() -> RedirectResponse:
        return RedirectResponse("/console/samples", status_code=307)

    @app.get("/samples/{sample_id}", include_in_schema=False)
    def sample_redirect(sample_id: str) -> RedirectResponse:
        return RedirectResponse(f"/console/samples/{sample_id}", status_code=307)

    @app.get("/search", include_in_schema=False)
    def search_redirect(request: Request) -> RedirectResponse:
        return RedirectResponse(f"/console/search{_q(request)}", status_code=307)

    @app.get("/overview", include_in_schema=False)
    def overview_redirect() -> RedirectResponse:
        return RedirectResponse("/console/overview", status_code=307)


def create_app(
    engine: DbosTaskEngine, auth_token: str | None = None, host: str = "127.0.0.1"
) -> FastAPI:
    """组装 Web 应用：中间件/静态 + 六组页面路由 + /api/v1。

    页面组：auth / sample / task / plan / record / evidence（运行记录与 GOM）。
    """
    app = FastAPI(title="bacmap", docs_url=None, redoc_url=None)
    cfg = WebAuthConfig.from_env(auth_token)
    # v1.10.24 智能体对话嵌入：读 [[web.agent_embed]]，origin 进 CSP frame-src。
    from bacmap.config import config_path as _active_config_path
    from bacmap.interfaces.web.agent_embed import load_agent_embeds

    agent_embeds = load_agent_embeds(_active_config_path(engine.home))
    app.state.agent_embeds = agent_embeds
    app.state.web_auth = cfg
    # v1.10.30：周期进度 + 智能体回调投递（Web 进程通常承载长任务）。
    from bacmap.tasks.notifier import start as start_task_notifier

    start_task_notifier(engine.home)
    if cfg.enabled:
        # ADR-14/v1.4.15：bearer（API）与 cookie（浏览器）双通道；cookie 模式配 CSRF。
        app.add_middleware(WebAuthMiddleware, cfg=cfg)
    # DNS rebinding 防护：任何模式都校验 Host（位于鉴权外层、安全头内层）。
    allowed_hosts = web_allowed_hosts(host, allow_any=cfg.enabled)
    if allowed_hosts is not None:
        app.add_middleware(HostAllowlistMiddleware, allowed_hosts=allowed_hosts)
    # 安全响应头（含 CSP）：最后加入 → 位于最外层，鉴权 401/303 也带安全头。
    # v1.10.24：配置了智能体嵌入时，其回环 origin 加入 frame-src（default-src
    # 'self' 会拦跨源 iframe；仅放行配置内显式声明的本机地址）。
    # /research 工具页被控制台 iframe 嵌入（LegacyEmbedView）→ 同源 framing。
    _frame_sources = [e.origin for e in agent_embeds if e.origin]
    app.add_middleware(
        SecurityHeadersMiddleware,
        extra_frame_sources=_frame_sources,
        sameorigin_prefixes=("/research",),
    )
    # 静态资源仅本地（CSS/图标/脚本；零外联，ADR-16）
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # v1.10.24：SPA 资源经 /console/assets/ 可达（<base href="/console/"> 的
    # 相对路径解析正确；否则 catch-all 返回 HTML 导致 MIME type 错误）。
    console_assets = STATIC_DIR / "console" / "assets"
    if console_assets.is_dir():
        app.mount(
            "/console/assets",
            StaticFiles(directory=console_assets),
            name="console-assets",
        )

    # v0.2.0：Vue 3 SPA 控制台（构建产物在 static/console；无 Node 运行时）。
    console_index = STATIC_DIR / "console" / "index.html"

    @app.get("/console", response_class=HTMLResponse, include_in_schema=False)
    def console_root() -> Response:
        return RedirectResponse("/console/", status_code=307)

    @app.get("/console/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    def console(path: str = "") -> FileResponse:
        if not console_index.is_file():
            raise HTTPException(
                503,
                "前端尚未构建：在仓库根目录运行 `pixi run -e web web-build`",
            )
        return FileResponse(console_index)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/console/", status_code=307)

    _build_auth_routes(app, cfg)
    _build_sample_routes(app, engine)
    _build_redirect_routes(app)

    from bacmap.interfaces.web.gvixb import build_gvixb_routes

    build_gvixb_routes(app, engine, _TEMPLATES)

    from bacmap.interfaces.web.research import build_research_routes

    build_research_routes(app, engine)

    from bacmap.interfaces.web.api import build_api_routes

    build_api_routes(app, engine)
    return app
