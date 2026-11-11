"""流式两阶段分析（v1.10.23）：prelim 先行、注释垫底、web 首屏可见。"""

from __future__ import annotations

import json
from pathlib import Path

from bacmap.interfaces.views import sample_detail


class TestSampleDetailPrelimFallback:
    def test_prelim_summary_served_when_final_missing(self, tmp_path: Path):
        base = tmp_path / "results" / "S1" / "report"
        base.mkdir(parents=True)
        (base / "S1_summary.prelim.json").write_text(
            json.dumps({"sample": "S1", "steps": {"annotation": {"status": "pending"}}}),
            encoding="utf-8",
        )
        detail = sample_detail(tmp_path, "S1")
        assert detail is not None
        assert detail["digest"]["prelim"] is True
        assert detail["digest"]["has_report"] is False
        assert detail["digest"]["has_prelim_report"] is False  # HTML 尚未生成
        assert detail["steps"]["annotation"]["status"] == "pending"

    def test_final_summary_wins_when_both_exist(self, tmp_path: Path):
        base = tmp_path / "results" / "S2" / "report"
        base.mkdir(parents=True)
        (base / "S2_summary.prelim.json").write_text('{"sample": "S2", "steps": {}}')
        (base / "S2_summary.json").write_text(
            json.dumps({"sample": "S2", "steps": {"annotation": {"status": "ok"}}})
        )
        detail = sample_detail(tmp_path, "S2")
        assert detail["digest"]["prelim"] is False
        assert detail["steps"]["annotation"]["status"] == "ok"

    def test_no_summaries_returns_none(self, tmp_path: Path):
        assert sample_detail(tmp_path, "S3") is None


class TestEngineTwoPhase:
    def test_prelim_targets_run_before_final(self, tmp_path, monkeypatch):
        """runner.run 收到的目标序列：先 prelim 后 final（注释天然垫底）。"""
        import bacmap.tasks.engine.dbos_engine as eng

        calls: list[list[str]] = []

        class FakeRunner:
            def __init__(self, *a, **k): ...

            def run(self, targets=None, cores=None, config_overrides=None, timeout=None):
                calls.append(list(targets or []))
                import types

                return types.SimpleNamespace(returncode=0, stderr="")

        monkeypatch.setattr("bacmap.workflow.runner.deploy", lambda: tmp_path, raising=True)
        monkeypatch.setattr("bacmap.store.results_layout.link_run_results", lambda *a, **k: None)
        monkeypatch.setattr("bacmap.store.results_layout.run_results_dir", lambda home, tid: tmp_path / "runs" / tid)
        monkeypatch.setattr(eng, "_progress", lambda *a, **k: None)
        monkeypatch.setattr(eng, "_clear_stale_snakemake_locks", lambda: False)
        monkeypatch.setattr("bacmap.workflow.runner.WorkflowRunner", FakeRunner)
        params = {"home": str(tmp_path), "samples": ["S1"], "task_id": "t1", "timeout": 60}
        result = eng._run_snakemake(params)
        assert result.returncode == 0
        assert len(calls) == 2
        assert calls[0] == [str(tmp_path / "runs/t1/S1/report/S1_summary.prelim.json")]
        assert calls[1] == [str(tmp_path / "runs/t1/S1/report/S1_summary.json")]
