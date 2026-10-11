"""bacmap Web 任务页（ADR-14）。

FastAPI + Jinja2 + 内联轮询 JS（离线无 CDN 依赖，满足 C1）。
路由一律同步 def——引擎的 DBOS 同步 API 不得在事件循环内调用
（retrieve_workflow 会 RuntimeError），FastAPI 把同步路由放线程池执行。
页面：任务列表 / 提交（analyze|curate）/ 详情+状态轮询 / 审批签名 / 系统概览（只读）。
create_app(engine) 与 build_server(engine) 同构——引擎注入，测试可换。
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bacmap.agent.llm.endpoints import load_llm_config
from bacmap.config import BACMAP_HOME, DATA_DIR, RESULTS_DIR, WORKFLOWS_DIR
from bacmap.interfaces.web.static import STATIC_DIR
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.spec import Approval, TaskType

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _overview_data(engine: DbosTaskEngine) -> dict[str, Any]:
    """系统概览只读数据——端点/路由/数据策略/版本/路径/沙箱/任务分布，零密钥。"""
    cfg = load_llm_config(BACMAP_HOME / "config.toml")
    endpoints = [
        {
            "name": e.name,
            "location": e.location,
            "base_url": e.base_url,
            "model": e.model,
            "enabled": e.enabled,
        }
        for e in cfg.endpoints.values()
    ]
    versions: dict[str, str] = {}
    for pkg in ("bacmap", "gside", "gapit", "gmlst"):
        try:
            versions[pkg] = pkg_version(pkg)
        except PackageNotFoundError:
            versions[pkg] = "未安装"
    if shutil.which("apptainer"):
        sandbox = "Apptainer"
    elif shutil.which("podman"):
        sandbox = "Podman"
    else:
        sandbox = "无可用后端（mine 任务将失败）"
    if os.environ.get("BACMAP_ALLOW_UNSANDBOXED") == "1":
        sandbox += " · 直通通道已开启"
    counts = Counter(str(t["state"]) for t in engine.list_tasks())
    return {
        "endpoints": endpoints,
        "routing": cfg.routing,
        "cloud_max_data_class": cfg.policy.cloud_max_data_class.name,
        "versions": versions,
        "paths": {
            "BACMAP_HOME": str(BACMAP_HOME),
            "data/": str(DATA_DIR),
            "results/": str(RESULTS_DIR),
            "workflows/": str(WORKFLOWS_DIR),
        },
        "sandbox": sandbox,
        "task_counts": dict(counts),
    }


def create_app(engine: DbosTaskEngine) -> FastAPI:
    app = FastAPI(title="bacmap", docs_url=None, redoc_url=None)
    # 静态资源仅本地（CSS/图标；零外联，ADR-16）
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request, "index.html", {"tasks": engine.list_tasks()}
        )

    @app.get("/overview", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(request, "overview.html", _overview_data(engine))

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
        params: dict[str, Any] = {}
        if samples.strip():
            params["samples"] = [
                s.strip() for s in samples.replace("\n", ",").split(",") if s.strip()
            ]
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
            return engine.status(task_id)
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
        try:
            engine.approve(
                task_id,
                Approval(
                    approver=approver,
                    decision=decision,  # type: ignore[arg-type]
                    signature=signature,
                    at=datetime.now(UTC),
                ),
            )
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    return app
