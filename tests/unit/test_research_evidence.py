"""Evidence graph auto-linking across research objects."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.research.checklist import ChecklistService
from bacmap.research.models import CreateSessionRequest, ResearchProfile
from bacmap.research.packages import ResearchPackageService
from bacmap.research.service import ResearchObjectService, ResearchService
from bacmap.research.store import ResearchObjectStore
from bacmap.store import runs
from bacmap.store.genome_object_service import ensure_gom_schema
from bacmap.store.lab_results import LabResultService


@pytest.fixture
def home(tmp_path: Path) -> Path:
    wf = tmp_path / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 2\niqu_tree_seed: 42\n")
    strains = [f"S{i:02d}" for i in range(8)]
    run = runs.create_run(
        "bacmap", wf, strains, db_path=tmp_path / "runs.sqlite", task_id="task-1"
    )
    with sqlite3.connect(tmp_path / "runs.sqlite") as conn:
        conn.execute(
            "UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", ("run-1", run.run_id)
        )
    ensure_gom_schema(tmp_path / "gom.sqlite")
    with sqlite3.connect(tmp_path / "gom.sqlite") as conn:
        for i, sid in enumerate(strains):
            if i < 4:
                conn.execute(
                    "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                    " VALUES (?,?,?)",
                    (sid, "blaKPC-33", "card"),
                )
    with LabResultService(tmp_path / "data" / "bacmap.sqlite") as svc:
        for i, sid in enumerate(strains):
            svc.add(
                sid,
                "mic",
                "meropenem",
                "0.25",
                interpretation="R" if i < 3 else "S",
            )
    return tmp_path


def test_auto_edges_cover_research_objects(home: Path):
    objects = ResearchObjectService(home)
    study = objects.create_study("Evidence question", "KPN", 2, "t")
    cohort = objects.create_cohort(
        study.study_id, [{"isolate_id": "S00", "run_id": "run-1"}], name="ev", actor="t"
    )
    objects.freeze_cohort(cohort.cohort_id, "t")
    plan = objects.create_plan(
        study.study_id, cohort.cohort_id, {"run_id": "run-1"}, "t"
    )
    objects.freeze_plan(plan.plan_id, "t")
    objects.create_claim(
        study.study_id, "association", "gene is associated", "E2", {}, "t"
    )
    objects.record_experiment(plan.plan_id, "success", ["run-1"], {"n": 8}, actor="t")
    view = ResearchService(home).create_session(
        CreateSessionRequest(
            run_id="run-1",
            gene="blaKPC-33",
            test_name="meropenem",
            profile=ResearchProfile.RESEARCH,
            study_id=study.study_id,
            cohort_id=cohort.cohort_id,
            plan_id=plan.plan_id,
        ),
        actor="t",
    )
    ChecklistService(home).save(study.study_id, [], actor="t")
    ResearchPackageService(home).build(study.study_id, actor="t")

    with ResearchObjectStore(home) as store:
        study_edges = {edge.edge_type for edge in store.list_edges_for_id(study.study_id)}
        session_edges = {
            edge.edge_type for edge in store.list_edges_for_id(view.session.session_id)
        }
    assert {
        "COHORT_OF",
        "PLAN_OF",
        "CLAIM_OF",
        "EXPERIMENT_OF",
        "PART_OF",
        "CHECKLIST_OF",
        "PACKAGE_OF",
    } <= study_edges
    assert {"PART_OF", "USES_COHORT", "GENERATED_BY"} <= session_edges


def test_ensure_edge_is_idempotent(home: Path):
    with ResearchObjectStore(home) as store:
        study = store.create_study("Idempotent", "", 2, "t")
        store.ensure_edge("x", "1", "LINKS", "study", study.study_id, "r", "t")
        store.ensure_edge("x", "1", "LINKS", "study", study.study_id, "r", "t")
        edges = store.list_edges_for_id(study.study_id)
    assert len([edge for edge in edges if edge.edge_type == "LINKS"]) == 1
