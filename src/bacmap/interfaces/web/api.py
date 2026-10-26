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
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from bacmap.application.errors import ApplicationError, Conflict, NotFound
from bacmap.application.plans import PlanService
from bacmap.interfaces.views import (
    compare_run_records,
    gom_object,
    list_gom_objects,
    list_runs,
    run_detail,
    sample_page,
)
from bacmap.interfaces.web.auth import verify_csrf
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.events import EventLog
from bacmap.tasks.spec import TaskId

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
    _plan_routes(router, PlanService(engine, engine.db))
    _event_routes(router, engine, EventLog(engine.db))
    _evidence_routes(router, engine)
    app.include_router(router)


def _meta_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "bacmap_version": pkg_version("bacmap"),
            "plannable_task_types": ["analyze", "curate"],
            "features": ["plans", "tasks", "events.poll", "events.sse", "samples.cursor"],
        }

    @router.get("/samples")
    def list_samples(cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        items, next_cursor = sample_page(engine.home, cursor, _limit(limit))
        return {"items": items, "next_cursor": next_cursor}


def _task_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/tasks")
    def list_tasks(limit: int = 50) -> dict[str, Any]:
        return {"items": engine.list_tasks(_limit(limit))}

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        try:
            return engine.status(TaskId(task_id)).model_dump(mode="json")
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc

    @router.post("/tasks/{task_id}/cancel")
    def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
        _require_csrf(request)
        try:
            engine.cancel(TaskId(task_id))
        except KeyError as exc:
            raise NotFound(f"no such task: {task_id}") from exc
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        return engine.status(TaskId(task_id)).model_dump(mode="json")


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
