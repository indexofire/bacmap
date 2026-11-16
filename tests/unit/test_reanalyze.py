"""partial reanalyze（v1.10.39）：base run 解析、硬链接快照与阶段目标。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bacmap.store import runs as runs_store
from bacmap.tasks.reanalyze import (
    ReanalyzeError,
    prepare_reanalysis,
    reanalysis_targets,
    resolve_base_run,
)


def _base_home(tmp_path: Path, sample: str = "S1") -> tuple[Path, str, str]:
    home = tmp_path / "home"
    wf = home / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 1\n")
    db = home / "runs.sqlite"
    run = runs_store.create_run(
        workflow="bacmap",
        workflow_dir=wf,
        strain_ids=[sample],
        db_path=db,
        task_id="base-task",
        refs_dir=tmp_path / "refs",
    )
    runs_store.finalize_run(run.run_id, db, home / "runs")
    base = home / "results" / "runs" / "base-task" / sample
    (base / "typing").mkdir(parents=True)
    (base / "typing" / "mlst.json").write_text("old-cgmlst")
    (base / "assembly").mkdir()
    (base / "assembly" / f"{sample}.fasta").write_text(">x\nACGT\n")
    (base / "report").mkdir()
    (base / "report" / f"{sample}_summary.json").write_text('{"old": true}')
    (base / "report" / f"{sample}_report.html").write_text("old report")
    return home, run.run_id, "base-task"


def test_resolve_base_run_latest(tmp_path: Path):
    home, run_id, task_id = _base_home(tmp_path)
    resolved = resolve_base_run(home, ["S1"])
    assert resolved["run_id"] == run_id
    assert resolved["task_id"] == task_id


def test_resolve_base_run_rejects_missing_sample(tmp_path: Path):
    home, _, _ = _base_home(tmp_path)
    with pytest.raises(ReanalyzeError, match="no successful base run"):
        resolve_base_run(home, ["S2"])


def test_prepare_reanalysis_hardlinks_and_invalidates_targets(tmp_path: Path):
    home, _, _ = _base_home(tmp_path)
    result = prepare_reanalysis(home, ["S1"], ["mlst"], "new-task")
    new_dir = result["run_dir"]
    base_dir = home / "results" / "runs" / "base-task" / "S1"
    # unchanged artifacts are hardlinks: same inode, base not duplicated
    assert os.stat(new_dir / "S1" / "assembly" / "S1.fasta").st_ino == os.stat(
        base_dir / "assembly" / "S1.fasta"
    ).st_ino
    # selected stage + summary/report are invalidated -> rerun
    assert not (new_dir / "S1" / "typing" / "mlst.json").exists()
    assert not (new_dir / "S1" / "report" / "S1_summary.json").exists()
    assert not (new_dir / "S1" / "report" / "S1_report.html").exists()
    # base run untouched
    assert (base_dir / "typing" / "mlst.json").read_text() == "old-cgmlst"


def test_prepare_annotation_removes_whole_annotation_tree(tmp_path: Path):
    home, _, _ = _base_home(tmp_path)
    base = home / "results" / "runs" / "base-task" / "S1" / "annotation"
    base.mkdir()
    (base / "annotation.json").write_text("{}")
    result = prepare_reanalysis(home, ["S1"], ["annotation"], "new-task")
    assert not (result["run_dir"] / "S1" / "annotation").exists()


def test_reanalysis_targets_include_stage_and_summary(tmp_path: Path):
    home, _, _ = _base_home(tmp_path)
    targets = reanalysis_targets(
        home / "results" / "runs" / "new", ["S1"], ["mlst"]
    )
    assert targets[-1].endswith("/S1/report/S1_summary.json")
    assert any(path.endswith("/S1/typing/mlst.json") for path in targets)


def test_create_run_records_reanalysis_provenance(tmp_path: Path):
    home, _, _ = _base_home(tmp_path)
    run = runs_store.create_run(
        workflow="bacmap",
        workflow_dir=home / "workflows" / "bacmap",
        strain_ids=["S1"],
        db_path=home / "runs.sqlite",
        task_id="new-task",
        refs_dir=tmp_path / "refs",
        base_run_id="base-run",
        reanalysis_steps=["mlst"],
    )
    loaded = runs_store.read_run(run.run_id, home / "runs.sqlite")
    assert loaded is not None
    assert loaded.base_run_id == "base-run"
    assert loaded.reanalysis_steps == ["mlst"]


def test_reanalyze_params_validates_stage_names():
    from bacmap.tasks.params import ReanalyzeParams

    task = ReanalyzeParams(samples=["S1"], steps=["mlst", "mlst"])
    assert task.steps == ["mlst"]
    with pytest.raises(ValueError, match="unknown reanalysis stage"):
        ReanalyzeParams(samples=["S1"], steps=["bogus"])


def test_reanalyze_is_plannable_and_registered():
    from pydantic import TypeAdapter

    from bacmap.tasks.engine import dbos_engine
    from bacmap.tasks.engine.task_engine import DbosTaskEngine
    from bacmap.tasks.params import PlannableTask
    from bacmap.tasks.spec import TaskType

    tasks = TypeAdapter(list[PlannableTask]).validate_python(
        [{"task_type": "reanalyze", "samples": ["S1"], "steps": ["mlst"]}]
    )
    assert tasks[0].task_type == "reanalyze"
    assert DbosTaskEngine._workflows()[TaskType.REANALYZE] is dbos_engine.reanalyze_workflow


def test_reanalyze_workflow_marks_new_run_provenance(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import dbos_engine as eng

    home, base_run_id, _ = _base_home(tmp_path)
    params = {
        "home": str(home),
        "task_id": "new-task",
        "samples": ["S1"],
        "steps": ["mlst"],
        "base_run_id": "",
    }
    monkeypatch.setattr(
        eng,
        "_step_run_reanalyze",
        lambda p, prepared: {
            "returncode": 0, "error": None, "started_at": None, "ended_at": None
        },
    )
    monkeypatch.setattr(eng, "_step_create_run", lambda p: {"run_id": "new-run"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, p: None)
    monkeypatch.setattr(eng, "_step_ingest_gom", lambda *a: "obj")
    monkeypatch.setattr(eng, "_step_gate", lambda *a: {"verdict": "pass"})
    monkeypatch.setattr(eng, "_step_record_gate", lambda *a: None)
    monkeypatch.setattr(eng, "_step_report", lambda *a: {})
    captured: dict = {}
    monkeypatch.setattr(eng, "_step_mark_terminal", lambda p, out: captured.update(p=p, out=out))
    out = eng.reanalyze_workflow(params)
    assert out["status"] == "SUCCEEDED"
    assert captured["p"]["base_run_id"] == base_run_id
    assert captured["p"]["steps"] == ["mlst"]
    assert captured["out"]["run_id"] == "new-run"
