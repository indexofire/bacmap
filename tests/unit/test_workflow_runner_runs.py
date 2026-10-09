"""WorkflowRunner 与运行记录的单元测试（子进程全部 mock/临时目录）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bacmap.store import runs
from bacmap.workflow import runner as wf_runner


@pytest.fixture
def workflow_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workflow"
    (d / "config").mkdir(parents=True)
    (d / "config" / "config.yaml").write_text("threads: 8\niqtree_seed: 42\n")
    (d / "Snakefile").write_text("# fake\n")
    return d


class TestResolveConfig:
    def test_merge_override(self, workflow_dir: Path):
        cfg = runs.resolve_config(workflow_dir, {"threads": 16, "extra": "x"})
        assert cfg["threads"] == 16
        assert cfg["iqtree_seed"] == 42
        assert cfg["extra"] == "x"

    def test_nested_dict_merge(self, workflow_dir: Path):
        (workflow_dir / "config" / "config.yaml").write_text(
            "tools:\n  fastp:\n    qualified_quality_phred: 20\n"
        )
        cfg = runs.resolve_config(
            workflow_dir, {"tools": {"fastp": {"qualified_quality_phred": 30}}}
        )
        assert cfg["tools"]["fastp"]["qualified_quality_phred"] == 30


class TestAnalysisRun:
    def test_create_and_finish(self, tmp_path: Path, workflow_dir: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {"snakemake": "9.27.0"})
        db = tmp_path / "runs.sqlite"
        run = runs.create_run(
            workflow="bacmap",
            workflow_dir=workflow_dir,
            strain_ids=["SAM-1"],
            overrides={"threads": 4},
            db_path=db,
            task_id="t-1",
        )
        assert run.config_sha256
        assert run.seeds == {"iqtree": 42}

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT run_id, workflow, seeds FROM analysis_runs").fetchone()
        conn.close()
        assert row[0] == run.run_id and row[1] == "bacmap"
        assert json.loads(row[2]) == {"iqtree": 42}

        runs.finish_run(run, db_path=db)
        conn = sqlite3.connect(db)
        fin = conn.execute(
            "SELECT finished_at FROM analysis_runs WHERE run_id=?", (run.run_id,)
        ).fetchone()
        conn.close()
        assert fin[0] is not None

    def test_manifest_roundtrip(self, tmp_path: Path, workflow_dir: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        db = tmp_path / "runs.sqlite"
        run = runs.create_run(
            workflow="bacmap", workflow_dir=workflow_dir, strain_ids=[], db_path=db
        )
        path = runs.write_manifest(run, tmp_path / "runroots")
        payload = json.loads(path.read_text())
        assert payload["run_id"] == run.run_id
        assert payload["manifest_sha256"] == run.manifest_sha256
        assert payload["workflow"] == "bacmap"

    def test_file_sha256_stable(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        assert runs.file_sha256(f) == runs.file_sha256(f)
        assert len(runs.file_sha256(f)) == 64


class TestDeploy:
    def test_deploy_rewrites_project_root_and_keeps_samples(self, tmp_path: Path, monkeypatch):
        pkg = tmp_path / "pkg_workflow"
        (pkg / "config").mkdir(parents=True)
        (pkg / "config" / "config.yaml").write_text('project_root: "../.."\n')
        (pkg / "Snakefile").write_text("#\n")
        home = tmp_path / "home"
        monkeypatch.setattr(wf_runner, "WORKFLOW_PKG_DIR", pkg)
        monkeypatch.setattr(wf_runner, "WORKFLOWS_DIR", home / "workflows")
        monkeypatch.setattr(wf_runner, "BACMAP_HOME", home)

        d1 = wf_runner.deploy()
        assert 'project_root: "' in (d1 / "config" / "config.yaml").read_text()
        assert "../.." not in (d1 / "config" / "config.yaml").read_text()

        (d1 / "config" / "samples.tsv").write_text("user\tdata\n")
        wf_runner.deploy(force=True)
        assert (d1 / "config" / "samples.tsv").read_text() == "user\tdata\n"

    def test_idempotent_when_unchanged(self, tmp_path: Path, monkeypatch):
        pkg = tmp_path / "pkg_workflow"
        (pkg / "config").mkdir(parents=True)
        (pkg / "config" / "config.yaml").write_text('project_root: "../.."\n')
        monkeypatch.setattr(wf_runner, "WORKFLOW_PKG_DIR", pkg)
        monkeypatch.setattr(wf_runner, "WORKFLOWS_DIR", tmp_path / "workflows")
        monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path)
        d1 = wf_runner.deploy()
        stamp_before = (d1 / ".bacmap_workflow_sha").read_text()
        wf_runner.deploy()
        assert (d1 / ".bacmap_workflow_sha").read_text() == stamp_before


class TestRunnerSubprocess:
    def test_run_builds_correct_command(self, tmp_path: Path, monkeypatch):
        recorded: dict = {}

        def fake_run(cmd, cwd=None, timeout=None, text=None, capture_output=None, env=None):  # noqa: ARG001
            recorded["cmd"] = cmd
            recorded["cwd"] = cwd

            class P:
                returncode = 0
                stdout = ""
                stderr = ""
            return P()

        monkeypatch.setattr(wf_runner.subprocess, "run", fake_run)
        r = wf_runner.WorkflowRunner(deployed_dir=tmp_path)
        r.run(["results/S/report/s.json"], cores=4, config_overrides={"threads": "4"})
        cmd = recorded["cmd"]
        assert cmd[0] == "snakemake" and cmd[1] == "-s"
        assert "--cores" in cmd and "4" in cmd
        assert "--rerun-incomplete" in cmd
        assert cmd[-1] == "results/S/report/s.json"
        assert recorded["cwd"] == str(tmp_path)
