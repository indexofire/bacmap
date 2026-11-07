"""Web Research Workbench pages: dashboard, session, study, package, downloads."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.research.models import CreateSessionRequest, ResearchProfile
from bacmap.research.service import (
    ResearchObjectService,
    ResearchRequestService,
    ResearchService,
)
from bacmap.store import runs
from bacmap.store.genome_object_service import ensure_gom_schema
from bacmap.store.lab_results import LabResultService


def _build_home(home: Path) -> None:
    wf = home / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 2\niqu_tree_seed: 42\n")
    strains = [f"S{i:02d}" for i in range(20)]
    run = runs.create_run(
        "bacmap", wf, strains, db_path=home / "runs.sqlite", task_id="task-1"
    )
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute(
            "UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", ("run-1", run.run_id)
        )
    ensure_gom_schema(home / "gom.sqlite")
    with sqlite3.connect(home / "gom.sqlite") as conn:
        for i, sid in enumerate(strains):
            if i < 10:
                conn.execute(
                    "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                    " VALUES (?,?,?)",
                    (sid, "blaKPC-33", "card"),
                )
    with LabResultService(home / "data" / "bacmap.sqlite") as svc:
        for i, sid in enumerate(strains):
            svc.add(
                sid,
                "mic",
                "meropenem",
                "0.25",
                interpretation="R" if i < 8 else "S" if i < 16 else "I",
            )


@pytest.fixture
def web(tmp_path: Path, monkeypatch):
    _build_home(tmp_path)
    objects = ResearchObjectService(tmp_path)
    study = objects.create_study("Is blaKPC-33 associated with meropenem?", "KPN", 2, "t")
    cohort = objects.create_cohort(
        study.study_id,
        [{"isolate_id": f"S{i:02d}", "run_id": "run-1"} for i in range(20)],
        name="discovery",
        actor="t",
    )
    objects.freeze_cohort(cohort.cohort_id, "t")
    plan = objects.create_plan(
        study.study_id,
        cohort.cohort_id,
        {"run_id": "run-1", "gene": "blaKPC-33", "test_name": "meropenem"},
        "t",
    )
    objects.freeze_plan(plan.plan_id, "t")
    claim = objects.create_claim(
        study.study_id,
        "association",
        "blaKPC-33 is associated with meropenem resistance",
        "E2",
        {"run_id": "run-1"},
        "t",
    )
    objects.review_claim(claim.claim_id, "approve", "", "t")
    objects.record_experiment(plan.plan_id, "success", ["run-1"], {"n": 16}, actor="t")
    service = ResearchService(tmp_path)
    view = service.create_session(
        CreateSessionRequest(
            run_id="run-1",
            gene="blaKPC-33",
            test_name="meropenem",
            profile=ResearchProfile.RESEARCH,
            study_id=study.study_id,
            cohort_id=cohort.cohort_id,
            plan_id=plan.plan_id,
            note="Web test note",
        ),
        actor="t",
    )
    svg = tmp_path / "custom.svg"
    svg.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>",
        encoding="utf-8",
    )
    code = tmp_path / "plot.py"
    code.write_text("print('plot')\n", encoding="utf-8")
    service.attach_figure(
        view.session.session_id,
        svg,
        code=code,
        renderer="agent-script",
        recipe_id="custom",
    )
    monkeypatch.setattr(eng, "_run_snakemake", lambda p: object())
    engine = eng.DbosTaskEngine(tmp_path)
    client = TestClient(create_app(engine))
    yield client, view.session.session_id, study.study_id, tmp_path
    eng.shutdown_dbos()


def test_research_home_shows_run_and_study(web):
    client, _, study_id, _ = web
    body = client.get("/research").text
    assert "新建研究会话" in body
    assert "run-1" in body
    assert study_id in body
    assert "研究说明" in body


def test_session_detail_shows_figure_spec_and_custom(web):
    client, session_id, _, _ = web
    body = client.get(f"/research/{session_id}").text
    assert "FigureSpec" in body
    assert "自定义图 provenance" in body
    assert "figure_custom" in body
    assert "Web test note" in body
    assert "全部产物" in body


def test_study_page_shows_checklist_and_package(web):
    client, _, study_id, _ = web
    body = client.get(f"/research/studies/{study_id}").text
    assert "研究结果" in body
    assert "STROBE 草案" in body
    assert "查看投稿包" in body
    assert "下载 ZIP" in body
    assert "met=" in body


def test_package_page_and_zip(web):
    client, _, study_id, _ = web
    page = client.get(f"/research/studies/{study_id}/package")
    assert page.status_code == 200
    assert "投稿包" in page.text
    assert "STROBE 草案" in page.text
    archive = client.get(f"/research/studies/{study_id}/package.zip")
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        names = set(zf.namelist())
    assert "submission_manifest.json" in names
    assert "strobe_checklist.json" in names


def test_web_session_create_links_provenance(web):
    client, _, study_id, _ = web
    response = client.post(
        "/research/sessions",
        data={
            "run_id": "run-1",
            "gene": "blaKPC-33",
            "test_name": "meropenem",
            "profile": "research",
            "study_id": study_id,
            "note": "created from web",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    body = client.get(response.headers["location"]).text
    assert "created from web" in body
    assert study_id in body


def test_artifact_downloads(web):
    client, session_id, _, _ = web
    spec = client.get(f"/research/{session_id}/artifact/figure_spec")
    assert spec.status_code == 200
    assert "figure_spec" in spec.text
    custom = client.get(f"/research/{session_id}/artifact/figure_custom")
    assert custom.status_code == 200
    assert custom.headers["content-type"].startswith("image/svg+xml")
    assert json.loads(spec.text)["schema"] == "bacmap.figure_spec/1"


def test_request_inbox_and_approval(web):
    client, _, _, home = web
    request = ResearchRequestService(home).propose_request(
        "Agent proposed question",
        pathogen_scope="KPN",
        run_ids=["run-1"],
        gene="blaKPC-33",
        test_name="meropenem",
        analysis="association",
        note="from agent",
        actor="mcp-stdio:local-trusted:test",
    )
    page = client.get("/research").text
    assert "研究请求收件箱" in page
    assert request.request_id in page
    response = client.post(
        f"/research/requests/{request.request_id}/approve",
        data={"members": "", "plan_spec": "", "note": "web approved"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    reviewed = ResearchRequestService(home).get_request(request.request_id)
    assert reviewed.status.value == "approved"
    assert reviewed.study_id
    assert reviewed.session_id
