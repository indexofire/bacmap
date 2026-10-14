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
from typing import Any, Literal

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bacmap.agent.llm.endpoints import load_llm_config
from bacmap.interfaces._auth import BearerTokenMiddleware
from bacmap.interfaces.web.static import STATIC_DIR
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.spec import Approval, TaskId, TaskType
from bacmap.tools._common import _validate_sample_id

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _overview_data(engine: DbosTaskEngine) -> dict[str, Any]:
    """系统概览只读数据——端点/路由/数据策略/版本/路径/沙箱/任务分布，零密钥。

    路径随实例 ``engine.home`` 解析（与 ``--home`` 一致），不读模块级常量。
    """
    home = Path(engine.home)
    cfg = load_llm_config(home / "config.toml")
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
            "BACMAP_HOME": str(home),
            "data/": str(home / "data"),
            "results/": str(home / "results"),
            "workflows/": str(home / "workflows"),
        },
        "sandbox": sandbox,
        "task_counts": dict(counts),
    }


def _digest(summary: dict[str, Any]) -> dict[str, Any]:
    """summary JSON → 展示行（物种/MLST/血清型/基因计数，口径对齐 bio_get_result）。"""
    from bacmap.core.utils import parse_mlst

    steps = summary.get("steps", {}) or {}
    sp = steps.get("species", {}) or {}
    verdict = sp.get("verdict", "N/A") if isinstance(sp, dict) else str(sp)
    mlst_raw = steps.get("mlst", "") or ""
    st = parse_mlst(mlst_raw)["st"] if mlst_raw else "N/A"
    sero = steps.get("serotype", {}) or {}
    serovar = sero.get("sistr", "N/A") if isinstance(sero, dict) else "N/A"
    amr = steps.get("amr", {}) or {}
    card = amr.get("abricate_card", []) if isinstance(amr, dict) else []
    vfdb = amr.get("abricate_vfdb", []) if isinstance(amr, dict) else []
    plasmid = (steps.get("plasmid", {}) or {}).get("plasmidfinder", [])
    dec = steps.get("dec", {}) if isinstance(steps.get("dec", {}), dict) else {}
    return {
        "sample_id": summary.get("_sample_id", summary.get("sample", "")),
        "verdict": verdict,
        "st": st,
        "serovar": serovar,
        "n_card": len(card),
        "n_vfdb": len(vfdb),
        "n_plasmid": len(plasmid),
        "ipaH": dec.get("ipaH", "N/A"),
        "pathotype": dec.get("pathotype", "N/A"),
        "card_genes": sorted({str(g.get("GENE", "")) for g in card if g.get("GENE")}),
        "vfdb_genes": sorted({str(g.get("GENE", "")) for g in vfdb if g.get("GENE")}),
    }


def _load_summaries(engine: DbosTaskEngine) -> list[dict[str, Any]]:
    """已完成样本的 summary 扫描（基于 engine.home，随 --home 正确）。"""
    results = Path(engine.home) / "results"
    out: list[dict[str, Any]] = []
    for sj in sorted(results.glob("*/report/*_summary.json")):
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["_sample_id"] = sj.parent.parent.name
            out.append(data)
    return out


def _report_path(engine: DbosTaskEngine, sample_id: str) -> Path:
    return Path(engine.home) / "results" / sample_id / "report" / f"{sample_id}_report.html"


def create_app(engine: DbosTaskEngine, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="bacmap", docs_url=None, redoc_url=None)
    if auth_token:
        # ADR-14：跨机访问需鉴权；配置 token 时全站 Bearer 校验。
        app.add_middleware(BearerTokenMiddleware, token=auth_token)
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

    @app.get("/samples", response_class=HTMLResponse)
    def samples_page(request: Request) -> HTMLResponse:
        rows = [_digest(s) for s in _load_summaries(engine)]
        return _TEMPLATES.TemplateResponse(request, "samples.html", {"rows": rows})

    @app.get("/samples/{sample_id}", response_class=HTMLResponse)
    def sample_detail(request: Request, sample_id: str) -> HTMLResponse:
        if not _validate_sample_id(sample_id):
            raise HTTPException(400, "非法样本 ID")
        summary = next(
            (s for s in _load_summaries(engine) if s["_sample_id"] == sample_id), None
        )
        if summary is None:
            raise HTTPException(404, "样本不存在")
        d = _digest(summary)
        d["has_report"] = _report_path(engine, sample_id).is_file()
        return _TEMPLATES.TemplateResponse(request, "sample_detail.html", {"d": d})

    @app.get("/samples/{sample_id}/report")
    def sample_report(sample_id: str) -> FileResponse:
        if not _validate_sample_id(sample_id):
            raise HTTPException(400, "非法样本 ID")
        path = _report_path(engine, sample_id)
        if not path.is_file():
            raise HTTPException(404, "该样本尚未生成 HTML 报告")
        return FileResponse(path, media_type="text/html")

    @app.get("/search", response_class=HTMLResponse)
    def search_page(
        request: Request,
        query: str = "",
        serotype: str = "",
        mlst_st: str = "",
        amr_gene: str = "",
    ) -> HTMLResponse:
        rows = [_digest(s) for s in _load_summaries(engine)]
        terms = [q.lower() for q in query.split() if q.strip()]
        ser_l, st_u, gene_l = (
            serotype.strip().lower(), mlst_st.strip().upper(), amr_gene.strip().lower()
        )
        hits = []
        for r in rows:
            hay = " ".join(
                [r["verdict"], r["serovar"], r["st"], *r["card_genes"], *r["vfdb_genes"]]
            ).lower()
            if terms and not all(t in hay for t in terms):
                continue
            if ser_l and ser_l not in r["serovar"].lower():
                continue
            if st_u and r["st"].upper() != st_u:
                continue
            if gene_l and gene_l not in [g.lower() for g in r["card_genes"] + r["vfdb_genes"]]:
                continue
            hits.append(r)
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

    return app
