"""gvixb Web 页面与同源只读数据路由。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from bacmap.interfaces import gvixb as service
from bacmap.interfaces.web.static import STATIC_DIR


def _call(factory: Callable[[], Any]) -> Any:
    try:
        return factory()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _run_link(engine: Any, run_id: str, url: str) -> service.GvixbLink:
    link = next((view for view in run_visualizations(engine, run_id) if view.url == url), None)
    if link is None:
        raise HTTPException(404, "该运行没有此 gvixb 可视化结果")
    return link


def run_visualizations(engine: Any, run_id: str) -> list[service.GvixbLink]:
    return _call(lambda: service.run_visualizations(engine, run_id))


def _asset_version() -> str:
    """静态 gvixb 资源的版本串：升级后 URL 变化，绕过旧 CSS/JS 缓存。"""
    base = STATIC_DIR / "gvixb"
    parts: list[str] = []
    for rel in (
        "gvixb.css", "gvixb-shell.css", "gvixb-app.js",
        "views/circular-annotation-view.js", "framework/analysis-framework.js",
    ):
        path = base / rel
        if path.is_file():
            stat = path.stat()
            parts.append(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def _switcher_views(
    engine: Any, run_id: str, current: service.GvixbLink
) -> list[service.GvixbLink]:
    """同一运行内可切换的视图：当前菌株的 genome/circle + 全部 tree/mst。"""
    try:
        views = run_visualizations(engine, run_id)
    except Exception:  # 只影响切换器，不影响当前视图
        return [current]
    sample = current.context
    keep = [
        view for view in views
        if view.kind in ("tree", "mst")
        or (view.kind in ("genome", "circle") and view.context == sample)
    ]
    if current not in keep:
        keep.insert(0, current)
    return keep


def build_gvixb_routes(
    app: FastAPI, engine: Any, templates: Jinja2Templates
) -> None:
    """Register result-launched pages. Routes stay synchronous like the rest of Web."""

    def render(
        request: Request,
        link: service.GvixbLink,
        view: str,
        title: str,
        back_url: str,
        back_label: str,
        views: list[service.GvixbLink] | None = None,
    ) -> HTMLResponse:
        response = templates.TemplateResponse(
            request,
            "gvixb.html",
            {
                "link": link,
                "view": view,
                "title": title,
                "back_url": back_url,
                "back_label": back_label,
                "asset_version": _asset_version(),
                "views": views or [link],
            },
        )
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.get("/gvixb-assets/{version}/{path:path}", include_in_schema=False)
    def gvixb_asset(version: str, path: str) -> FileResponse:
        """版本化静态资源：整棵 JS 模块图 URL 随版本变化，彻底绕过旧缓存。"""
        if version != _asset_version():
            raise HTTPException(404, "stale gvixb asset version")
        base = (STATIC_DIR / "gvixb").resolve()
        target = (base / path).resolve()
        if target != base and base not in target.parents:
            raise HTTPException(404, "asset path outside gvixb")
        if not target.is_file():
            raise HTTPException(404, "asset not found")
        return FileResponse(
            target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    @app.get("/gvixb/samples/{sample_id}/genome", response_class=HTMLResponse)
    def latest_genome(request: Request, sample_id: str) -> HTMLResponse:
        link = _call(lambda: service.latest_genome_link(engine, sample_id))
        if link is None:
            raise HTTPException(404, "该样本没有可查看的组装结果")
        return render(
            request, link, "assembly", f"3D 基因组 · {sample_id}",
            f"/console/samples/{sample_id}", "返回样本结果",
        )

    @app.get("/gvixb/runs/{run_id}/genome/{sample_id}", response_class=HTMLResponse)
    def run_genome(request: Request, run_id: str, sample_id: str) -> HTMLResponse:
        url = f"/gvixb/runs/{run_id}/genome/{sample_id}"
        link = _run_link(engine, run_id, url)
        return render(
            request, link, "assembly", f"3D 基因组 · {sample_id}",
            f"/console/runs/{run_id}", "返回运行记录",
            views=_switcher_views(engine, run_id, link),
        )

    @app.get("/gvixb/runs/{run_id}/annotation/{sample_id}", response_class=HTMLResponse)
    def run_annotation(request: Request, run_id: str, sample_id: str) -> HTMLResponse:
        url = f"/gvixb/runs/{run_id}/annotation/{sample_id}"
        link = _run_link(engine, run_id, url)
        return render(
            request, link, "circle", f"3D 注释圈图 · {sample_id}",
            f"/console/runs/{run_id}", "返回运行记录",
            views=_switcher_views(engine, run_id, link),
        )

    @app.get("/gvixb/samples/{sample_id}/annotation", response_class=HTMLResponse)
    def latest_annotation(request: Request, sample_id: str) -> HTMLResponse:
        link = _call(lambda: service.latest_annotation_link(engine, sample_id))
        if link is None:
            raise HTTPException(404, "该样本没有 Bakta 注释结果")
        return render(
            request, link, "circle", f"3D 注释圈图 · {sample_id}",
            f"/console/samples/{sample_id}", "返回样本结果",
        )

    @app.get("/gvixb/runs/{run_id}/tree/{cohort}/{group}", response_class=HTMLResponse)
    def run_tree(request: Request, run_id: str, cohort: str, group: str) -> HTMLResponse:
        url = f"/gvixb/runs/{run_id}/tree/{cohort}/{group}"
        link = _run_link(engine, run_id, url)
        return render(
            request, link, "phylo", f"3D 进化树 · {group}",
            f"/console/runs/{run_id}", "返回运行记录",
            views=_switcher_views(engine, run_id, link),
        )

    @app.get("/gvixb/runs/{run_id}/mst/{group}", response_class=HTMLResponse)
    def run_mst(request: Request, run_id: str, group: str) -> HTMLResponse:
        url = f"/gvixb/runs/{run_id}/mst/{group}"
        link = _run_link(engine, run_id, url)
        return render(
            request, link, "mst", f"3D 最小生成树 · {group}",
            f"/console/runs/{run_id}", "返回运行记录",
            views=_switcher_views(engine, run_id, link),
        )

    _build_gvixb_api_routes(app, engine)


def _build_gvixb_api_routes(app: FastAPI, engine: Any) -> None:
    @app.get("/api/v1/gvixb/runs/{run_id}/manifest", response_model=service.GvixbManifest)
    def manifest(run_id: str) -> service.GvixbManifest:
        return _call(lambda: service.run_manifest(engine, run_id))

    @app.get(
        "/api/v1/gvixb/runs/{run_id}/genome/{sample_id}",
        response_model=service.AssemblyPayload,
    )
    def run_genome_data(run_id: str, sample_id: str) -> service.AssemblyPayload:
        return _call(lambda: service.assembly_payload(engine, run_id, sample_id))

    @app.get(
        "/api/v1/gvixb/runs/{run_id}/annotated-genome/{sample_id}",
        response_model=service.AnnotatedGenomePayload,
    )
    def run_annotated_genome_data(run_id: str, sample_id: str) -> service.AnnotatedGenomePayload:
        return _call(lambda: service.annotated_genome_payload(engine, run_id, sample_id))

    @app.get(
        "/api/v1/gvixb/samples/{sample_id}/genome",
        response_model=service.AssemblyPayload,
    )
    def latest_genome_data(sample_id: str) -> service.AssemblyPayload:
        return _call(lambda: service.latest_assembly_payload(engine, sample_id))

    @app.get(
        "/api/v1/gvixb/samples/{sample_id}/annotated-genome",
        response_model=service.AnnotatedGenomePayload,
    )
    def latest_annotated_genome_data(sample_id: str) -> service.AnnotatedGenomePayload:
        return _call(lambda: service.latest_annotated_genome_payload(engine, sample_id))

    @app.get(
        "/api/v1/gvixb/runs/{run_id}/tree/{cohort}/{group}",
        response_model=service.TreePayload,
    )
    def run_tree_data(run_id: str, cohort: str, group: str) -> service.TreePayload:
        return _call(lambda: service.tree_payload(engine, run_id, cohort, group))

    @app.get(
        "/api/v1/gvixb/runs/{run_id}/mst/{group}",
        response_model=service.MstPayload,
    )
    def run_mst_data(run_id: str, group: str) -> service.MstPayload:
        return _call(lambda: service.mst_payload(engine, run_id, group))
