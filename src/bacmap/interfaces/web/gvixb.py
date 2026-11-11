"""gvixb Web 页面与同源只读数据路由。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bacmap.interfaces import gvixb as service


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
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "gvixb.html",
            {
                "link": link,
                "view": view,
                "title": title,
                "back_url": back_url,
                "back_label": back_label,
            },
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
        )

    @app.get("/gvixb/runs/{run_id}/annotation/{sample_id}", response_class=HTMLResponse)
    def run_annotation(request: Request, run_id: str, sample_id: str) -> HTMLResponse:
        url = f"/gvixb/runs/{run_id}/annotation/{sample_id}"
        link = _run_link(engine, run_id, url)
        return render(
            request, link, "circle", f"3D 注释圈图 · {sample_id}",
            f"/console/runs/{run_id}", "返回运行记录",
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
        )

    @app.get("/gvixb/runs/{run_id}/mst/{group}", response_class=HTMLResponse)
    def run_mst(request: Request, run_id: str, group: str) -> HTMLResponse:
        url = f"/gvixb/runs/{run_id}/mst/{group}"
        link = _run_link(engine, run_id, url)
        return render(
            request, link, "mst", f"3D 最小生成树 · {group}",
            f"/console/runs/{run_id}", "返回运行记录",
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
