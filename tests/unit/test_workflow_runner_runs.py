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
        # 回归：部署必须落在 monkeypatch 的 WORKFLOWS_DIR——绝不写穿真实 BACMAP_HOME
        # （旧实现用导入期常量 DEPLOYED_DIR，测试会把 user samples.tsv 覆盖成 "user\tdata"）。
        assert d1 == home / "workflows" / "bacmap"
        assert 'project_root: "' in (d1 / "config" / "config.yaml").read_text()
        assert "../.." not in (d1 / "config" / "config.yaml").read_text()

        (d1 / "config" / "samples.tsv").write_text("user\tdata\n")
        wf_runner.deploy(force=True)
        assert (d1 / "config" / "samples.tsv").read_text() == "user\tdata\n"

    def test_deploy_fails_without_project_root_marker(self, tmp_path: Path, monkeypatch):
        pkg = tmp_path / "pkg"
        (pkg / "config").mkdir(parents=True)
        (pkg / "config" / "config.yaml").write_text("threads: 8\n")
        monkeypatch.setattr(wf_runner, "WORKFLOW_PKG_DIR", pkg)
        monkeypatch.setattr(wf_runner, "WORKFLOWS_DIR", tmp_path / "workflows")
        monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path / "home")
        with pytest.raises(RuntimeError, match="project_root"):
            wf_runner.deploy()

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

        def fake_run(cmd, cwd=None, timeout=None, text=None, capture_output=None, env=None):
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


class TestFinalizeRunManifest:
    """ADR-18 §4.6：运行记录封存——表与 run_manifest.json 内容一致且带哈希。"""

    def test_finalize_writes_manifest_and_matches_table(
        self, tmp_path: Path, workflow_dir: Path, monkeypatch
    ):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {"snakemake": "9"})
        db = tmp_path / "runs.sqlite"
        run = runs.create_run(
            workflow="bacmap", workflow_dir=workflow_dir, strain_ids=[], db_path=db
        )
        out = runs.finalize_run(run.run_id, db, tmp_path / "runs")
        assert out is not None and out.finished_at is not None

        manifest = tmp_path / "runs" / run.run_id / "run_manifest.json"
        payload = json.loads(manifest.read_text())
        assert payload["manifest_sha256"] == out.manifest_sha256

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT manifest_sha256, finished_at FROM analysis_runs WHERE run_id=?",
            (run.run_id,),
        ).fetchone()
        conn.close()
        assert row[0] == out.manifest_sha256
        assert row[1] == out.finished_at.isoformat()

    def test_read_run_roundtrip(self, tmp_path: Path, workflow_dir: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        db = tmp_path / "runs.sqlite"
        run = runs.create_run(
            workflow="bacmap",
            workflow_dir=workflow_dir,
            strain_ids=["S1", "S2"],
            db_path=db,
            task_id="t-9",
        )
        loaded = runs.read_run(run.run_id, db)
        assert loaded is not None
        assert loaded.strain_ids == ["S1", "S2"]
        assert loaded.task_id == "t-9"

    def test_finalize_unknown_run_returns_none(self, tmp_path: Path):
        assert runs.finalize_run("no-such", tmp_path / "r.sqlite", tmp_path / "runs") is None


class TestRefDatabases:
    """ADR-20 → ADR-18：部署期登记的外部工具数据库写入运行记录。"""

    def test_missing_manifest_is_empty(self, tmp_path: Path):
        assert runs.load_ref_databases(tmp_path / "refs") == []

    def test_manifest_list_and_object_forms(self, tmp_path: Path):
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "manifest.json").write_text(
            json.dumps(
                {
                    "databases": [
                        {"name": "gapit:card", "version": "3.2.6", "checksum": "abc"},
                        {"name": "bad-no-version"},
                    ]
                }
            )
        )
        out = runs.load_ref_databases(refs)
        assert len(out) == 1
        assert out[0].name == "gapit:card" and out[0].version == "3.2.6"

        (refs / "manifest.json").write_text(
            json.dumps([{"name": "gmlst:senterica_2", "version": "2026-01"}])
        )
        out2 = runs.load_ref_databases(refs)
        assert out2[0].name == "gmlst:senterica_2" and out2[0].checksum == ""

    def test_invalid_json_is_empty(self, tmp_path: Path):
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "manifest.json").write_text("{not json")
        assert runs.load_ref_databases(refs) == []

    def test_create_run_records_ref_databases(
        self, tmp_path: Path, workflow_dir: Path, monkeypatch
    ):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "manifest.json").write_text(
            json.dumps({"databases": [{"name": "gapit:vfdb", "version": "2024"}]})
        )
        db = tmp_path / "r.sqlite"
        run = runs.create_run(
            workflow="bacmap",
            workflow_dir=workflow_dir,
            strain_ids=[],
            db_path=db,
            refs_dir=refs,
        )
        assert [r.name for r in run.ref_databases] == ["gapit:vfdb"]
        loaded = runs.read_run(run.run_id, db)
        assert loaded is not None
        assert [r.name for r in loaded.ref_databases] == ["gapit:vfdb"]


class TestSeedsAndNondeterminism:
    """ADR-18：随机种子与 nondeterministic_steps 由 config.yaml 声明。"""

    def test_seeds_extend_iqtree_default(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        wf = tmp_path / "wf"
        (wf / "config").mkdir(parents=True)
        (wf / "config" / "config.yaml").write_text(
            "iqtree_seed: 7\nseeds:\n  bwa: 11\n  samtools: 3\n"
        )
        run = runs.create_run(
            workflow="bacmap", workflow_dir=wf, strain_ids=[], db_path=tmp_path / "r.sqlite"
        )
        assert run.seeds == {"iqtree": 7, "bwa": 11, "samtools": 3}

    def test_nondeterministic_steps_declared(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        wf = tmp_path / "wf"
        (wf / "config").mkdir(parents=True)
        (wf / "config" / "config.yaml").write_text(
            "nondeterministic_steps:\n  - assembly_shovill\n  - \n"
        )
        run = runs.create_run(
            workflow="bacmap", workflow_dir=wf, strain_ids=[], db_path=tmp_path / "r.sqlite"
        )
        assert run.nondeterministic_steps == ["assembly_shovill"]

    def test_defaults_empty_nondeterministic(self, tmp_path: Path, workflow_dir: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        run = runs.create_run(
            workflow="bacmap",
            workflow_dir=workflow_dir,
            strain_ids=[],
            db_path=tmp_path / "r.sqlite",
        )
        assert run.nondeterministic_steps == []
        assert run.seeds == {"iqtree": 42}


class TestManifestSelfVerify:
    """ADR-18：run_manifest.json 的 manifest_sha256 是可复算的自校验哈希。"""

    def _finalized(self, tmp_path, workflow_dir, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda t: {})
        db = tmp_path / "r.sqlite"
        run = runs.create_run(
            workflow="bacmap", workflow_dir=workflow_dir, strain_ids=[], db_path=db
        )
        out = runs.finalize_run(run.run_id, db, tmp_path / "runs")
        assert out is not None
        return out

    def test_verify_after_write(self, tmp_path, workflow_dir, monkeypatch):
        out = self._finalized(tmp_path, workflow_dir, monkeypatch)
        assert runs.verify_run_manifest(out.run_id, tmp_path / "runs") is True

    def test_tamper_is_detected(self, tmp_path, workflow_dir, monkeypatch):
        out = self._finalized(tmp_path, workflow_dir, monkeypatch)
        path = tmp_path / "runs" / out.run_id / "run_manifest.json"
        payload = json.loads(path.read_text())
        payload["workflow"] = "tampered"
        path.write_text(json.dumps(payload))
        assert runs.verify_run_manifest(out.run_id, tmp_path / "runs") is False

    def test_missing_or_malformed_is_false(self, tmp_path):
        assert runs.verify_run_manifest("nope", tmp_path / "runs") is False
        d = tmp_path / "runs" / "x"
        d.mkdir(parents=True)
        (d / "run_manifest.json").write_text("{not json")
        assert runs.verify_run_manifest("x", tmp_path / "runs") is False

    def test_write_is_atomic_no_tmp_left(self, tmp_path, workflow_dir, monkeypatch):
        out = self._finalized(tmp_path, workflow_dir, monkeypatch)
        leftovers = list((tmp_path / "runs" / out.run_id).glob("*.tmp"))
        assert leftovers == []
