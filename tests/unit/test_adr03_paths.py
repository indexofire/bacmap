"""ADR-03 路径合规回归：数据类路径一律来自 BACMAP_HOME，不由源码位置推导。

背景（审计发现）：tools/_common.py 曾暴露 `_PROJECT_ROOT = parents[2]`（实为
`src/`），被 bio_list_samples / bio_diagnose / bio_cgmlst 用于拼接 samples.tsv、
日志目录、cgmlst 参考库——standalone 部署下指向不存在的位置。本模块锁死修复。
"""

from __future__ import annotations

from pathlib import Path

from bacmap import config
from bacmap.store import runs
from bacmap.tools import pipeline as tools_pipeline
from bacmap.tools import services as tools_services


class TestConfigDerivedPaths:
    def test_deployed_workflows_dir_under_bacmap_home(self):
        assert config.DEPLOYED_WORKFLOWS_DIR == config.WORKFLOWS_DIR / "bacmap"
        # 不得落在源码树内（src/）
        assert "src" not in config.DEPLOYED_WORKFLOWS_DIR.parts

    def test_pipeline_uses_config_deployed_dir(self):
        assert tools_pipeline._DEPLOYED_WORKFLOWS_DIR == config.DEPLOYED_WORKFLOWS_DIR

    def test_services_data_dir_from_config(self):
        assert tools_services._DATA_DIR == config.DATA_DIR
        assert tools_services._DEPLOYED_WORKFLOWS_DIR == config.DEPLOYED_WORKFLOWS_DIR

    def test_common_no_project_root(self):
        from bacmap.tools import _common

        assert not hasattr(_common, "_PROJECT_ROOT")

    def test_services_has_no_scripts_dir(self):
        assert not hasattr(tools_services, "_scripts_dir")


class TestEnvLockPath:
    def test_explicit_env_var_wins(self, tmp_path: Path, monkeypatch):
        lock = tmp_path / "pixi.lock"
        lock.write_text("x")
        monkeypatch.setenv("BACMAP_ENV_LOCK", str(lock))
        assert config.env_lock_path() == lock.resolve()

    def test_pixi_project_root_fallback(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("BACMAP_ENV_LOCK", raising=False)
        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path / "home")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "pixi.lock").write_text("x")
        monkeypatch.setenv("PIXI_PROJECT_ROOT", str(proj))
        assert config.env_lock_path() == proj / "pixi.lock"

    def test_none_when_absent(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("BACMAP_ENV_LOCK", raising=False)
        monkeypatch.delenv("PIXI_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path / "empty")
        assert config.env_lock_path() is None


class TestRunsUsesEnvLock:
    def test_create_run_records_env_lock(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
        lock = tmp_path / "pixi.lock"
        lock.write_text("lock-content")
        # create_run 内部 `from bacmap.config import env_lock_path`，故 patch config 侧
        monkeypatch.setattr(config, "env_lock_path", lambda: lock)

        wf = tmp_path / "wf"
        (wf / "config").mkdir(parents=True)
        (wf / "config" / "config.yaml").write_text("threads: 2\n")
        run = runs.create_run(
            workflow="bacmap", workflow_dir=wf, strain_ids=[], db_path=tmp_path / "r.sqlite"
        )
        assert run.env_lock_sha256 == runs.file_sha256(lock)


class TestDataDirResolution:
    """DATA_DIR 优先级：env > config.toml(paths.data_dir) > $BACMAP_HOME/data（含展开/resolve）。"""

    def test_env_wins_over_toml(self, tmp_path: Path):
        env = tmp_path / "envdir"
        toml_dir = tmp_path / "tomldir"
        got = config._resolve_data_dir(tmp_path, {"data_dir": str(toml_dir)}, str(env))
        assert got == env.resolve()

    def test_toml_fallback_resolved(self, tmp_path: Path):
        toml_dir = tmp_path / "tomldir"
        assert config._resolve_data_dir(tmp_path, {"data_dir": str(toml_dir)}, None) == (
            toml_dir.resolve()
        )

    def test_blank_toml_falls_back_to_home_data(self, tmp_path: Path):
        assert config._resolve_data_dir(tmp_path, {"data_dir": "   "}, None) == tmp_path / "data"

    def test_default_home_data(self, tmp_path: Path):
        assert config._resolve_data_dir(tmp_path, {}, None) == tmp_path / "data"


class TestCheckm2EnvName:
    """文档写 CHECKM2_DB；代码须读同名（回归：曾误读 CHECKM2DB，文档变量失效）。"""

    def test_checkm2_db_env_name_aligned(self, tmp_path: Path):
        import os
        import subprocess
        import sys

        env = {**os.environ, "CHECKM2_DB": str(tmp_path / "c2")}
        env.pop("CHECKM2DB", None)
        out = subprocess.run(
            [sys.executable, "-c", "from bacmap import config; print(config.CHECKM2_DB)"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == str((tmp_path / "c2").resolve())
