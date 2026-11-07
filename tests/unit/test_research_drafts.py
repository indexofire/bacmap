"""Figure draft lifecycle: upload record, feedback, finalize, reject."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.research.models import CreateSessionRequest, FigureDraftStatus, ResearchProfile
from bacmap.research.service import ResearchService
from bacmap.store import runs
from bacmap.store.genome_object_service import ensure_gom_schema
from bacmap.store.lab_results import LabResultService


def _home(tmp_path: Path) -> Path:
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


@pytest.fixture
def session(tmp_path: Path):
    home = _home(tmp_path)
    view = ResearchService(home).create_session(
        CreateSessionRequest(
            run_id="run-1",
            gene="blaKPC-33",
            test_name="meropenem",
            profile=ResearchProfile.RESEARCH,
        ),
        actor="t",
    )
    return home, view.session.session_id


def _draft_file(tmp_path: Path, name: str = "draft.svg") -> Path:
    path = tmp_path / name
    path.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>",
        encoding="utf-8",
    )
    return path


def test_create_list_feedback_and_finalize(session, tmp_path: Path):
    home, session_id = session
    svc = ResearchService(home)
    draft = svc.create_draft(
        session_id, _draft_file(tmp_path), note="first pass", actor="web"
    )
    assert draft.status is FigureDraftStatus.DRAFT
    assert [item.draft_id for item in svc.list_drafts(session_id)] == [draft.draft_id]
    updated = svc.add_draft_feedback(
        draft.draft_id, "use colorblind palette", actor="web"
    )
    assert updated.feedback == "use colorblind palette"
    artifact = svc.finalize_draft(draft.draft_id, recipe_id="custom", actor="web")
    assert artifact.recipe_id == "custom"
    assert Path(artifact.output).is_file()
    final = svc.get_draft(draft.draft_id)
    assert final.status is FigureDraftStatus.FINAL
    artifacts = {item.kind.value for item in svc.get_session(session_id).artifacts}
    assert "figure_custom" in artifacts


def test_reject_draft(session, tmp_path: Path):
    home, session_id = session
    svc = ResearchService(home)
    draft = svc.create_draft(session_id, _draft_file(tmp_path), actor="web")
    rejected = svc.reject_draft(draft.draft_id, note="wrong layout", actor="web")
    assert rejected.status is FigureDraftStatus.REJECTED
    with pytest.raises(Exception, match="already rejected"):
        svc.finalize_draft(draft.draft_id, actor="web")


def test_finalize_twice_conflicts(session, tmp_path: Path):
    home, session_id = session
    svc = ResearchService(home)
    draft = svc.create_draft(session_id, _draft_file(tmp_path), actor="web")
    svc.finalize_draft(draft.draft_id, actor="web")
    with pytest.raises(Exception, match="already final"):
        svc.finalize_draft(draft.draft_id, actor="web")


def test_unknown_draft(session):
    home, _ = session
    with pytest.raises(Exception, match="no such figure draft"):
        ResearchService(home).get_draft("fd-nope")
