"""bio_db_setup / bio_db_status Hermes tools."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.tools import services as tool_services  # noqa: E402


class TestDbSetupList:
    def test_lists_all_tiers_with_readiness(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path)
        out = tool_services.db_setup({"action": "list"})
        for tier in ("instant", "mini", "sourmash", "full", "standard"):
            assert tier in out

    def test_installed_marked(self, monkeypatch, tmp_path):
        (tmp_path / "manifests").mkdir(parents=True)
        (tmp_path / "manifests" / "mash_refseq.json").write_text("{}")
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path)
        out = tool_services.db_setup({"action": "list"})
        assert "✅已装" in out

    def test_unknown_tier_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path)
        out = tool_services.db_setup({"action": "run", "tier": "mega"})
        assert "未知档位" in out


class TestDbSetupRun:
    def test_spawns_background_process_with_log(self, monkeypatch, tmp_path):
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "download_db_mash_refseq.py").write_text("#!/usr/bin/env python3\n")
        captured = {}

        class _P:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                captured["kw"] = kw

        import subprocess as _sp

        monkeypatch.setattr(_sp, "Popen", _P)
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path / "db")
        monkeypatch.setattr(tool_services, "_scripts_dir", lambda: scripts)
        out = tool_services.db_setup({"action": "run", "tier": "instant"})
        assert "后台" in out
        assert "setup_databases.py" in captured["cmd"][1]
        assert "--tier" in captured["cmd"] and "instant" in captured["cmd"]
        assert captured["kw"]["start_new_session"] is True
        assert (tmp_path / "db" / "setup.log").exists()

    def test_missing_script_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path)
        monkeypatch.setattr(tool_services, "_scripts_dir", lambda: tmp_path / "empty")
        out = tool_services.db_setup({"action": "run", "tier": "mini"})
        assert "脚本缺失" in out


class TestDbStatus:
    def test_no_databases(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path)
        out = tool_services.db_status({})
        assert "尚未安装" in out

    def test_manifest_and_log_tail(self, monkeypatch, tmp_path):
        (tmp_path / "manifests").mkdir()
        (tmp_path / "manifests" / "refseq_panel.json").write_text(
            '{"name": "refseq_panel", "n_genomes": 2495}'
        )
        (tmp_path / "setup.log").write_text("a\nb\nCompleted 100%\nEXIT=0\n")
        monkeypatch.setattr(tool_services, "_db_dir", lambda: tmp_path)
        out = tool_services.db_status({})
        assert "refseq_panel" in out and "2495" in out
        assert "EXIT=0" in out
