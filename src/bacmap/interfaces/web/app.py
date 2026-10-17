"""bacmap Web 任务页（ADR-14）。

FastAPI + Jinja2 + 内联轮询 JS（离线无 CDN 依赖，满足 C1）。
路由一律同步 def——引擎的 DBOS 同步 API 不得在事件循环内调用
（retrieve_workflow 会 RuntimeError），FastAPI 把同步路由放线程池执行。
页面：任务列表 / 提交（analyze|curate）/ 详情+状态轮询 / 审批签名 / 系统概览（只读）。
create_app(engine) 与 build_server(engine) 同构——引擎注入，测试可换。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bacmap.interfaces._auth import BearerTokenMiddleware
from bacmap.interfaces._security import SecurityHeadersMiddleware
from bacmap.interfaces.views import (
    load_summaries,
    overview_data,
    report_path,
    sample_digest,
    search_rows,
)
from bacmap.interfaces.web.static import STATIC_DIR
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.spec import Approval, TaskId, TaskType
from bacmap.tools._common import _validate_sample_id

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_MAX_ASSISTANT_SESSIONS = 32  # 会话上限（LRU 淘汰；防无界增长/内存泄漏）
_MAX_PROMPT_LEN = 8000  # 单轮需求文本上限（防超大表单/提示词）


def create_app(engine: DbosTaskEngine, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="bacmap", docs_url=None, redoc_url=None)
    if auth_token:
        # ADR-14：跨机访问需鉴权；配置 token 时全站 Bearer 校验。
        app.add_middleware(BearerTokenMiddleware, token=auth_token)
    # 安全响应头（含 CSP）：最后加入 → 位于最外层，鉴权 401 也带安全头。
    app.add_middleware(SecurityHeadersMiddleware)
    # 静态资源仅本地（CSS/图标/脚本；零外联，ADR-16）
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
    def sample_report(sample_id: str) -> FileResponse:
        if not _validate_sample_id(sample_id):
            raise HTTPException(400, "非法样本 ID")
        path = report_path(engine, sample_id)
        if not path.is_file():
            raise HTTPException(404, "该样本尚未生成 HTML 报告")
        # 以附件下载：报告为独立 HTML，避免在同源内联渲染引入 XSS 面。
        return FileResponse(
            path,
            media_type="text/html",
            filename=f"{sample_id}_report.html",
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
        task_type: str = Form(...),
        samples: str = Form(""),
        scope: str = Form(""),
    ) -> RedirectResponse:
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
        except NotImplementedError as exc:
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
        task_id: str,
        approver: str = Form(...),
        decision: str = Form(...),
        signature: str = Form(...),
    ) -> RedirectResponse:
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
        request: Request, text: str = Form(...), sid: str = Form("")
    ) -> HTMLResponse:
        from uuid import uuid4

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
    def assistant_execute(request: Request, sid: str = Form(...)) -> HTMLResponse:
        from bacmap.interfaces.assistant import execute_plan

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
