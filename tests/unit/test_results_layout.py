"""run 级结果目录（v1.8.1，P2 方案 A）：物理数据在 runs/<task_id>，扁平路径为最新运行别名。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.store.results_layout import (
    link_run_results,
    migrate_flat_results,
    run_results_dir,
)


def _make_run(home: Path, task: str, sample: str) -> Path:
    rd = run_results_dir(home, task)
    rep = rd / sample / "report"
    rep.mkdir(parents=True)
    (rep / f"{sample}_summary.json").write_text("{}")
    (rd / "snp" / "SAL").mkdir(parents=True)
    (rd / "cgmlst" / "SAL").mkdir(parents=True)
    return rd


class TestLayout:
    def test_run_dir_under_runs(self, tmp_path: Path):
        assert run_results_dir(tmp_path, "t1") == tmp_path / "results" / "runs" / "t1"

    def test_links_latest_per_sample_and_cohorts(self, tmp_path: Path):
        rd = _make_run(tmp_path, "t1", "S1")
        link_run_results(tmp_path, "t1", ["S1"])
        assert (tmp_path / "results" / "S1").is_symlink()
        assert (tmp_path / "results" / "S1").resolve() == (rd / "S1").resolve()
        assert (tmp_path / "results" / "snp").is_symlink()
        assert (tmp_path / "results" / "cgmlst").is_symlink()

    def test_relink_switches_latest_but_keeps_old_run(self, tmp_path: Path):
        old = _make_run(tmp_path, "t1", "S1")
        link_run_results(tmp_path, "t1", ["S1"])
        new = _make_run(tmp_path, "t2", "S1")
        link_run_results(tmp_path, "t2", ["S1"])
        assert (tmp_path / "results" / "S1").resolve() == (new / "S1").resolve()
        assert (old / "S1" / "report" / "S1_summary.json").is_file()

    def test_refuses_to_replace_real_directory(self, tmp_path: Path):
        legacy = tmp_path / "results" / "S1" / "report"
        legacy.mkdir(parents=True)
        _make_run(tmp_path, "t1", "S1")
        with pytest.raises(RuntimeError, match="migrate"):
            link_run_results(tmp_path, "t1", ["S1"])


class TestMigration:
    def test_moves_flat_into_runs_and_links(self, tmp_path: Path):
        flat = tmp_path / "results" / "OLD" / "report"
        flat.mkdir(parents=True)
        (flat / "OLD_summary.json").write_text("{}")
        moved = migrate_flat_results(tmp_path)
        assert moved == 1
        target = tmp_path / "results" / "runs" / "legacy-OLD" / "OLD"
        assert (target / "report" / "OLD_summary.json").is_file()
        assert (tmp_path / "results" / "OLD").is_symlink()
        assert not (tmp_path / "results" / "OLD").is_dir() or (tmp_path / "results" / "OLD").is_symlink()

    def test_skips_runs_and_cohort_dirs(self, tmp_path: Path):
        _make_run(tmp_path, "t1", "S1")
        (tmp_path / "results" / "snp").mkdir(parents=True)
        (tmp_path / "results" / "cgmlst").mkdir(parents=True)
        assert migrate_flat_results(tmp_path) == 0


class TestEngineWritesRunScoped:
    def test_run_snakemake_targets_and_overrides(self, tmp_path: Path, monkeypatch):
        from types import SimpleNamespace

        import bacmap.tasks.engine.dbos_engine as eng

        seen: dict = {}

        class _Runner:
            def __init__(self, deployed_dir, timeout):
                pass

            def run(self, targets, cores, config_overrides=None):
                seen["targets"] = targets
                seen["overrides"] = config_overrides
                return SimpleNamespace(returncode=0, stderr="")

        import bacmap.workflow.runner as runner_mod

        monkeypatch.setattr(runner_mod, "deploy", lambda: tmp_path / "workflows" / "bacmap")
        monkeypatch.setattr(runner_mod, "WorkflowRunner", _Runner)
        params = {"home": str(tmp_path), "task_id": "t9", "samples": ["S1"], "cores": 2}
        # 预置运行产物，便于链接断言
        _make_run(tmp_path, "t9", "S1")
        eng._run_snakemake(params)
        assert seen["targets"] == [
            str(tmp_path / "results" / "runs" / "t9" / "S1" / "report" / "S1_summary.json")
        ]
        assert seen["overrides"] == {"workdir": "results/runs/t9"}
        assert (tmp_path / "results" / "S1").is_symlink()
