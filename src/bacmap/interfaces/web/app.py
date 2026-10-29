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

from fastapi import FastAPI, Form, HTTPException, Request, Response
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



def _consteq(a: str, b: str) -> bool:
    """常量时间字符串比较（非 ASCII 输入编码失败按不匹配处理，而非 500）。

    ``hmac.compare_digest`` 对 str 要求 ASCII-only：登录表单提交含非 ASCII
    token 时会抛 TypeError → 未捕获 500。这里统一走 UTF-8 bytes 比较。
    """
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except UnicodeEncodeError:
        return False


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
        if not _consteq(token, cfg.token):
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
    """样本列表/详情/内联报告/搜索页。"""

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


def _submit_task_payload(
    task_type: str, samples: str, scope: str
) -> tuple[TaskType, dict[str, Any]]:
    """提交表单 → (任务类型, 引擎参数)；非法值抛 HTTPException。"""
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
            parsed_scope = json.loads(scope)
        except ValueError as exc:
            raise HTTPException(400, "scope 不是合法 JSON") from exc
        # 工作流按 dict 读取 scope（scope.get）；数组/标量会在任务线程里
        # 变成含义不明的 FAILED，接口入口直接拒绝（v1.9.2）。
        if not isinstance(parsed_scope, dict):
            raise HTTPException(400, "scope 必须是 JSON 对象")
        params["scope"] = parsed_scope
    return tt, params


def _approval_from_form(approver: str, decision: str, signature: str) -> Approval:
    """审批表单 → Approval；非法 decision 抛 HTTPException。"""
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision 必须是 approve|reject")
    typed_decision: Literal["approve", "reject"] = (
        "approve" if decision == "approve" else "reject"
    )
    return Approval(
        approver=approver,
        decision=typed_decision,
        signature=signature,
        at=datetime.now(UTC),
    )


def _build_task_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    """任务列表/概览/提交/详情/轮询 fragment/审批。"""

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "index.html", {"tasks": engine.list_tasks()}
        )

    @app.get("/overview", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(request, "overview.html", overview_data(engine))

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
        tt, params = _submit_task_payload(task_type, samples, scope)
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

    def _render_task_page(request: Request, task_id: str, template: str) -> HTMLResponse:
        """task 详情页与轮询 fragment 共用渲染（仅模板不同）。"""
        st = _status_or_404(task_id)
        return _TEMPLATES.TemplateResponse(
            request, template, {"st": st, "task_id": task_id}
        )

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_detail(request: Request, task_id: str) -> HTMLResponse:
        return _render_task_page(request, task_id, "task_detail.html")

    @app.get("/tasks/{task_id}/fragment", response_class=HTMLResponse)
    def task_fragment(request: Request, task_id: str) -> HTMLResponse:
        return _render_task_page(request, task_id, "task_fragment.html")

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
        try:
            engine.approve(TaskId(task_id), _approval_from_form(approver, decision, signature))
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        except ValueError as exc:
            # 重复审批 / 任务已终态：状态冲突（409），不能把状态机拒绝当 500。
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)


def _build_record_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    """数据记录页（v1.7）：元数据 / 化验 / 知识库——写操作只经任务层（record 任务）。"""
    from bacmap.tasks.spec import TaskType

    @app.get("/records", response_class=HTMLResponse)
    def records_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(request, "records.html", {})

    def _fields_from_text(raw: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in raw.replace(",", "\n").splitlines():
            line = line.strip()
            if not line:
                continue
            if "=" not in line:
                raise HTTPException(400, f"字段行需要 k=v 形式：{line!r}")
            key, _, value = line.partition("=")
            if not key.strip():
                raise HTTPException(400, f"字段键为空：{line!r}")
            out[key.strip()] = value.strip()
        return out

    @app.post("/records/{kind}")
    def submit_record(
        request: Request,
        kind: str,
        strain_id: str = Form(""),
        sample_id: str = Form(""),
        fields: str = Form(""),
        category: str = Form(""),
        test_name: str = Form(""),
        result: str = Form(""),
        unit: str = Form(""),
        title: str = Form(""),
        identifier: str = Form(""),
        content: str = Form(""),
        entry_id: str = Form(""),
        csrf: str = Form(""),
    ) -> RedirectResponse:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        params: dict[str, Any] = {}
        if kind == "metadata":
            params = {
                "kind": "metadata",
                "strain_id": strain_id.strip(),
                "sample_id": (sample_id.strip() or strain_id.strip()),
                "fields": _fields_from_text(fields),
            }
        elif kind == "lab":
            params = {
                "kind": "lab_result",
                "strain_id": strain_id.strip(),
                "category": category.strip(),
                "test_name": test_name.strip(),
                "result": result.strip(),
                "unit": unit.strip(),
            }
        elif kind == "knowledge-import":
            params = {
                "kind": "knowledge_import",
                "title": title.strip(),
                "identifier": identifier.strip(),
                "content": content.strip(),
            }
        elif kind == "knowledge-approve":
            try:
                params = {"kind": "knowledge_approve", "entry_id": int(entry_id)}
            except ValueError as exc:
                raise HTTPException(400, "entry_id 必须是整数") from exc
        else:
            raise HTTPException(404, "未知的记录类型")
        try:
            tid = engine.submit(TaskType.RECORD, params, "web")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/tasks/{tid}", status_code=303)


def _build_evidence_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    """运行记录与 GOM 的只读页面（v1.7.1，ADR-18/13）。"""
    import json as _json

    from bacmap.interfaces.views import (
        compare_run_records,
        gom_object,
        list_gom_objects,
        list_runs,
        run_detail,
    )

    @app.get("/runs", response_class=HTMLResponse)
    def runs_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "runs.html", {"runs": list_runs(engine.home, 50)}
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str, other: str | None = None) -> Any:
        run = run_detail(engine.home, run_id)
        if run is None:
            raise HTTPException(404, "运行记录不存在")
        compare = compare_run_records(engine.home, run_id, other) if other else None
        return _TEMPLATES.TemplateResponse(
            request,
            "run_detail.html",
            {
                "run": run,
                "compare": compare,
                "tool_versions": _json.dumps(
                    run.get("tool_versions", {}), ensure_ascii=False, indent=2
                ),
                "ref_databases": _json.dumps(
                    run.get("ref_databases", []), ensure_ascii=False, indent=2
                ),
                "resolved_config": _json.dumps(
                    run.get("resolved_config", {}), ensure_ascii=False, indent=2
                ),
            },
        )

    @app.get("/gom", response_class=HTMLResponse)
    def gom_page(request: Request, type: str | None = None) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "gom.html",
            {"objects": list_gom_objects(engine.home, type, 100), "type": type or ""},
        )

    @app.get("/gom/{object_id}", response_class=HTMLResponse)
    def gom_detail_page(request: Request, object_id: str, version: int | None = None) -> Any:
        obj = gom_object(engine.home, object_id, version)
        if obj is None:
            raise HTTPException(404, "GOM 对象不存在")
        return _TEMPLATES.TemplateResponse(
            request,
            "gom_detail.html",
            {
                "obj": obj,
                "payload": _json.dumps(obj["payload"], ensure_ascii=False, indent=2),
            },
        )


def _build_plan_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    """计划审阅与确认（v1.5.1，ADR-21 可信确认面）：外部 Harness 建计划，人在此确认。"""
    from bacmap.application.errors import ApplicationError, NotFound
    from bacmap.application.plans import PlanRecord, PlanService

    service = PlanService(engine, engine.db)

    def _render(request: Request, plan: PlanRecord, error: str = "", status: int = 200) -> Any:
        task_json = [
            json.dumps(t.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
            for t in plan.tasks
        ]
        return _TEMPLATES.TemplateResponse(
            request,
            "plan_detail.html",
            {"plan": plan, "task_json": task_json, "error": error},
            status_code=status,
        )

    def _get_or_404(plan_id: str, version: int | None = None) -> PlanRecord:
        try:
            return service.get(plan_id, version)
        except NotFound as exc:
            raise HTTPException(404, "计划不存在") from exc

    @app.get("/plans", response_class=HTMLResponse)
    def plans(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "plans.html", {"plans": service.list_plans(50)}
        )

    @app.get("/plans/{plan_id}", response_class=HTMLResponse)
    def plan_detail(request: Request, plan_id: str, version: int | None = None) -> Any:
        return _render(request, _get_or_404(plan_id, version))

    @app.post("/plans/{plan_id}/confirm")
    def confirm_plan(
        request: Request,
        plan_id: str,
        version: int = Form(...),
        plan_hash: str = Form(...),
        confirmer: str = Form(...),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        who = confirmer.strip()[:64]
        if not who:
            raise HTTPException(400, "需要确认人")
        try:
            service.confirm(plan_id, version, plan_hash, f"web:{who}")
        except NotFound as exc:
            raise HTTPException(404, "计划不存在") from exc
        except ApplicationError as exc:
            return _render(request, _get_or_404(plan_id, version), exc.message, 409)
        return RedirectResponse(f"/plans/{plan_id}?version={version}", status_code=303)

    @app.post("/plans/{plan_id}/reject")
    def reject_plan(
        request: Request,
        plan_id: str,
        version: int = Form(...),
        reason: str = Form(...),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            service.reject(plan_id, version, reason.strip()[:500], "web")
        except NotFound as exc:
            raise HTTPException(404, "计划不存在") from exc
        except ApplicationError as exc:
            return _render(request, _get_or_404(plan_id, version), exc.message, 409)
        return RedirectResponse(f"/plans/{plan_id}?version={version}", status_code=303)


def create_app(engine: DbosTaskEngine, auth_token: str | None = None) -> FastAPI:
    """组装 Web 应用：中间件/静态 + 六组页面路由 + /api/v1。

    页面组：auth / sample / task / plan / record / evidence（运行记录与 GOM）。
    """
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

    _build_auth_routes(app, cfg)
    _build_sample_routes(app, engine)
    _build_task_routes(app, engine)
    _build_plan_routes(app, engine)
    _build_record_routes(app, engine)
    _build_evidence_routes(app, engine)

    from bacmap.interfaces.web.api import build_api_routes

    build_api_routes(app, engine)
    return app
