"""bacmap Web 任务页（ADR-14）。

FastAPI + Jinja2 + 内联轮询 JS（离线无 CDN 依赖，满足 C1）。
路由一律同步 def——引擎的 DBOS 同步 API 不得在事件循环内调用
（retrieve_workflow 会 RuntimeError），FastAPI 把同步路由放线程池执行。
页面：任务列表 / 提交（analyze|curate）/ 详情+状态轮询 / 审批签名 / 系统概览（只读）。
create_app(engine) 与 build_server(engine) 同构——引擎注入，测试可换。
"""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from bacmap.interfaces._security import SecurityHeadersMiddleware
from bacmap.interfaces.views import (
    load_summaries,
    overview_data,
    report_path,
    sample_digest,
    search_rows,
)
from bacmap.interfaces.web.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    WebAuthConfig,
    WebAuthMiddleware,
    issue_session,
    safe_next,
    verify_csrf,
)
from bacmap.interfaces.web.static import STATIC_DIR
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.spec import Approval, TaskId, TaskType
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

_MAX_ASSISTANT_SESSIONS = 32  # 会话上限（LRU 淘汰；防无界增长/内存泄漏）
_MAX_PROMPT_LEN = 8000  # 单轮需求文本上限（防超大表单/提示词）


def create_app(engine: DbosTaskEngine, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="bacmap", docs_url=None, redoc_url=None)
    cfg = WebAuthConfig.from_env(auth_token)
    app.state.web_auth = cfg
    if cfg.enabled:
        # ADR-14/v1.4.15：bearer（API）与 cookie（浏览器）双通道；cookie 模式配 CSRF。
        app.add_middleware(WebAuthMiddleware, cfg=cfg)
    # 安全响应头（含 CSP）：最后加入 → 位于最外层，鉴权 401/303 也带安全头。
    app.add_middleware(SecurityHeadersMiddleware)
    # 静态资源仅本地（CSS/图标/脚本；零外联，ADR-16）
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # -- 登录 / 登出（cookie 模式；bearer 模式下 /login 直接回首页） --------------

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/"):
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
    ):
        if not (cfg.enabled and cfg.mode == "cookie"):
            return RedirectResponse("/", status_code=303)
        host = request.headers.get("host", "")
        origin = request.headers.get("origin", "")
        if origin and urlparse(origin).netloc != host:
            raise HTTPException(403, "cross-origin login rejected")
        if not hmac.compare_digest(token, cfg.token):
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
    def logout() -> RedirectResponse:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        resp.delete_cookie(CSRF_COOKIE, path="/")
        return resp

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "index.html", {"tasks": engine.list_tasks()}
        )

    @app.get("/overview", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(request, "overview.html", overview_data(engine))

    @app.get("/samples", response_class=HTMLResponse)
    def samples_page(request: Request) -> HTMLResponse:
        rows = [sample_digest(s) for s in load_summaries(engine)]
        return _TEMPLATES.TemplateResponse(request, "samples.html", {"rows": rows})

    @app.get("/samples/{sample_id}", response_class=HTMLResponse)
    def sample_detail(request: Request, sample_id: str) -> HTMLResponse:
        if not _validate_sample_id(sample_id):
            raise HTTPException(400, "非法样本 ID")
        summary = next(
            (s for s in load_summaries(engine) if s["_sample_id"] == sample_id), None
        )
        if summary is None:
            raise HTTPException(404, "样本不存在")
        d = sample_digest(summary)
        d["has_report"] = report_path(engine, sample_id).is_file()
        return _TEMPLATES.TemplateResponse(request, "sample_detail.html", {"d": d})

    @app.get("/samples/{sample_id}/report")
    def sample_report(sample_id: str, download: int = 0) -> FileResponse:
        if not _validate_sample_id(sample_id):
            raise HTTPException(400, "非法样本 ID")
        path = report_path(engine, sample_id)
        if not path.is_file():
            raise HTTPException(404, "该样本尚未生成 HTML 报告")
        # 默认**内联查看**（用户点"查看"的预期）；`?download=1` 才作为附件下载。
        # 报告是自包含 HTML（内联 <style>），用 sandbox CSP 隔离：禁脚本、禁外联、
        # 唯一不透明源（即使报告里混入不可信文本也无法读取同源 cookie/发起请求）。
        csp = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        return FileResponse(
            path,
            media_type="text/html",
            filename=f"{sample_id}_report.html",
            content_disposition_type="attachment" if download else "inline",
            headers={"Content-Security-Policy": csp},
        )

    @app.get("/search", response_class=HTMLResponse)
    def search_page(
        request: Request,
        query: str = "",
        serotype: str = "",
        mlst_st: str = "",
        amr_gene: str = "",
    ) -> HTMLResponse:
        rows = [sample_digest(s) for s in load_summaries(engine)]
        hits = search_rows(
            rows, query=query, serotype=serotype, mlst_st=mlst_st, amr_gene=amr_gene
        )
        return _TEMPLATES.TemplateResponse(
            request,
            "search.html",
            {
                "hits": hits,
                "query": query,
                "serotype": serotype,
                "mlst_st": mlst_st,
                "amr_gene": amr_gene,
            },
        )

    @app.post("/tasks/submit")
    def submit_task(
        request: Request,
        task_type: str = Form(...),
        samples: str = Form(""),
        scope: str = Form(""),
        csrf: str = Form(""),
    ) -> RedirectResponse:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            tt = TaskType(task_type)
        except ValueError as exc:
            raise HTTPException(400, f"未知任务类型: {task_type}") from exc
        # 表单仅提供 analyze|curate；mine/write 属开放路径，需 script/draft 参数，
        # 不经本表单提交（防止伪造 POST 产生空任务）。
        if tt not in (TaskType.ANALYZE, TaskType.CURATE):
            raise HTTPException(400, f"任务类型 {tt.value!r} 不支持 Web 提交")
        params: dict[str, Any] = {}
        if samples.strip():
            sample_list = [s.strip() for s in samples.replace("\n", ",").split(",") if s.strip()]
            bad = [s for s in sample_list if not _validate_sample_id(s)]
            if bad:
                raise HTTPException(400, f"非法样本 ID: {bad!r}")
            params["samples"] = sample_list
        if scope.strip():
            try:
                params["scope"] = json.loads(scope)
            except ValueError as exc:
                raise HTTPException(400, "scope 不是合法 JSON") from exc
        try:
            tid = engine.submit(tt, params, submitted_by="web")
        except (ValueError, NotImplementedError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/tasks/{tid}", status_code=303)

    def _status_or_404(task_id: str):
        try:
            return engine.status(TaskId(task_id))
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_detail(request: Request, task_id: str) -> HTMLResponse:
        st = _status_or_404(task_id)
        return _TEMPLATES.TemplateResponse(
            request, "task_detail.html", {"st": st, "task_id": task_id}
        )

    @app.get("/tasks/{task_id}/fragment", response_class=HTMLResponse)
    def task_fragment(request: Request, task_id: str) -> HTMLResponse:
        st = _status_or_404(task_id)
        return _TEMPLATES.TemplateResponse(
            request, "task_fragment.html", {"st": st, "task_id": task_id}
        )

    @app.post("/tasks/{task_id}/approve")
    def approve_task(
        request: Request,
        task_id: str,
        approver: str = Form(...),
        decision: str = Form(...),
        signature: str = Form(...),
        csrf: str = Form(""),
    ) -> RedirectResponse:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        if decision not in ("approve", "reject"):
            raise HTTPException(400, "decision 必须是 approve|reject")
        typed_decision: Literal["approve", "reject"] = (
            "approve" if decision == "approve" else "reject"
        )
        try:
            engine.approve(
                TaskId(task_id),
                Approval(
                    approver=approver,
                    decision=typed_decision,
                    signature=signature,
                    at=datetime.now(UTC),
                ),
            )
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    # -- 会话式助手（LLM 规划 → 确认 → 提交） --------------------------------

    _agent_sessions: dict[str, dict[str, Any]] = {}

    @app.get("/assistant", response_class=HTMLResponse)
    def assistant_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "assistant.html", {"sid": "", "reply": None, "text": "", "results": None}
        )

    def _new_session(sid: str) -> None:
        from bacmap.interfaces.assistant import build_session

        # LRU 上限：超限淘汰最旧会话（其 LLM 历史随之释放）。
        if len(_agent_sessions) >= _MAX_ASSISTANT_SESSIONS:
            oldest = min(_agent_sessions, key=lambda k: _agent_sessions[k]["at"])
            _agent_sessions.pop(oldest, None)
        _agent_sessions[sid] = {
            "session": build_session(engine),
            "plan": None,
            "at": datetime.now(UTC),
        }

    @app.post("/assistant", response_class=HTMLResponse)
    def assistant_ask(
        request: Request, text: str = Form(...), sid: str = Form(""), csrf: str = Form("")
    ) -> HTMLResponse:
        from uuid import uuid4

        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        prompt = text.strip()
        if not prompt:
            raise HTTPException(400, "需求不能为空")
        if len(prompt) > _MAX_PROMPT_LEN:
            raise HTTPException(413, f"需求过长（上限 {_MAX_PROMPT_LEN} 字符）")

        if not sid or sid not in _agent_sessions:
            sid = uuid4().hex
            _new_session(sid)
        entry = _agent_sessions[sid]
        entry["at"] = datetime.now(UTC)
        reply = entry["session"].respond(prompt)
        entry["plan"] = reply.plan
        return _TEMPLATES.TemplateResponse(
            request,
            "assistant.html",
            {"sid": sid, "reply": reply, "text": "", "results": None},
        )

    @app.post("/assistant/execute", response_class=HTMLResponse)
    def assistant_execute(
        request: Request, sid: str = Form(...), csrf: str = Form("")
    ) -> HTMLResponse:
        from bacmap.interfaces.assistant import execute_plan

        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        entry = _agent_sessions.get(sid)
        plan = entry["plan"] if entry else None
        if plan is None or not plan.tasks:
            raise HTTPException(400, "没有待执行的计划")
        results = execute_plan(engine, plan, submitted_by="web")
        if entry is not None:
            entry["plan"] = None
        return _TEMPLATES.TemplateResponse(
            request,
            "assistant.html",
            {"sid": sid, "reply": None, "text": "", "results": results},
        )

    return app
