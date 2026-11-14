"""版本化 JSON API ``/api/v1``（v1.5.2，ADR-14 补充）。

与 HTML 页面共用同一套鉴权中间件（bearer / cookie）；cookie 模式下的状态变更请求须带
``X-CSRF-Token``（与 ``bacmap_csrf`` cookie 一致）且同源。错误统一为
``{"code": "validation_error|not_found|conflict", "error": "..."}``。

该 API 是可信界面（持有 Web 令牌即操作员），不得把令牌交给外部 Harness——Harness 只走
MCP（ADR-21）。事件流 SSE 支持 ``Last-Event-ID`` 续传；事件不是真相，断线后以查询恢复。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from bacmap.application.errors import ApplicationError, Conflict, NotFound
from bacmap.application.plans import PlanService
from bacmap.interfaces.gvixb import (
    GvixbLink,
    gom_visualizations,
    latest_annotation_link,
    latest_genome_link,
    run_visualizations,
)
from bacmap.interfaces.stats_summary import gather_stats
from bacmap.interfaces.views import (
    compare_run_records,
    count_gom_objects,
    count_isolates,
    count_runs,
    count_samples,
    count_specimens,
    gom_object,
    isolate_detail,
    isolate_rows,
    list_gom_objects,
    list_runs,
    overview_data,
    run_detail,
    sample_detail,
    sample_page,
    sample_rows,
    search_page,
    specimen_detail,
    specimen_rows,
)
from bacmap.interfaces.web.auth import verify_csrf
from bacmap.interfaces.web.payloads import (
    approval_payload,
    fields_from_text,
    submit_task_payload,
)
from bacmap.research.discovery import ExploreRequest
from bacmap.research.models import (
    ClaimCreate,
    ClaimReview,
    CohortCreate,
    CreateSessionRequest,
    ExperimentCreate,
    PlanCreate,
    ResearchError,
    ResearchProfile,
    StudyCreate,
)
from bacmap.research.outbreak import OutbreakAnalyzeRequest
from bacmap.research.service import (
    ResearchObjectService,
    ResearchService,
    default_profile,
)
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.events import EventLog
from bacmap.tasks.spec import TaskId, TaskType

API_VERSION = "1"
_STATUS = {"validation_error": 400, "not_found": 404, "conflict": 409}
_SSE_POLL_S = 1.0
_SSE_MAX_S = 300


class ConfirmBody(BaseModel):
    version: int
    plan_hash: str = Field(min_length=12, max_length=64)
    confirmer: str = Field(min_length=1, max_length=64)


class RejectBody(BaseModel):
    version: int
    reason: str = Field(min_length=1, max_length=500)


class TaskSubmitBody(BaseModel):
    task_type: str
    samples: list[str] | str = ""
    scope: dict[str, Any] | str | None = None


class ApprovalBody(BaseModel):
    approver: str = Field(min_length=1, max_length=64)
    decision: Literal["approve", "reject"]
    signature: str = Field(min_length=1, max_length=256)
    comment: str | None = None


class RecordBody(BaseModel):
    strain_id: str = ""
    sample_id: str = ""
    fields: dict[str, str] | str = ""
    category: str = ""
    test_name: str = ""
    result: str = ""
    unit: str = ""
    title: str = ""
    identifier: str = ""
    content: str = ""
    entry_id: str = ""


class SpecimenDeleteBody(BaseModel):
    force: bool = False


class SpecimenAssignBody(BaseModel):
    specimen_id: str = Field(min_length=1, max_length=128)
    isolates: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)


class LoginBody(BaseModel):
    token: str = ""
    next: str = "/console/"


def _require_csrf(request: Request) -> None:
    if not verify_csrf(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(403, "CSRF check failed")


def _limit(raw: int, ceiling: int = 200) -> int:
    return max(1, min(raw, ceiling))


def _gvixb_sample_links(engine: DbosTaskEngine, sample_id: str) -> list[GvixbLink]:
    """样本"最新结果"的 gvixb 入口（latest scope，与 run scope 严格分离）。

    无对应产物时返回空列表；latest scope 拒绝越界时同样视为无入口
    （路径越界是安全拒绝，不是 500）。
    """
    links: list[GvixbLink] = []
    for factory in (latest_genome_link, latest_annotation_link):
        try:
            link = factory(engine, sample_id)
        except PermissionError:
            continue
        if link is not None:
            links.append(link)
    return links


def build_api_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    router = APIRouter(prefix="/api/v1")

    @app.exception_handler(ApplicationError)
    def _app_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=_STATUS.get(exc.code.value, 400))

    _meta_routes(router, engine)
    _auth_routes(router)
    _task_routes(router, engine)
    _record_routes(router, engine)
    _plan_routes(router, PlanService(engine, engine.db))
    _event_routes(router, engine, EventLog(engine.db))
    _evidence_routes(router, engine)
    _identity_routes(router, engine)
    _research_routes(router, engine)
    app.include_router(router)


def _auth_routes(router: APIRouter) -> None:
    """控制台登录体验（v1.10.28）：单令牌登录/状态/登出，不引入账号体系。

    登录仍沿用 ADR-14 的签名会话 cookie + CSRF；``/auth/status`` 与
    ``/auth/login`` 在鉴权中间件中免鉴权（登录页自身需要它们）。
    """

    @router.get("/auth/status")
    def auth_status(request: Request) -> dict[str, Any]:
        from bacmap.interfaces.web.auth import LOGIN_PATH
        from bacmap.interfaces.web.auth import operator_label as _operator_label
        from bacmap.interfaces.web.auth import (
            request_authenticated as _request_authenticated,
        )

        cfg = request.app.state.web_auth
        if not cfg.enabled:
            return {
                "enabled": False,
                "mode": "disabled",
                "authenticated": True,
                "operator": "",
                "login_url": "",
            }
        authenticated = _request_authenticated(request, cfg)
        return {
            "enabled": True,
            "mode": cfg.mode,
            "authenticated": authenticated,
            "operator": _operator_label(cfg) if authenticated else "",
            "login_url": LOGIN_PATH if cfg.mode == "cookie" else "",
        }

    @router.post("/auth/login")
    def auth_login(request: Request, body: LoginBody) -> Response:
        import secrets
        from urllib.parse import urlparse

        from bacmap.interfaces._security import consteq
        from bacmap.interfaces.web.auth import (
            CSRF_COOKIE,
            SESSION_COOKIE,
            issue_session,
            safe_next,
        )

        cfg = request.app.state.web_auth
        if not (cfg.enabled and cfg.mode == "cookie"):
            raise HTTPException(409, "browser login is not enabled")
        host = request.headers.get("host", "")
        origin = request.headers.get("origin", "")
        if origin and urlparse(origin).netloc != host:
            raise HTTPException(403, "cross-origin login rejected")
        if not consteq(body.token, cfg.token):
            raise HTTPException(401, "invalid token")
        target = safe_next(body.next, default="/console/")
        response = JSONResponse({"ok": True, "next": target})
        response.set_cookie(
            SESSION_COOKIE,
            issue_session(cfg.secret, cfg.ttl_s),
            **cfg.session_cookie_kwargs(),
        )
        response.set_cookie(
            CSRF_COOKIE, secrets.token_urlsafe(24), **cfg.csrf_cookie_kwargs()
        )
        return response

    @router.post("/auth/logout")
    def auth_logout(request: Request) -> Response:
        from bacmap.interfaces.web.auth import CSRF_COOKIE, SESSION_COOKIE

        _require_csrf(request)
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return response


def _meta_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/capabilities")
    def capabilities(request: Request) -> dict[str, Any]:
        # v1.10.24：智能体对话嵌入清单（[[web.agent_embed]] 配置驱动）。
        from bacmap.interfaces.web.agent_embed import embeds_payload

        embeds = getattr(request.app.state, "agent_embeds", [])
        return {
            "api_version": API_VERSION,
            "bacmap_version": pkg_version("bacmap"),
            "agent_embeds": embeds_payload(embeds),
            # 与 application/plans.py 的 PlannableTask 全集一致（MCP
            # bacmap_capabilities 同源）——此前写死两类会让外部编排方低估能力面。
            "plannable_task_types": [
                "analyze", "curate", "mine", "write", "research",
            ],
            "features": [
                "plans",
                "tasks",
                "tasks.submit",
                "tasks.approve",
                "events.poll",
                "events.sse",
                "samples.cursor",
                "overview",
                "stats",
                "search",
                "records",
            ],
        }

    @router.get("/samples")
    def list_samples(
        cursor: str | None = None, limit: int = 50, offset: int | None = None
    ) -> dict[str, Any]:
        total = count_samples(engine.home)
        if offset is not None:
            rows = sample_rows(engine)
            start = max(0, offset)
            return {
                "items": rows[start : start + _limit(limit, 500)],
                "next_cursor": None,
                "total": total,
                "offset": start,
                "limit": _limit(limit, 500),
            }
        items, next_cursor = sample_page(engine.home, cursor, _limit(limit))
        return {
            "items": items,
            "next_cursor": next_cursor,
            "total": total,
            "limit": _limit(limit),
        }

    @router.get("/samples/{sample_id}")
    def get_sample(sample_id: str) -> dict[str, Any]:
        data = sample_detail(engine.home, sample_id)
        if data is None:
            raise NotFound(f"no such sample: {sample_id}")
        data["gvixb"] = _gvixb_sample_links(engine, sample_id)
        return data

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        return overview_data(engine)

    @router.get("/stats")
    def stats() -> dict[str, Any]:
        return gather_stats(engine.home)

    @router.get("/search")
    def search(
        q: str = "",
        serotype: str = "",
        mlst_st: str = "",
        amr_gene: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        items, total = search_page(
            sample_rows(engine),
            query=q,
            serotype=serotype,
            mlst_st=mlst_st,
            amr_gene=amr_gene,
            offset=offset,
            limit=_limit(limit, 500),
        )
        return {
            "items": items,
            "total": total,
            "offset": max(0, offset),
            "limit": _limit(limit, 500),
        }


def _task_routes(router: APIRouter, engine: DbosTaskEngine) -> None:  # noqa: C901 — 路由族内聚；拆分收益低于可读性损失
    @router.get("/tasks")
    def list_tasks(
        limit: int = 50, offset: int = 0, task_type: str = ""
    ) -> dict[str, Any]:
        return {
            "items": engine.list_tasks(
                _limit(limit, 500), offset=offset, task_type=task_type
            ),
            "total": engine.count_tasks(task_type=task_type),
            "offset": max(0, offset),
            "limit": _limit(limit, 500),
        }

    @router.post("/tasks")
    def create_task(request: Request, body: TaskSubmitBody) -> dict[str, Any]:
        _require_csrf(request)
        tt, params = submit_task_payload(body.task_type, body.samples, body.scope)
        try:
            tid = engine.submit(tt, params, "web")
        except (ValueError, NotImplementedError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return engine.get_task(tid)

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        try:
            return engine.get_task(TaskId(task_id))
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc

    @router.post("/tasks/{task_id}/approve")
    def approve_task(request: Request, task_id: str, body: ApprovalBody) -> dict[str, Any]:
        _require_csrf(request)
        try:
            engine.approve(
                TaskId(task_id),
                approval_payload(body.approver, body.decision, body.signature, body.comment),
            )
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        return engine.get_task(TaskId(task_id))

    @router.post("/tasks/{task_id}/cancel")
    def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
        _require_csrf(request)
        try:
            engine.cancel(TaskId(task_id))
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        return engine.get_task(TaskId(task_id))

    @router.post("/tasks/{task_id}/pause")
    def pause_task(request: Request, task_id: str) -> dict[str, Any]:
        """v1.10.22：用户暂停（工作流在下一边界收场，snakemake 跑完当前规则）。"""
        _require_csrf(request)
        try:
            engine.pause(TaskId(task_id))
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        return engine.get_task(TaskId(task_id))

    @router.post("/tasks/{task_id}/resume")
    def resume_task(request: Request, task_id: str) -> dict[str, Any]:
        """v1.10.22：恢复 paused/failed(interrupted) 任务（同 run 目录续跑）。"""
        _require_csrf(request)
        try:
            engine.resume(TaskId(task_id))
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        return engine.get_task(TaskId(task_id))


def _record_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """记录类任务（metadata/lab/knowledge）的 JSON 入口。"""

    @router.get("/records")
    def list_records(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """记录任务列表（数据记录页分页；任务层只读视图）。"""
        return {
            "items": engine.list_tasks(
                _limit(limit, 500), offset=offset, task_type="record"
            ),
            "total": engine.count_tasks(task_type="record"),
            "offset": max(0, offset),
            "limit": _limit(limit, 500),
        }

    @router.post("/records/{kind}")
    def create_record(request: Request, kind: str, body: RecordBody) -> dict[str, Any]:
        _require_csrf(request)
        params: dict[str, Any]
        if kind == "metadata":
            params = {
                "kind": "metadata",
                "strain_id": body.strain_id.strip(),
                "sample_id": (body.sample_id.strip() or body.strain_id.strip()),
                "fields": fields_from_text(body.fields),
            }
        elif kind == "lab":
            params = {
                "kind": "lab_result",
                "strain_id": body.strain_id.strip(),
                "category": body.category.strip(),
                "test_name": body.test_name.strip(),
                "result": body.result.strip(),
                "unit": body.unit.strip(),
            }
        elif kind == "knowledge-import":
            params = {
                "kind": "knowledge_import",
                "title": body.title.strip(),
                "identifier": body.identifier.strip(),
                "content": body.content.strip(),
            }
        elif kind == "knowledge-approve":
            try:
                params = {"kind": "knowledge_approve", "entry_id": int(body.entry_id)}
            except ValueError as exc:
                raise HTTPException(400, "entry_id 必须是整数") from exc
        else:
            raise HTTPException(404, "未知的记录类型")
        try:
            tid = engine.submit(TaskType.RECORD, params, "web")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return engine.get_task(tid)


def _plan_routes(router: APIRouter, plans: PlanService) -> None:
    @router.get("/plans")
    def list_plans(limit: int = 20) -> dict[str, Any]:
        return {"items": [p.model_dump(mode="json") for p in plans.list_plans(_limit(limit))]}

    @router.get("/plans/{plan_id}")
    def get_plan(plan_id: str, version: int | None = None) -> dict[str, Any]:
        return plans.get(plan_id, version).model_dump(mode="json")

    @router.post("/plans/{plan_id}/confirm")
    def confirm_plan(request: Request, plan_id: str, body: ConfirmBody) -> dict[str, Any]:
        _require_csrf(request)
        actor = f"api:{body.confirmer.strip()}"
        return plans.confirm(plan_id, body.version, body.plan_hash, actor).model_dump(mode="json")

    @router.post("/plans/{plan_id}/reject")
    def reject_plan(request: Request, plan_id: str, body: RejectBody) -> dict[str, Any]:
        _require_csrf(request)
        return plans.reject(plan_id, body.version, body.reason, "api").model_dump(mode="json")


def _event_routes(router: APIRouter, engine: DbosTaskEngine, events: EventLog) -> None:
    @router.get("/events")
    def list_events(
        after: int = 0,
        limit: int = 100,
        task_id: str | None = None,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        items = events.list(after=after, limit=limit, task_id=task_id, plan_id=plan_id)
        return {
            "events": [e.model_dump(mode="json") for e in items],
            "last_seq": items[-1].seq if items else after,
            # v1.10.30：SSE 起点必须是最新 seq，否则会重放全部历史事件。
            "max_seq": events.last_seq(),
        }

    @router.get("/events/stream")
    def stream_events(request: Request, after: int = 0, timeout: int = _SSE_MAX_S) -> Any:
        header = request.headers.get("last-event-id", "")
        cursor = int(header) if header.isdigit() else after
        deadline = time.monotonic() + max(0, min(timeout, _SSE_MAX_S))

        def gen() -> Iterator[str]:
            nonlocal cursor
            while True:
                # 列表读取会惰性对账 running 任务的终态 → 终态事件得以产生
                engine.count_states()
                for e in events.list(after=cursor, limit=200):
                    cursor = e.seq
                    data = json.dumps(e.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {e.seq}\nevent: {e.type.value}\ndata: {data}\n\n"
                if time.monotonic() >= deadline:
                    return
                yield ": keepalive\n\n"
                time.sleep(_SSE_POLL_S)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def _identity_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """样本/菌株身份模型只读接口（v1.10.27，P2）。

    现有 ``/samples`` 仍是"测序数据（library）"的分析结果视图（历史路径）；
    本组新接口提供 specimen → isolate → library 的上层实体浏览。
    """

    @router.get("/specimens")
    def specimens(limit: int = 200, offset: int = 0) -> dict[str, Any]:
        return {
            "items": specimen_rows(engine.home, _limit(limit, 500), offset),
            "total": count_specimens(engine.home),
            "offset": max(0, offset),
            "limit": _limit(limit, 500),
        }

    @router.get("/specimens/{specimen_id}")
    def specimen(specimen_id: str) -> dict[str, Any]:
        data = specimen_detail(engine.home, specimen_id)
        if data is None:
            raise NotFound(f"no such specimen: {specimen_id}")
        return data

    @router.get("/isolates")
    def isolates(limit: int = 500, offset: int = 0) -> dict[str, Any]:
        return {
            "items": isolate_rows(engine.home, _limit(limit, 2000), offset),
            "total": count_isolates(engine.home),
            "offset": max(0, offset),
            "limit": _limit(limit, 2000),
        }

    @router.get("/isolates/{isolate_id}")
    def isolate(isolate_id: str) -> dict[str, Any]:
        data = isolate_detail(engine.home, isolate_id)
        if data is None:
            raise NotFound(f"no such isolate: {isolate_id}")
        return data

    @router.post("/specimens/{specimen_id}/delete")
    def delete_specimen_route(
        request: Request,
        specimen_id: str,
        body: SpecimenDeleteBody | None = None,
    ) -> dict[str, Any]:
        """删除样本（可信界面写操作，需 CSRF）。

        默认只允许空样本；``force=true`` 先解除菌株关联（不删菌株/数据）再删除。
        权限点（specimen.delete）预留给后续多用户 RBAC。
        """
        _require_csrf(request)
        from bacmap.workflow.samples_registry import delete_specimen

        try:
            result = delete_specimen(
                engine.home, specimen_id, force=bool(body and body.force)
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not result["deleted"]:
            raise NotFound(f"no such specimen: {specimen_id}")
        return result

    @router.post("/specimens/assign")
    def assign_specimen(request: Request, body: SpecimenAssignBody) -> dict[str, Any]:
        """把菌株/测序数据关联到样本（可信界面写操作，需 CSRF）。"""
        _require_csrf(request)
        from bacmap.workflow.samples_registry import assign_specimens

        results: list[dict[str, Any]] = []
        if body.datasets:
            results.append(
                assign_specimens(
                    engine.home,
                    {dataset: body.specimen_id for dataset in body.datasets},
                    by="dataset",
                )
            )
        if body.isolates:
            results.append(
                assign_specimens(
                    engine.home,
                    {isolate: body.specimen_id for isolate in body.isolates},
                    by="isolate",
                )
            )
        if not results:
            raise HTTPException(400, "give at least one isolate or dataset")
        return {
            "specimen_id": body.specimen_id,
            "updated": sum(int(r["updated"]) for r in results),
            "missing": sorted({m for r in results for m in r["missing"]}),
        }

    @router.get("/search/identity")
    def identity_search_route(
        q: str = "",
        specimen_offset: int = 0,
        specimen_limit: int = 50,
        isolate_offset: int = 0,
        isolate_limit: int = 50,
    ) -> dict[str, Any]:
        """统一检索：样本与菌株分页（测序数据仍用 /search 的结构化过滤）。"""
        from bacmap.interfaces.views import identity_page

        return identity_page(
            engine.home,
            q,
            specimen_offset=specimen_offset,
            specimen_limit=_limit(specimen_limit, 500),
            isolate_offset=isolate_offset,
            isolate_limit=_limit(isolate_limit, 500),
        )


def _evidence_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """运行记录与 GOM 的只读接口（v1.7.1，ADR-18/13）。"""

    @router.get("/runs")
    def runs(limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return {
            "items": list_runs(engine.home, _limit(limit), offset),
            "total": count_runs(engine.home),
            "offset": max(0, offset),
            "limit": _limit(limit),
        }

    @router.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        data = run_detail(engine.home, run_id)
        if data is None:
            raise NotFound(f"no such run: {run_id}")
        # gvixb 入口只列真实存在的产物；任务未成功/结果目录缺失时为空列表。
        data["gvixb_views"] = run_visualizations(engine, run_id)
        return data

    @router.get("/runs/{run_id}/compare")
    def run_compare(run_id: str, other: str) -> dict[str, Any]:
        data = compare_run_records(engine.home, run_id, other)
        if data is None:
            raise NotFound("one of the runs does not exist")
        return data

    @router.get("/gom/objects")
    def gom_objects(
        type: str | None = None, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        return {
            "items": list_gom_objects(
                engine.home, type, _limit(limit, 500), offset
            ),
            "total": count_gom_objects(engine.home, type),
            "offset": max(0, offset),
            "limit": _limit(limit, 500),
        }

    @router.get("/gom/objects/{object_id}")
    def gom_one(object_id: str, version: int | None = None) -> dict[str, Any]:
        data = gom_object(engine.home, object_id, version)
        if data is None:
            raise NotFound(f"no such GOM object: {object_id}")
        # 仅当对象载荷指向本次运行且产物存在时非空（sample_analysis / cohort 类）。
        data["gvixb_views"] = gom_visualizations(engine, data)
        return data


def _research_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """P1 Research Workbench API（trusted operator surface）。"""
    _research_session_routes(router, engine)
    _research_artifact_routes(router, engine)
    _research_object_routes(router, engine)


def _research_status(code: str) -> int:
    return {"validation_error": 400, "not_found": 404, "conflict": 409}.get(code, 400)


def _research_session_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    def _err(exc: ResearchError) -> JSONResponse:
        return JSONResponse(
            {"code": exc.code, "error": exc.message},
            status_code=_research_status(exc.code),
        )

    @router.get("/research/capabilities")
    def research_capabilities(profile: str | None = None) -> dict[str, Any]:
        try:
            p = ResearchProfile(profile) if profile else default_profile()
        except ValueError as exc:
            raise HTTPException(400, f"unknown research profile: {profile}") from exc
        return ResearchService(engine.home).capabilities(p).model_dump(mode="json")

    @router.get("/research/sessions")
    def research_sessions(limit: int = 50) -> dict[str, Any]:
        items = ResearchService(engine.home).list_sessions(_limit(limit))
        return {"items": [s.model_dump(mode="json") for s in items]}

    @router.post("/research/sessions")
    def research_create(request: Request, body: CreateSessionRequest) -> Any:
        _require_csrf(request)
        try:
            view = ResearchService(engine.home).create_session(body, actor="api")
        except ResearchError as exc:
            return _err(exc)
        return view.model_dump(mode="json")

    @router.get("/research/sessions/{session_id}")
    def research_get(session_id: str) -> dict[str, Any]:
        try:
            return ResearchService(engine.home).get_session(session_id).model_dump(mode="json")
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc

    @router.get("/research/sessions/{session_id}/ledger")
    def research_ledger(session_id: str) -> dict[str, Any]:
        svc = ResearchService(engine.home)
        try:
            svc.get_session(session_id)
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc
        return {"items": svc.ledger(session_id)}


def _research_artifact_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    def _artifact_response(session_id: str, kind: str) -> Path:
        try:
            return ResearchService(engine.home).read_artifact(session_id, kind)
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc

    @router.get("/research/sessions/{session_id}/figure.svg")
    def research_figure(session_id: str) -> FileResponse:
        return FileResponse(_artifact_response(session_id, "figure"), media_type="image/svg+xml")

    @router.get("/research/sessions/{session_id}/report.md")
    def research_report(session_id: str) -> PlainTextResponse:
        path = _artifact_response(session_id, "report")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")

    @router.get("/research/sessions/{session_id}/manuscript.md")
    def research_manuscript(session_id: str) -> PlainTextResponse:
        path = _artifact_response(session_id, "manuscript")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


def _research_bad(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


def _research_object_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """P2 research objects: Study/Cohort/Plan/Claim (trusted operator surface)."""

    def _svc() -> ResearchObjectService:
        return ResearchObjectService(engine.home)

    @router.get("/research/studies")
    def list_studies(limit: int = 50) -> dict[str, Any]:
        return {"items": [s.model_dump(mode="json") for s in _svc().list_studies(_limit(limit))]}

    @router.post("/research/studies")
    def create_study(request: Request, body: StudyCreate) -> dict[str, Any]:
        _require_csrf(request)
        s = _svc().create_study(body.question, body.pathogen_scope, body.data_class, "api")
        return s.model_dump(mode="json")

    @router.get("/research/studies/{study_id}")
    def get_study(study_id: str) -> dict[str, Any]:
        try:
            return _svc().get_study(study_id).model_dump(mode="json")
        except Exception as exc:
            raise _research_bad(exc) from exc

    @router.get("/research/studies/{study_id}/publication-readiness")
    def publication_readiness(study_id: str) -> dict[str, Any]:
        try:
            return _svc().publication_readiness(study_id)
        except Exception as exc:
            raise _research_bad(exc) from exc

    @router.post("/research/outbreak/analyze")
    def analyze_outbreak(request: Request, body: OutbreakAnalyzeRequest) -> dict[str, Any]:
        _require_csrf(request)
        from bacmap.research.outbreak import summarize_outbreak

        return summarize_outbreak(body.events, body.min_count)

    @router.post("/research/explore")
    def explore(request: Request, body: ExploreRequest) -> dict[str, Any]:
        _require_csrf(request)
        from bacmap.research.discovery import explore_candidates

        try:
            return explore_candidates(body.study_id, body.cases, body.budget, body.role)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    _research_cohort_routes(router, _svc)
    _research_plan_routes(router, _svc)
    _research_claim_routes(router, _svc)
    _research_ledger_route(router, _svc)
    _research_benchmark_routes(router, engine)


def _research_cohort_routes(router: APIRouter, svc: Any) -> None:
    @router.get("/research/cohorts")
    def list_cohorts(study_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(svc().home) as store:
            items = store.list_cohorts(study_id, _limit(limit))
        return {"items": [c.model_dump(mode="json") for c in items]}

    @router.get("/research/cohorts/{cohort_id}")
    def get_cohort(cohort_id: str) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        try:
            with ResearchObjectStore(svc().home) as store:
                return store.get_cohort(cohort_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/research/cohorts/preview")
    def preview_cohort(request: Request, body: CohortCreate) -> dict[str, Any]:
        _require_csrf(request)
        try:
            return svc().preview_cohort(
                body.study_id, [m.model_dump(mode="json") for m in body.members], body.rules
            )
        except Exception as exc:
            raise _research_bad(exc) from exc

    @router.post("/research/cohorts")
    def create_cohort(request: Request, body: CohortCreate) -> dict[str, Any]:
        _require_csrf(request)
        try:
            c = svc().create_cohort(
                body.study_id, [m.model_dump(mode="json") for m in body.members],
                body.rules, body.name, "api",
            )
        except Exception as exc:
            raise _research_bad(exc) from exc
        return c.model_dump(mode="json")

    @router.post("/research/cohorts/{cohort_id}/freeze")
    def freeze_cohort(request: Request, cohort_id: str) -> dict[str, Any]:
        _require_csrf(request)
        try:
            return svc().freeze_cohort(cohort_id, "api").model_dump(mode="json")
        except Exception as exc:
            raise _research_bad(exc) from exc


def _research_plan_routes(router: APIRouter, svc: Any) -> None:
    @router.get("/research/plans")
    def list_plans(study_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(svc().home) as store:
            items = store.list_plans(study_id, _limit(limit))
        return {"items": [p.model_dump(mode="json") for p in items]}

    @router.get("/research/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        try:
            with ResearchObjectStore(svc().home) as store:
                return store.get_plan(plan_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/research/plans")
    def create_plan(request: Request, body: PlanCreate) -> dict[str, Any]:
        _require_csrf(request)
        try:
            p = svc().create_plan(body.study_id, body.cohort_id, body.spec, "api")
        except Exception as exc:
            raise _research_bad(exc) from exc
        return p.model_dump(mode="json")

    @router.post("/research/plans/{plan_id}/freeze")
    def freeze_plan(request: Request, plan_id: str) -> dict[str, Any]:
        _require_csrf(request)
        try:
            return svc().freeze_plan(plan_id, "api").model_dump(mode="json")
        except Exception as exc:
            raise _research_bad(exc) from exc

    @router.post("/research/plans/{plan_id}/run")
    def run_plan(request: Request, plan_id: str) -> dict[str, Any]:
        _require_csrf(request)
        try:
            view = svc().run_plan(plan_id, "api")
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc
        return view.model_dump(mode="json")

    @router.get("/research/experiments")
    def list_experiments(
        study_id: str | None = None, plan_id: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        items = svc().list_experiments(study_id, plan_id, _limit(limit))
        return {"items": [e.model_dump(mode="json") for e in items]}

    @router.post("/research/experiments")
    def create_experiment(request: Request, body: ExperimentCreate) -> dict[str, Any]:
        _require_csrf(request)
        try:
            exp = svc().record_experiment(
                body.plan_id,
                body.status.value,
                body.run_ids,
                body.outcome,
                body.deviation,
                "api",
            )
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc
        return exp.model_dump(mode="json")


def _research_claim_routes(router: APIRouter, svc: Any) -> None:
    @router.get("/research/claims")
    def list_claims(study_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(svc().home) as store:
            items = store.list_claims(study_id, _limit(limit))
        return {"items": [c.model_dump(mode="json") for c in items]}

    @router.get("/research/claims/{claim_id}")
    def get_claim(claim_id: str) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        try:
            with ResearchObjectStore(svc().home) as store:
                return store.get_claim(claim_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/research/claims")
    def create_claim(request: Request, body: ClaimCreate) -> dict[str, Any]:
        _require_csrf(request)
        try:
            c = svc().create_claim(
                body.study_id, body.claim_type.value, body.wording,
                body.evidence_level.value, body.evidence, "api",
            )
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc
        except Exception as exc:
            raise _research_bad(exc) from exc
        return c.model_dump(mode="json")

    @router.post("/research/claims/from-session")
    def claim_from_session(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        _require_csrf(request)
        try:
            c = svc().claim_from_session(
                str(body.get("session_id", "")),
                str(body.get("wording", "")),
                str(body.get("evidence_level", "E2")),
                "api",
            )
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc
        except Exception as exc:
            raise _research_bad(exc) from exc
        return c.model_dump(mode="json")

    @router.post("/research/claims/{claim_id}/review")
    def review_claim(request: Request, claim_id: str, body: ClaimReview) -> dict[str, Any]:
        _require_csrf(request)
        try:
            c = svc().review_claim(claim_id, body.decision, body.message, "api")
        except ResearchError as exc:
            raise HTTPException(_research_status(exc.code), exc.message) from exc
        return c.model_dump(mode="json")


def _research_ledger_route(router: APIRouter, svc: Any) -> None:
    @router.get("/research/ledger")
    def research_object_ledger(
        object_type: str | None = None, object_id: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(svc().home) as store:
            return {"items": store.list_ledger(object_type, object_id, _limit(limit, 500))}


def _research_benchmark_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/research/benchmarks/amr")
    def amr_benchmark() -> dict[str, Any]:
        from bacmap.research.benchmarks import run_amr_benchmark

        return run_amr_benchmark()

    def _benchmark_root(dataset: str) -> Path:
        import os

        env = os.environ.get("BACMAP_BENCHMARK_DATA")
        if env:
            candidate = Path(env)
            nested = candidate / dataset
            if nested.is_dir():
                return nested
            if candidate.is_dir():
                return candidate
        return engine.home / "benchmarks" / dataset

    @router.get("/research/benchmarks/bvbrc-amr")
    def bvbrc_amr_benchmark() -> dict[str, Any]:
        from bacmap.research.benchmarks import run_bvbrc_amr_benchmark

        return run_bvbrc_amr_benchmark(_benchmark_root("bvbrc_kpn_meropenem"))

    @router.get("/research/benchmarks/osf-cohort")
    def osf_cohort_benchmark() -> dict[str, Any]:
        from bacmap.research.benchmarks import summarize_osf_cohort

        return summarize_osf_cohort(_benchmark_root("osf_n78q3"))

    @router.get("/research/benchmarks/verify")
    def verify_benchmark(dataset: str = "bvbrc_kpn_meropenem") -> dict[str, Any]:
        from bacmap.research.benchmarks import verify_benchmark_dir

        if dataset not in {"bvbrc_kpn_meropenem", "osf_n78q3"}:
            raise HTTPException(404, f"unknown benchmark dataset: {dataset}")
        return verify_benchmark_dir(_benchmark_root(dataset))
