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

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from bacmap.application.errors import ApplicationError, Conflict, NotFound
from bacmap.application.plans import PlanService
from bacmap.interfaces.views import (
    compare_run_records,
    gom_object,
    list_gom_objects,
    list_runs,
    overview_data,
    run_detail,
    sample_detail,
    sample_page,
    sample_rows,
    search_rows,
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


def _require_csrf(request: Request) -> None:
    if not verify_csrf(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(403, "CSRF check failed")


def _limit(raw: int, ceiling: int = 200) -> int:
    return max(1, min(raw, ceiling))


def build_api_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    router = APIRouter(prefix="/api/v1")

    @app.exception_handler(ApplicationError)
    def _app_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=_STATUS.get(exc.code.value, 400))

    _meta_routes(router, engine)
    _task_routes(router, engine)
    _record_routes(router, engine)
    _plan_routes(router, PlanService(engine, engine.db))
    _event_routes(router, engine, EventLog(engine.db))
    _evidence_routes(router, engine)
    _research_routes(router, engine)
    app.include_router(router)


def _meta_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "bacmap_version": pkg_version("bacmap"),
            "plannable_task_types": ["analyze", "curate"],
            "features": [
                "plans",
                "tasks",
                "tasks.submit",
                "tasks.approve",
                "events.poll",
                "events.sse",
                "samples.cursor",
                "overview",
                "search",
                "records",
            ],
        }

    @router.get("/samples")
    def list_samples(cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        items, next_cursor = sample_page(engine.home, cursor, _limit(limit))
        return {"items": items, "next_cursor": next_cursor}

    @router.get("/samples/{sample_id}")
    def get_sample(sample_id: str) -> dict[str, Any]:
        data = sample_detail(engine.home, sample_id)
        if data is None:
            raise NotFound(f"no such sample: {sample_id}")
        return data

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        return overview_data(engine)

    @router.get("/search")
    def search(
        q: str = "",
        serotype: str = "",
        mlst_st: str = "",
        amr_gene: str = "",
    ) -> dict[str, Any]:
        rows = search_rows(sample_rows(engine), q, serotype, mlst_st, amr_gene)
        return {"items": rows}


def _task_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/tasks")
    def list_tasks(limit: int = 50) -> dict[str, Any]:
        return {"items": engine.list_tasks(_limit(limit))}

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


def _record_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """记录类任务（metadata/lab/knowledge）的 JSON 入口。"""

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


def _evidence_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    """运行记录与 GOM 的只读接口（v1.7.1，ADR-18/13）。"""

    @router.get("/runs")
    def runs(limit: int = 20) -> dict[str, Any]:
        return {"items": list_runs(engine.home, _limit(limit))}

    @router.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        data = run_detail(engine.home, run_id)
        if data is None:
            raise NotFound(f"no such run: {run_id}")
        return data

    @router.get("/runs/{run_id}/compare")
    def run_compare(run_id: str, other: str) -> dict[str, Any]:
        data = compare_run_records(engine.home, run_id, other)
        if data is None:
            raise NotFound("one of the runs does not exist")
        return data

    @router.get("/gom/objects")
    def gom_objects(type: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"items": list_gom_objects(engine.home, type, _limit(limit, 500))}

    @router.get("/gom/objects/{object_id}")
    def gom_one(object_id: str, version: int | None = None) -> dict[str, Any]:
        data = gom_object(engine.home, object_id, version)
        if data is None:
            raise NotFound(f"no such GOM object: {object_id}")
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
