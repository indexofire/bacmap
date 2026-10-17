"""bio_compare_runs 运行比较测试（ADR-18：差异归因 + 不可复现告警）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bacmap.store import runs
from bacmap.store.genome_object_service import (
    GenomeObject,
    GenomeObjectService,
    ObjectType,
)
from bacmap.tools import services


def _workflow_dir(tmp_path: Path) -> Path:
    wf = tmp_path / "wf"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 8\niqtree_seed: 42\n")
    return wf


def _make_run(db: Path, wf: Path, sample: str, **overrides) -> runs.AnalysisRun:
    return runs.create_run(
        workflow="bacmap",
        workflow_dir=wf,
        strain_ids=[sample],
        overrides=overrides or None,
        db_path=db,
        task_id="t",
    )


def _add_summary(gom_db: Path, sample: str, run_id: str, steps: dict) -> None:
    with GenomeObjectService(gom_db) as gos:
        gos.create(
            GenomeObject(
                object_id=f"{sample}-{run_id}",
                object_type=ObjectType.ANALYSIS,
                version=1,
                schema_version="1.0.0",
                created_at=datetime.now(UTC),
                created_by="test",
                payload={
                    "analysis_type": "sample_analysis",
                    "sample_id": sample,
                    "run_id": run_id,
                    "summary": {"sample_id": sample, "steps": steps},
                },
                pipeline_version="test",
                tool_versions={"workflow": "test"},
                strain_id=sample,
            )
        )


class TestCompareRunsProvenance:
    def test_identical_provenance(self, tmp_path: Path):
        a = runs.AnalysisRun(run_id="a", workflow="bacmap")
        b = runs.AnalysisRun(run_id="b", workflow="bacmap")
        out = runs.compare_runs(a, b)
        assert out["same_provenance"] is True
        assert out["diffs"] == []

    def test_parameter_diff_attributed(self, tmp_path: Path):
        a = runs.AnalysisRun(run_id="a", workflow="bacmap", resolved_config={"threads": 4})
        b = runs.AnalysisRun(run_id="b", workflow="bacmap", resolved_config={"threads": 8})
        out = runs.compare_runs(a, b)
        assert out["same_provenance"] is False
        assert "parameters" in out["changed_categories"]
        assert any(d["field"] == "resolved_config" for d in out["diffs"])


class TestCompareRunsTool:
    def _setup(self, tmp_path: Path, monkeypatch, *, diff_prov: bool, diff_result: bool):
        db = tmp_path / "runs.sqlite"
        gom = tmp_path / "gom.sqlite"
        wf = _workflow_dir(tmp_path)
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {"snakemake": "9"})
        a = _make_run(db, wf, "SAM-1", threads=4)
        b = _make_run(db, wf, "SAM-1", threads=8 if diff_prov else 4)
        _add_summary(gom, "SAM-1", a.run_id, {"species": {"verdict": "Salmonella"}})
        _add_summary(
            gom,
            "SAM-1",
            b.run_id,
            {"species": {"verdict": "E.coli" if diff_result else "Salmonella"}},
        )
        monkeypatch.setattr(services, "_RUNS_DB", db)
        monkeypatch.setattr(services, "_GOM_DB", gom)
        return a, b

    def test_not_reproducible(self, tmp_path, monkeypatch):
        a, b = self._setup(tmp_path, monkeypatch, diff_prov=False, diff_result=True)
        out = json.loads(
            services.compare_runs({"sample_id": "SAM-1", "run_a": a.run_id, "run_b": b.run_id})
        )
        assert out["verdict"] == "NOT_REPRODUCIBLE"
        assert out["same_provenance"] is True
        assert out["result_change_count"] >= 1

    def test_identical(self, tmp_path, monkeypatch):
        a, b = self._setup(tmp_path, monkeypatch, diff_prov=False, diff_result=False)
        out = json.loads(
            services.compare_runs({"sample_id": "SAM-1", "run_a": a.run_id, "run_b": b.run_id})
        )
        assert out["verdict"] == "IDENTICAL"

    def test_diff_attributed(self, tmp_path, monkeypatch):
        a, b = self._setup(tmp_path, monkeypatch, diff_prov=True, diff_result=True)
        out = json.loads(
            services.compare_runs({"sample_id": "SAM-1", "run_a": a.run_id, "run_b": b.run_id})
        )
        assert out["verdict"] == "DIFF_ATTRIBUTED"
        assert "parameters" in out["changed_categories"]

    def test_missing_run_errors(self, tmp_path, monkeypatch):
        a, _ = self._setup(tmp_path, monkeypatch, diff_prov=False, diff_result=False)
        out = json.loads(
            services.compare_runs({"sample_id": "SAM-1", "run_a": a.run_id, "run_b": "nope"})
        )
        assert "error" in out

    def test_required_fields(self):
        out = json.loads(services.compare_runs({"sample_id": "SAM-1"}))
        assert "error" in out

    def test_invalid_sample_id(self):
        out = json.loads(
            services.compare_runs({"sample_id": "../x", "run_a": "a", "run_b": "b"})
        )
        assert "error" in out
