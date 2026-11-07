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
from bacmap.research.analyses import ResearchAnalysisService
from bacmap.research.checklist import ChecklistService
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
    (tmp_path / "alignment.fasta").write_text(
        ">t1\nACGTACGTACGT\n>t2\nACGTACGTACGA\n"
        ">t3\nACGTTCGTACGT\n>t4\nACGTACGTTCGT\n",
        encoding="utf-8",
    )
    csv_rows = ["gene_present,age,lineage,outcome"]
    for i in range(20):
        gene = 1 if i < 10 else 0
        outcome = 1 if (i < 8 or i in {10, 13}) else 0
        csv_rows.append(f"{gene},{20 + i},{1 if i % 4 == 0 else 0},{outcome}")
    (tmp_path / "cohort.csv").write_text("\n".join(csv_rows) + "\n", encoding="utf-8")
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
    assert "投稿包历史" in body
    assert "生成新投稿包" in body
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


def test_cohort_builder_preview_and_create(web):
    client, _, study_id, _ = web
    page = client.get(f"/research/studies/{study_id}/cohorts/builder")
    assert page.status_code == 200
    assert "Cohort builder" in page.text
    assert "run-1" in page.text
    assert "S00" in page.text
    preview = client.post(
        f"/research/studies/{study_id}/cohorts/builder",
        data={
            "name": "builder-cohort",
            "rules": "{}",
            "member": ["run-1|S00", "run-1|S01"],
            "action": "preview",
        },
    )
    assert preview.status_code == 200
    assert "预检结果" in preview.text
    assert "通过" in preview.text
    created = client.post(
        f"/research/studies/{study_id}/cohorts/builder",
        data={
            "name": "builder-cohort",
            "rules": "{}",
            "member": ["run-1|S00", "run-1|S01"],
            "action": "create",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    study_page = client.get(f"/research/studies/{study_id}").text
    assert "builder-cohort" in study_page


def test_cohort_builder_blocks_duplicates(web):
    client, _, study_id, _ = web
    duplicate = client.post(
        f"/research/studies/{study_id}/cohorts/builder",
        data={
            "name": "dup",
            "rules": "{}",
            "member": ["run-1|S00", "run-1|S00"],
            "action": "create",
        },
    )
    assert duplicate.status_code == 200
    assert "预检未通过" in duplicate.text
    assert "S00" in duplicate.text


def test_cohort_builder_requires_members(web):
    client, _, study_id, _ = web
    response = client.post(
        f"/research/studies/{study_id}/cohorts/builder",
        data={"name": "empty", "rules": "{}", "member": [], "action": "preview"},
    )
    assert response.status_code == 200
    assert "至少选择一个样本" in response.text


def test_phylo_web_profile_plan_xml(web):
    client, _, _, home = web
    assert client.get("/research/phylo").status_code == 200
    alignment = str(home / "alignment.fasta")
    profile = client.post(
        "/research/phylo",
        data={"alignment": alignment, "goal": "bayesian", "action": "profile"},
    )
    assert profile.status_code == 200
    assert "Alignment profile" in profile.text
    plan = client.post(
        "/research/phylo",
        data={"alignment": alignment, "goal": "bayesian", "action": "plan"},
    )
    assert plan.status_code == 200
    assert "PhyloPlan" in plan.text
    xml = client.post(
        "/research/phylo",
        data={"alignment": alignment, "goal": "bayesian", "action": "xml"},
    )
    assert xml.status_code == 200
    assert "BEAST2 XML" in xml.text
    assert "/research/phylo/download/" in xml.text
    iqtree = client.post(
        "/research/phylo",
        data={"alignment": alignment, "goal": "ml", "action": "iqtree"},
    )
    assert iqtree.status_code == 200
    assert "iqtree2" in iqtree.text


def test_phylo_web_invalid_alignment(web):
    client, _, _, home = web
    response = client.post(
        "/research/phylo",
        data={"alignment": str(home / "missing.fasta"), "action": "profile"},
    )
    assert response.status_code == 200
    assert "alignment not found" in response.text


def test_stats_web_logistic(web):
    client, _, _, home = web
    assert client.get("/research/stats").status_code == 200
    response = client.post(
        "/research/stats",
        data={
            "data_path": str(home / "cohort.csv"),
            "outcome": "outcome",
            "predictors": "gene_present,age,lineage",
        },
    )
    assert response.status_code == 200
    assert "结果" in response.text
    assert "gene_present" in response.text
    assert "converged=True" in response.text


def test_stats_web_invalid_table(web):
    client, _, _, home = web
    response = client.post(
        "/research/stats",
        data={
            "data_path": str(home / "missing.csv"),
            "outcome": "outcome",
            "predictors": "gene_present",
        },
    )
    assert response.status_code == 200
    assert "table not found" in response.text


def test_figure_draft_upload_feedback_finalize(web):
    client, session_id, _, home = web
    upload = client.post(
        f"/research/{session_id}/drafts",
        files={
            "file": (
                "draft.svg",
                b"<svg xmlns='http://www.w3.org/2000/svg'><text>draft</text></svg>",
                "image/svg+xml",
            )
        },
        data={"note": "web draft"},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    page = client.get(f"/research/{session_id}").text
    assert "Figure 迭代" in page
    assert "web draft" in page
    drafts = ResearchService(home).list_drafts(session_id)
    draft = next(item for item in drafts if item.note == "web draft")
    feedback = client.post(
        f"/research/drafts/{draft.draft_id}/feedback",
        data={"feedback": "colorblind palette"},
        follow_redirects=False,
    )
    assert feedback.status_code == 303
    assert "colorblind palette" in client.get(f"/research/{session_id}").text
    finalize = client.post(
        f"/research/drafts/{draft.draft_id}/finalize",
        data={"recipe_id": "custom", "code_path": ""},
        follow_redirects=False,
    )
    assert finalize.status_code == 303
    assert ResearchService(home).get_draft(draft.draft_id).status.value == "final"


def test_figure_draft_rejects_unsupported_type(web):
    client, session_id, _, _ = web
    response = client.post(
        f"/research/{session_id}/drafts",
        files={"file": ("draft.txt", b"not a figure", "text/plain")},
        data={"note": "bad"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_package_history_and_detail(web):
    client, _, study_id, _ = web
    history = client.get(f"/research/studies/{study_id}/packages")
    assert history.status_code == 200
    assert "投稿包历史" in history.text
    build = client.post(
        f"/research/studies/{study_id}/packages",
        data={"label": "history smoke"},
        follow_redirects=False,
    )
    assert build.status_code == 303
    location = build.headers["location"]
    detail = client.get(location)
    assert detail.status_code == 200
    assert "history smoke" in detail.text
    package_id = location.rsplit("/", 1)[-1]
    archive = client.get(f"/research/packages/{package_id}/download.zip")
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert client.get(f"/research/studies/{study_id}").text.count(package_id) >= 1


def test_markdown_rendered_on_session(web):
    client, session_id, _, _ = web
    page = client.get(f"/research/{session_id}").text
    assert '<div class="markdown">' in page
    assert "<table>" in page or "<h1>" in page


def test_checklist_edit_and_sign(web):
    client, _, study_id, home = web
    base = ChecklistService(home).base(study_id)
    data = {
        f"status:{item.item_id}": "partial" for item in base.items
    }
    data["note"] = "reviewed in web"
    page = client.get(f"/research/studies/{study_id}/checklist")
    assert page.status_code == 200
    assert "STROBE checklist" in page.text
    saved = client.post(
        f"/research/studies/{study_id}/checklist",
        data={**data, "action": "save"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert ChecklistService(home).get_review(study_id).status.value == "draft"
    signed = client.post(
        f"/research/studies/{study_id}/checklist",
        data={**data, "action": "sign"},
        follow_redirects=False,
    )
    assert signed.status_code == 303
    review = ChecklistService(home).get_review(study_id)
    assert review.status.value == "signed"
    assert review.reviewed_by == "web"
    assert "signed" in client.get(f"/research/studies/{study_id}").text


def test_evidence_graph_on_study_and_session(web):
    client, session_id, study_id, _ = web
    study_page = client.get(f"/research/studies/{study_id}").text
    assert "证据链" in study_page
    assert "PART_OF" in study_page
    session_page = client.get(f"/research/{session_id}").text
    assert "证据链" in session_page
    assert "GENERATED_BY" in session_page


def test_analysis_result_saved_to_study(web):
    client, _, study_id, home = web
    response = client.post(
        "/research/stats",
        data={
            "data_path": str(home / "cohort.csv"),
            "outcome": "outcome",
            "predictors": "gene_present,age,lineage",
            "study_id": study_id,
        },
    )
    assert response.status_code == 200
    assert "已保存分析" in response.text
    analyses = client.get(f"/research/studies/{study_id}/analyses")
    assert analyses.status_code == 200
    assert "分析结果" in analyses.text
    import re

    match = re.search(r"/research/analyses/(ana-[a-f0-9]+)", analyses.text)
    assert match is not None
    detail = client.get(f"/research/analyses/{match.group(1)}")
    assert detail.status_code == 200
    assert "result sha256" in detail.text
    assert "gene_present" in detail.text


def test_phylo_analysis_saved_to_study(web):
    client, _, study_id, home = web
    response = client.post(
        "/research/phylo",
        data={
            "alignment": str(home / "alignment.fasta"),
            "goal": "bayesian",
            "action": "save",
            "study_id": study_id,
        },
    )
    assert response.status_code == 200
    assert "已保存分析" in response.text
    analyses = client.get(f"/research/studies/{study_id}/analyses").text
    assert "phylo" in analyses


def test_package_page_shows_supplementary_analyses(web):
    client, _, study_id, home = web
    ResearchAnalysisService(home).save(
        study_id, "logistic", {"n": 20}, title="web supp", actor="t"
    )
    build = client.post(
        f"/research/studies/{study_id}/packages",
        data={"label": "supp"},
        follow_redirects=False,
    )
    assert build.status_code == 303
    detail = client.get(build.headers["location"]).text
    assert "Supplementary analyses" in detail
    assert "web supp" in detail
