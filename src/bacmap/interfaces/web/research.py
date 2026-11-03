"""Web Research Workbench（P1）：从既有 run 生成 AMR 关联草案。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bacmap.interfaces.web.auth import verify_csrf
from bacmap.research.models import CreateSessionRequest, ResearchError, ResearchProfile
from bacmap.research.service import ResearchObjectService, ResearchService, default_profile
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _status(code: str) -> int:
    return {"validation_error": 400, "not_found": 404, "conflict": 409}.get(code, 400)


def _raise(exc: ResearchError) -> None:
    raise HTTPException(_status(exc.code), exc.message)


def build_research_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    service = ResearchService(engine.home)

    objects = ResearchObjectService(engine.home)

    @app.get("/research", response_class=HTMLResponse)
    def research_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research.html",
            {
                "sessions": service.list_sessions(50),
                "studies": objects.list_studies(20),
                "claims": _claims(objects),
                "default_profile": default_profile().value,
                "profiles": [p.value for p in ResearchProfile],
            },
        )

    @app.get("/research/studies/{study_id}", response_class=HTMLResponse)
    def study_detail(request: Request, study_id: str) -> HTMLResponse:
        from bacmap.research.store import ResearchObjectStore

        try:
            study = objects.get_study(study_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        with ResearchObjectStore(engine.home) as store:
            cohorts = store.list_cohorts(study_id)
            plans = store.list_plans(study_id)
            claims = store.list_claims(study_id)
            experiments = store.list_experiments(study_id=study_id)
        return _TEMPLATES.TemplateResponse(
            request,
            "research_study.html",
            {
                "study": study,
                "cohorts": cohorts,
                "plans": plans,
                "claims": claims,
                "experiments": experiments,
                "readiness": objects.publication_readiness(study_id),
            },
        )

    @app.post("/research/sessions")
    def research_create(
        request: Request,
        run_id: str = Form(...),
        gene: str = Form(...),
        test_name: str = Form(...),
        profile: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            p = ResearchProfile(profile) if profile else default_profile()
        except ValueError as exc:
            raise HTTPException(400, f"unknown research profile: {profile}") from exc
        try:
            view = service.create_session(
                CreateSessionRequest(
                    run_id=run_id, gene=gene, test_name=test_name, profile=p
                ),
                actor="web",
                profile=p,
            )
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return RedirectResponse(f"/research/{view.session.session_id}", status_code=303)

    @app.get("/research/{session_id}", response_class=HTMLResponse)
    def research_detail(request: Request, session_id: str) -> HTMLResponse:
        try:
            view = service.get_session(session_id)
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return _TEMPLATES.TemplateResponse(
            request, "research_detail.html", {"view": view, "session": view.session}
        )

    _object_form_routes(app, objects)
    _artifact_routes(app, service)


def _json_field(raw: str, what: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"{what} must be valid JSON: {exc}") from exc


def _object_form_routes(app: FastAPI, objects: ResearchObjectService) -> None:
    _study_cohort_form_routes(app, objects)
    _plan_experiment_form_routes(app, objects)
    _claim_form_routes(app, objects)


def _study_cohort_form_routes(app: FastAPI, objects: ResearchObjectService) -> None:
    @app.post("/research/studies")
    def create_study_form(
        request: Request,
        question: str = Form(...),
        pathogen_scope: str = Form(""),
        data_class: int = Form(2),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            study = objects.create_study(question, pathogen_scope, data_class, "web")
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{study.study_id}", status_code=303)

    @app.post("/research/studies/{study_id}/cohorts")
    def create_cohort_form(
        request: Request,
        study_id: str,
        name: str = Form(""),
        members: str = Form("[]"),
        rules: str = Form("{}"),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            objects.create_cohort(
                study_id, _json_field(members, "members"), _json_field(rules, "rules"),
                name, "web",
            )
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{study_id}", status_code=303)

    @app.post("/research/cohorts/{cohort_id}/freeze")
    def freeze_cohort_form(
        request: Request, cohort_id: str, csrf: str = Form("")
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            cohort = objects.freeze_cohort(cohort_id, "web")
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{cohort.study_id}", status_code=303)

def _plan_experiment_form_routes(app: FastAPI, objects: ResearchObjectService) -> None:
    @app.post("/research/studies/{study_id}/plans")
    def create_plan_form(
        request: Request,
        study_id: str,
        cohort_id: str = Form(...),
        spec: str = Form("{}"),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            objects.create_plan(study_id, cohort_id, _json_field(spec, "spec"), "web")
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{study_id}", status_code=303)

    @app.post("/research/plans/{plan_id}/freeze")
    def freeze_plan_form(request: Request, plan_id: str, csrf: str = Form("")) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            plan = objects.freeze_plan(plan_id, "web")
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{plan.study_id}", status_code=303)

    @app.post("/research/experiments")
    def create_experiment_form(
        request: Request,
        plan_id: str = Form(...),
        status: str = Form(...),
        run_ids: str = Form(""),
        outcome: str = Form("{}"),
        deviation: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            exp = objects.record_experiment(
                plan_id,
                status,
                [x.strip() for x in run_ids.split(",") if x.strip()],
                _json_field(outcome, "outcome"),
                deviation,
                "web",
            )
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{exp.study_id}", status_code=303)

def _claim_form_routes(app: FastAPI, objects: ResearchObjectService) -> None:
    @app.post("/research/studies/{study_id}/claims")
    def create_claim_form(
        request: Request,
        study_id: str,
        claim_type: str = Form(...),
        wording: str = Form(...),
        evidence_level: str = Form("E0"),
        evidence: str = Form("{}"),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            objects.create_claim(
                study_id, claim_type, wording, evidence_level,
                _json_field(evidence, "evidence"), "web",
            )
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{study_id}", status_code=303)

    @app.post("/research/claims/{claim_id}/review")
    def review_claim_form(
        request: Request,
        claim_id: str,
        decision: str = Form(...),
        message: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            claim = objects.review_claim(claim_id, decision, message, "web")
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/research/studies/{claim.study_id}", status_code=303)

def _artifact_routes(app: FastAPI, service: ResearchService) -> None:
    @app.get("/research/{session_id}/figure.svg")
    def research_figure(session_id: str) -> FileResponse:
        try:
            path = service.read_artifact(session_id, "figure")
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return FileResponse(path, media_type="image/svg+xml")

    @app.get("/research/{session_id}/report.md")
    def research_report(session_id: str) -> PlainTextResponse:
        try:
            path = service.read_artifact(session_id, "report")
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.get("/research/{session_id}/manuscript.md")
    def research_manuscript(session_id: str) -> PlainTextResponse:
        try:
            path = service.read_artifact(session_id, "manuscript")
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")



def _claims(objects: ResearchObjectService) -> list:
    from bacmap.research.store import ResearchObjectStore

    with ResearchObjectStore(objects.home) as store:
        return store.list_claims(limit=20)
