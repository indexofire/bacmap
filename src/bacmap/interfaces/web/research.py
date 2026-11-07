"""Web Research Workbench（P1）：从既有 run 生成 AMR 关联草案。"""

from __future__ import annotations

import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bacmap.interfaces.web.auth import verify_csrf
from bacmap.interfaces.web.markdown import render_markdown
from bacmap.research import advanced_stats, phylo, regression, reporting
from bacmap.research.checklist import ChecklistService
from bacmap.research.models import (
    ArtifactKind,
    ChecklistOverride,
    CreateSessionRequest,
    ResearchError,
    ResearchProfile,
)
from bacmap.research.packages import ResearchPackageService
from bacmap.research.service import (
    ResearchObjectService,
    ResearchRequestService,
    ResearchService,
    default_profile,
)
from bacmap.research.store import ResearchStore
from bacmap.store import runs as runs_store
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_EMPTY_MEMBER_FORM = Form(default=[])
_DRAFT_FILE_FORM = File(...)


def _status(code: str) -> int:
    return {"validation_error": 400, "not_found": 404, "conflict": 409}.get(code, 400)


def _raise(exc: ResearchError) -> None:
    raise HTTPException(_status(exc.code), exc.message)


def _study_context(
    engine: DbosTaskEngine, objects: ResearchObjectService, study_id: str
) -> dict[str, Any]:
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
        sessions = store.list_sessions_by_study(study_id)
        edges = store.list_edges_for_id(study_id)
    session_rows = []
    with ResearchStore(engine.home) as research:
        for session in sessions:
            artifacts = {
                artifact.kind.value: artifact
                for artifact in research.list_artifacts(session.session_id)
            }
            session_rows.append(
                {
                    "session": session,
                    "figure": artifacts.get(ArtifactKind.FIGURE.value),
                    "custom": artifacts.get(ArtifactKind.FIGURE_CUSTOM.value),
                }
            )
    checklist_service = ChecklistService(engine.home)
    try:
        checklist = checklist_service.merged(study_id)
        checklist_review = checklist_service.get_review(study_id)
    except ValueError:
        checklist = None
        checklist_review = None
    return {
        "study": study,
        "cohorts": cohorts,
        "plans": plans,
        "claims": claims,
        "experiments": experiments,
        "sessions": session_rows,
        "checklist": checklist,
        "checklist_review": checklist_review,
        "edges": edges,
        "readiness": objects.publication_readiness(study_id),
    }


def _session_context(
    service: ResearchService, objects: ResearchObjectService, session_id: str
) -> dict[str, Any]:
    try:
        view = service.get_session(session_id)
    except ResearchError as exc:
        _raise(exc)
        raise  # pragma: no cover
    artifacts = {artifact.kind.value: artifact for artifact in view.artifacts}
    spec = None
    manifest = None
    if view.stat is not None:
        try:
            spec = service.figure_spec(session_id)
        except ResearchError:
            spec = None
    manifest_artifact = artifacts.get(ArtifactKind.FIGURE_MANIFEST.value)
    if manifest_artifact is not None:
        try:
            manifest = json.loads(Path(manifest_artifact.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None
    report_html = ""
    manuscript_html = ""
    for kind, target in (
        (ArtifactKind.REPORT.value, "report_html"),
        (ArtifactKind.MANUSCRIPT.value, "manuscript_html"),
    ):
        artifact = artifacts.get(kind)
        if artifact is not None:
            path = Path(artifact.path)
            if path.is_file():
                rendered = render_markdown(path.read_text(encoding="utf-8"))
                if target == "report_html":
                    report_html = rendered
                else:
                    manuscript_html = rendered
    from bacmap.research.store import ResearchObjectStore

    with ResearchObjectStore(service.home) as store:
        edges = store.list_edges_for_id(session_id)
    study = None
    if view.session.study_id:
        try:
            study = objects.get_study(view.session.study_id)
        except KeyError:
            study = None
    return {
        "view": view,
        "session": view.session,
        "artifacts": artifacts,
        "spec": spec,
        "manifest": manifest,
        "study": study,
        "drafts": service.list_drafts(session_id),
        "edges": edges,
        "report_html": report_html,
        "manuscript_html": manuscript_html,
        "note": str(view.session.payload.get("note") or ""),
    }


def build_research_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    service = ResearchService(engine.home)
    objects = ResearchObjectService(engine.home)
    requests = ResearchRequestService(engine.home)
    packages = ResearchPackageService(engine.home)

    @app.get("/research", response_class=HTMLResponse)
    def research_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research.html",
            {
                "sessions": service.list_sessions(50),
                "studies": objects.list_studies(20),
                "claims": _claims(objects),
                "requests": _request_rows(
                    requests.list_requests(status="proposed", limit=20)
                ),
                "runs": runs_store.list_runs(engine.home / "runs.sqlite", 50),
                "default_profile": default_profile().value,
                "profiles": [p.value for p in ResearchProfile],
            },
        )

    @app.get("/research/studies/{study_id}", response_class=HTMLResponse)
    def study_detail(request: Request, study_id: str) -> HTMLResponse:
        context = _study_context(engine, objects, study_id)
        context["packages"] = packages.list_packages(study_id, limit=20)
        return _TEMPLATES.TemplateResponse(request, "research_study.html", context)

    @app.post("/research/sessions")
    def research_create(
        request: Request,
        run_id: str = Form(...),
        gene: str = Form(...),
        test_name: str = Form(...),
        profile: str = Form(""),
        study_id: str = Form(""),
        cohort_id: str = Form(""),
        plan_id: str = Form(""),
        note: str = Form(""),
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
                    run_id=run_id,
                    gene=gene,
                    test_name=test_name,
                    profile=p,
                    study_id=study_id,
                    cohort_id=cohort_id,
                    plan_id=plan_id,
                    note=note,
                ),
                actor="web",
                profile=p,
            )
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return RedirectResponse(f"/research/{view.session.session_id}", status_code=303)

    _phylo_routes(app, engine)
    _stats_routes(app)
    _advanced_stats_routes(app)

    @app.get("/research/{session_id}", response_class=HTMLResponse)
    def research_detail(request: Request, session_id: str) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research_detail.html",
            _session_context(service, objects, session_id),
        )

    _object_form_routes(app, objects)
    _artifact_routes(app, service)
    _package_routes(app, engine, objects)
    _package_history_routes(app, packages, objects)
    _checklist_routes(app, engine, objects)
    _request_routes(app, requests)
    _cohort_builder_routes(app, engine, objects)
    _draft_upload_routes(app, engine, service)
    _draft_routes(app, engine, service)


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

    @app.get("/research/{session_id}/artifact/{kind}")
    def research_artifact(session_id: str, kind: str) -> FileResponse:
        allowed = {item.value for item in ArtifactKind}
        if kind not in allowed:
            raise HTTPException(404, f"unknown artifact kind: {kind}")
        try:
            path = service.read_artifact(session_id, kind)
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=path.name)


def _package_routes(
    app: FastAPI, engine: DbosTaskEngine, objects: ResearchObjectService
) -> None:
    def _package_dir(study_id: str) -> Path:
        return engine.home / "research" / "packages" / study_id

    @app.get("/research/studies/{study_id}/package", response_class=HTMLResponse)
    def research_package_page(request: Request, study_id: str) -> HTMLResponse:
        try:
            study = objects.get_study(study_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        target = _package_dir(study_id)
        shutil.rmtree(target, ignore_errors=True)
        try:
            package = reporting.build_submission_package(engine.home, study_id, target)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return _TEMPLATES.TemplateResponse(
            request,
            "research_package.html",
            {"study": study, "package": package, "checklist": package.checklist},
        )

    @app.get("/research/studies/{study_id}/package.zip")
    def research_package_zip(study_id: str) -> FileResponse:
        target = _package_dir(study_id)
        shutil.rmtree(target, ignore_errors=True)
        try:
            reporting.build_submission_package(engine.home, study_id, target)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        archive = Path(shutil.make_archive(str(target), "zip", root_dir=target))
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"{study_id}_submission.zip",
        )


def _phylo_routes(app: FastAPI, engine: DbosTaskEngine) -> None:
    output_dir = engine.home / "research" / "phylo"

    @app.get("/research/phylo", response_class=HTMLResponse)
    def phylo_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research_phylo.html",
            {"alignment": "", "dates": "", "partitions": "", "goal": "bayesian"},
        )

    @app.post("/research/phylo", response_class=HTMLResponse)
    def phylo_submit(
        request: Request,
        alignment: str = Form(""),
        dates: str = Form(""),
        partitions: str = Form(""),
        goal: str = Form("bayesian"),
        profile_json: str = Form(""),
        plan_json: str = Form(""),
        action: str = Form("profile"),
        run_validation: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        context: dict[str, Any] = {
            "alignment": alignment,
            "dates": dates,
            "partitions": partitions,
            "goal": goal,
            "profile_json": profile_json,
            "plan_json": plan_json,
            "error": "",
        }
        try:
            if action == "profile" or not profile_json:
                profile = phylo.profile_alignment(
                    alignment,
                    dates=dates or None,
                    partitions=[
                        item.strip() for item in partitions.split(",") if item.strip()
                    ],
                )
                context["profile"] = profile
                context["profile_json"] = json.dumps(
                    profile.model_dump(mode="json", by_alias=True)
                )
            else:
                profile = phylo.AlignmentProfile.model_validate(json.loads(profile_json))
                context["profile"] = profile

            if action in {"plan", "xml", "iqtree"}:
                if plan_json:
                    plan = phylo.PhyloPlan.model_validate(json.loads(plan_json))
                else:
                    plan = phylo.recommend_plan(
                        profile, "ml" if goal == "ml" else "bayesian"
                    )
                context["plan"] = plan
                context["plan_json"] = json.dumps(
                    plan.model_dump(mode="json", by_alias=True)
                )
                context["issues"] = phylo.validate_plan(plan, profile)

            if action == "xml":
                output_dir.mkdir(parents=True, exist_ok=True)
                xml_path = output_dir / f"{uuid4().hex[:12]}.xml"
                context["xml_result"] = phylo.render_beast2_xml(
                    plan, profile, xml_path, validate=bool(run_validation)
                )
                context["xml_name"] = xml_path.name

            if action == "iqtree":
                prefix = str(output_dir / f"iqtree-{uuid4().hex[:8]}")
                context["iqtree_command"] = phylo.render_iqtree_command(
                    plan, alignment, prefix
                )
        except (phylo.PhyloError, ValueError, OSError) as exc:
            context["error"] = str(exc)
        return _TEMPLATES.TemplateResponse(request, "research_phylo.html", context)

    @app.get("/research/phylo/download/{name}")
    def phylo_download(name: str) -> FileResponse:
        if Path(name).name != name or not name.endswith(".xml"):
            raise HTTPException(400, "invalid XML name")
        path = output_dir / name
        if not path.is_file():
            raise HTTPException(404, "XML not found")
        return FileResponse(path, media_type="application/xml", filename=name)


def _stats_routes(app: FastAPI) -> None:
    @app.get("/research/stats", response_class=HTMLResponse)
    def stats_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research_stats.html",
            {"data_path": "", "outcome": "", "predictors": "", "error": ""},
        )

    @app.post("/research/stats", response_class=HTMLResponse)
    def stats_submit(
        request: Request,
        data_path: str = Form(""),
        outcome: str = Form(""),
        predictors: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        context: dict[str, Any] = {
            "data_path": data_path,
            "outcome": outcome,
            "predictors": predictors,
            "error": "",
        }
        names = [name.strip() for name in predictors.split(",") if name.strip()]
        try:
            rows, outcomes, dropped = regression.load_table(
                data_path, outcome, names
            )
            result = regression.fit_logistic(rows, outcomes, names)
            context["result"] = result
            context["dropped"] = dropped
            context["terms"] = [
                {
                    "name": name,
                    "beta": beta,
                    "odds_ratio": odds,
                    "ci_low": low,
                    "ci_high": high,
                    "p_value": p_value,
                }
                for name, beta, odds, low, high, p_value in zip(
                    result.feature_names,
                    result.coefficients,
                    result.odds_ratios,
                    result.ci_low,
                    result.ci_high,
                    result.p_values,
                    strict=True,
                )
            ]
            context["result_json"] = json.dumps(
                result.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
        except ValueError as exc:
            context["error"] = str(exc)
        return _TEMPLATES.TemplateResponse(request, "research_stats.html", context)


def _advanced_stats_routes(app: FastAPI) -> None:
    @app.get("/research/stats/iptw", response_class=HTMLResponse)
    def iptw_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research_iptw.html",
            {
                "data_path": "",
                "treatment": "",
                "outcome": "",
                "covariates": "",
                "weight": "ate",
                "error": "",
            },
        )

    @app.post("/research/stats/iptw", response_class=HTMLResponse)
    def iptw_submit(
        request: Request,
        data_path: str = Form(""),
        treatment: str = Form(""),
        outcome: str = Form(""),
        covariates: str = Form(""),
        weight: str = Form("ate"),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        names = [name.strip() for name in covariates.split(",") if name.strip()]
        context: dict[str, Any] = {
            "data_path": data_path,
            "treatment": treatment,
            "outcome": outcome,
            "covariates": covariates,
            "weight": weight,
            "error": "",
        }
        try:
            rows, dropped = regression.load_columns(
                data_path, [treatment, outcome, *names]
            )
            result = advanced_stats.fit_iptw(
                [int(row[treatment]) for row in rows],
                [int(row[outcome]) for row in rows],
                [[row[name] for name in names] for row in rows],
                names,
                weight_type="att" if weight == "att" else "ate",
            )
            context["result"] = result
            context["dropped"] = dropped
        except ValueError as exc:
            context["error"] = str(exc)
        return _TEMPLATES.TemplateResponse(request, "research_iptw.html", context)

    @app.get("/research/stats/match", response_class=HTMLResponse)
    def match_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research_match.html",
            {
                "data_path": "",
                "treatment": "",
                "outcome": "",
                "covariates": "",
                "caliper": "0.05",
                "error": "",
            },
        )

    @app.post("/research/stats/match", response_class=HTMLResponse)
    def match_submit(
        request: Request,
        data_path: str = Form(""),
        treatment: str = Form(""),
        outcome: str = Form(""),
        covariates: str = Form(""),
        caliper: str = Form("0.05"),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        names = [name.strip() for name in covariates.split(",") if name.strip()]
        context: dict[str, Any] = {
            "data_path": data_path,
            "treatment": treatment,
            "outcome": outcome,
            "covariates": covariates,
            "caliper": caliper,
            "error": "",
        }
        try:
            rows, dropped = regression.load_columns(
                data_path, [treatment, outcome, *names]
            )
            result = advanced_stats.fit_match(
                [int(row[treatment]) for row in rows],
                [int(row[outcome]) for row in rows],
                [[row[name] for name in names] for row in rows],
                names,
                caliper=float(caliper),
            )
            context["result"] = result
            context["dropped"] = dropped
        except ValueError as exc:
            context["error"] = str(exc)
        return _TEMPLATES.TemplateResponse(request, "research_match.html", context)

    @app.get("/research/stats/survival", response_class=HTMLResponse)
    def survival_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "research_survival.html",
            {"data_path": "", "time": "", "event": "", "group": "", "error": ""},
        )

    @app.post("/research/stats/survival", response_class=HTMLResponse)
    def survival_submit(
        request: Request,
        data_path: str = Form(""),
        time: str = Form(""),
        event: str = Form(""),
        group: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        context: dict[str, Any] = {
            "data_path": data_path,
            "time": time,
            "event": event,
            "group": group,
            "error": "",
        }
        try:
            times, events, groups, dropped = regression.load_survival_table(
                data_path, time, event, group
            )
            context["result"] = advanced_stats.kaplan_meier(times, events, groups)
            context["dropped"] = dropped
        except ValueError as exc:
            context["error"] = str(exc)
        return _TEMPLATES.TemplateResponse(request, "research_survival.html", context)


def _draft_upload_routes(
    app: FastAPI, engine: DbosTaskEngine, service: ResearchService
) -> None:
    upload_dir = engine.home / "research" / "uploads"

    @app.post("/research/{session_id}/drafts")
    async def upload_draft(
        request: Request,
        session_id: str,
        file: UploadFile = _DRAFT_FILE_FORM,
        note: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".svg", ".png", ".pdf"}:
            raise HTTPException(400, "draft must be SVG, PNG or PDF")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(400, "draft exceeds 10 MiB")
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp = upload_dir / f"{uuid4().hex}{suffix}"
        temp.write_bytes(data)
        try:
            service.create_draft(session_id, temp, note=note, actor="web")
        except ResearchError as exc:
            _raise(exc)
        finally:
            temp.unlink(missing_ok=True)
        return RedirectResponse(f"/research/{session_id}", status_code=303)


def _draft_routes(
    app: FastAPI, engine: DbosTaskEngine, service: ResearchService
) -> None:
    @app.get("/research/drafts/{draft_id}/file")
    def draft_file(draft_id: str) -> FileResponse:
        try:
            draft = service.get_draft(draft_id)
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        path = Path(draft.path)
        if not path.is_file():
            raise HTTPException(404, "draft file not found")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.post("/research/drafts/{draft_id}/feedback")
    def draft_feedback(
        request: Request,
        draft_id: str,
        feedback: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            draft = service.add_draft_feedback(draft_id, feedback, actor="web")
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return RedirectResponse(f"/research/{draft.session_id}", status_code=303)

    @app.post("/research/drafts/{draft_id}/finalize")
    def draft_finalize(
        request: Request,
        draft_id: str,
        recipe_id: str = Form("custom"),
        code_path: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            draft = service.get_draft(draft_id)
            service.finalize_draft(
                draft_id,
                recipe_id=recipe_id or "custom",
                code_path=code_path or None,
                actor="web",
            )
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return RedirectResponse(f"/research/{draft.session_id}", status_code=303)

    @app.post("/research/drafts/{draft_id}/reject")
    def draft_reject(
        request: Request,
        draft_id: str,
        note: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            draft = service.reject_draft(draft_id, note=note, actor="web")
        except ResearchError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return RedirectResponse(f"/research/{draft.session_id}", status_code=303)


def _members_from_form(values: list[str]) -> list[dict[str, str]]:
    members: list[dict[str, str]] = []
    for value in values:
        if "|" not in value:
            continue
        run_id, isolate_id = value.split("|", 1)
        if run_id and isolate_id:
            members.append({"isolate_id": isolate_id, "run_id": run_id})
    return members


def _cohort_builder_routes(
    app: FastAPI, engine: DbosTaskEngine, objects: ResearchObjectService
) -> None:
    def _render(
        request: Request,
        study_id: str,
        *,
        members: list[dict[str, str]] | None = None,
        name: str = "",
        rules_raw: str = "{}",
        preview: dict[str, Any] | None = None,
        error: str = "",
    ) -> HTMLResponse:
        study = objects.get_study(study_id)
        selected = {
            f"{member.get('run_id', '')}|{member.get('isolate_id', '')}"
            for member in (members or [])
        }
        return _TEMPLATES.TemplateResponse(
            request,
            "research_cohort_builder.html",
            {
                "study": study,
                "runs": runs_store.list_runs(engine.home / "runs.sqlite", 50),
                "selected": selected,
                "name": name,
                "rules_raw": rules_raw,
                "preview": preview,
                "error": error,
            },
        )

    @app.get(
        "/research/studies/{study_id}/cohorts/builder", response_class=HTMLResponse
    )
    def cohort_builder(request: Request, study_id: str) -> HTMLResponse:
        try:
            return _render(request, study_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post(
        "/research/studies/{study_id}/cohorts/builder", response_class=HTMLResponse
    )
    def cohort_builder_submit(
        request: Request,
        study_id: str,
        name: str = Form(""),
        rules: str = Form("{}"),
        member: list[str] = _EMPTY_MEMBER_FORM,
        action: str = Form("preview"),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        members = _members_from_form(member)
        try:
            rules_obj = _json_field(rules, "rules")
        except HTTPException as exc:
            return _render(
                request,
                study_id,
                members=members,
                name=name,
                rules_raw=rules,
                error=str(exc.detail),
            )
        if not members:
            return _render(
                request,
                study_id,
                members=members,
                name=name,
                rules_raw=rules,
                error="至少选择一个样本",
            )
        preview = objects.preview_cohort(study_id, members, rules_obj)
        if action == "create":
            if not preview["ok"]:
                return _render(
                    request,
                    study_id,
                    members=members,
                    name=name,
                    rules_raw=rules,
                    preview=preview,
                    error="预检未通过：请先处理重复成员或缺失 run",
                )
            objects.create_cohort(study_id, members, rules_obj, name, "web")
            return RedirectResponse(
                f"/research/studies/{study_id}", status_code=303
            )
        return _render(
            request,
            study_id,
            members=members,
            name=name,
            rules_raw=rules,
            preview=preview,
        )


def _request_routes(app: FastAPI, requests: ResearchRequestService) -> None:
    @app.post("/research/requests/{request_id}/approve")
    def approve_request_form(
        request: Request,
        request_id: str,
        members: str = Form(""),
        plan_spec: str = Form(""),
        note: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            reviewed = requests.approve_request(
                request_id,
                members=_json_field(members, "members") if members.strip() else None,
                plan_spec=_json_field(plan_spec, "plan_spec") if plan_spec.strip() else None,
                actor="web",
                note=note,
            )
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if reviewed.study_id:
            return RedirectResponse(
                f"/research/studies/{reviewed.study_id}", status_code=303
            )
        return RedirectResponse("/research", status_code=303)

    @app.post("/research/requests/{request_id}/reject")
    def reject_request_form(
        request: Request,
        request_id: str,
        note: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            requests.reject_request(request_id, actor="web", note=note)
        except (ResearchError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse("/research", status_code=303)


def _request_rows(items: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "request": item,
            "members_json": json.dumps(item.members, ensure_ascii=False),
            "plan_spec_json": json.dumps(item.plan_spec, ensure_ascii=False),
        }
        for item in items
    ]


def _package_history_routes(
    app: FastAPI,
    packages: ResearchPackageService,
    objects: ResearchObjectService,
) -> None:
    @app.get("/research/studies/{study_id}/packages", response_class=HTMLResponse)
    def package_history(request: Request, study_id: str) -> HTMLResponse:
        try:
            study = objects.get_study(study_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return _TEMPLATES.TemplateResponse(
            request,
            "research_packages.html",
            {"study": study, "packages": packages.list_packages(study_id, 50)},
        )

    @app.post("/research/studies/{study_id}/packages")
    def package_build(
        request: Request,
        study_id: str,
        label: str = Form(""),
        csrf: str = Form(""),
    ) -> Any:
        if not verify_csrf(request, csrf):
            raise HTTPException(403, "CSRF 校验失败")
        try:
            record = packages.build(study_id, actor="web", label=label)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return RedirectResponse(
            f"/research/packages/{record.package_id}", status_code=303
        )

    @app.get("/research/packages/{package_id}", response_class=HTMLResponse)
    def package_detail(request: Request, package_id: str) -> HTMLResponse:
        try:
            record = packages.get_package(package_id)
            study = objects.get_study(record.study_id)
            manifest = packages.load_manifest(record)
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, str(exc)) from exc
        return _TEMPLATES.TemplateResponse(
            request,
            "research_package.html",
            {
                "study": study,
                "package": manifest,
                "checklist": manifest.get("checklist", {}),
                "record": record,
            },
        )

    @app.get("/research/packages/{package_id}/download.zip")
    def package_zip(package_id: str) -> FileResponse:
        try:
            record = packages.get_package(package_id)
            archive = packages.zip_path(record)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"{package_id}.zip",
        )


def _checklist_routes(
    app: FastAPI, engine: DbosTaskEngine, objects: ResearchObjectService
) -> None:
    service = ChecklistService(engine.home)

    def _context(study_id: str, error: str = "") -> dict[str, Any]:
        study = objects.get_study(study_id)
        return {
            "study": study,
            "checklist": service.merged(study_id),
            "review": service.get_review(study_id),
            "error": error,
        }

    @app.get(
        "/research/studies/{study_id}/checklist", response_class=HTMLResponse
    )
    def checklist_page(request: Request, study_id: str) -> HTMLResponse:
        try:
            context = _context(study_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return _TEMPLATES.TemplateResponse(request, "research_checklist.html", context)

    @app.post(
        "/research/studies/{study_id}/checklist", response_class=HTMLResponse
    )
    async def checklist_submit(request: Request, study_id: str) -> Any:
        form = await request.form()
        if not verify_csrf(request, str(form.get("csrf", ""))):
            raise HTTPException(403, "CSRF 校验失败")
        action = str(form.get("action", "save"))
        try:
            base = service.base(study_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        statuses: dict[str, Literal["met", "partial", "missing", "not_applicable"]] = {
            "met": "met",
            "partial": "partial",
            "missing": "missing",
            "not_applicable": "not_applicable",
        }
        overrides: list[ChecklistOverride] = []
        for item in base.items:
            raw_status = str(form.get(f"status:{item.item_id}", item.status))
            status = statuses.get(raw_status, item.status)
            evidence = str(form.get(f"evidence:{item.item_id}", "; ".join(item.evidence)))
            note = str(form.get(f"note:{item.item_id}", item.note))
            overrides.append(
                ChecklistOverride(
                    item_id=item.item_id,
                    status=status,
                    evidence=[part.strip() for part in evidence.split(";") if part.strip()],
                    note=note,
                )
            )
        try:
            if action == "reset":
                service.reset(study_id, actor="web")
            elif action == "sign":
                service.sign(study_id, overrides, actor="web", note=str(form.get("note", "")))
            else:
                service.save(study_id, overrides, actor="web", note=str(form.get("note", "")))
        except ValueError as exc:
            return _TEMPLATES.TemplateResponse(
                request,
                "research_checklist.html",
                {**_context(study_id), "error": str(exc)},
            )
        return RedirectResponse(
            f"/research/studies/{study_id}/checklist", status_code=303
        )


def _claims(objects: ResearchObjectService) -> list:
    from bacmap.research.store import ResearchObjectStore

    with ResearchObjectStore(objects.home) as store:
        return store.list_claims(limit=20)
