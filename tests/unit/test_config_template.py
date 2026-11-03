"""配置模板、配置路径解析与 ``bacmap config`` 命令。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import bacmap.config as config


@pytest.fixture(autouse=True)
def _clear_config_env(monkeypatch):
    monkeypatch.delenv("BACMAP_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


class TestConfigPath:
    def test_explicit_config_wins(self, monkeypatch, tmp_path: Path):
        explicit = tmp_path / "local.toml"
        explicit.write_text("[debug]\nenabled = true\n", encoding="utf-8")
        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path / "home")
        monkeypatch.setenv("BACMAP_CONFIG", str(explicit))
        assert config.config_path() == explicit
        assert config.load_config()["debug"]["enabled"] is True

    def test_home_config_beats_xdg(self, monkeypatch, tmp_path: Path):
        home = tmp_path / "home"
        xdg = tmp_path / "xdg"
        (home).mkdir()
        (xdg / "bacmap").mkdir(parents=True)
        (home / "config.toml").write_text("[debug]\nenabled = true\n", encoding="utf-8")
        (xdg / "bacmap" / "config.toml").write_text("[debug]\nenabled = false\n", encoding="utf-8")
        monkeypatch.setattr(config, "BACMAP_HOME", home)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        assert config.config_path() == home / "config.toml"

    def test_xdg_fallback_when_home_missing(self, monkeypatch, tmp_path: Path):
        home = tmp_path / "home"
        xdg = tmp_path / "xdg"
        (xdg / "bacmap").mkdir(parents=True)
        (xdg / "bacmap" / "config.toml").write_text("[mcp]\n", encoding="utf-8")
        monkeypatch.setattr(config, "BACMAP_HOME", home)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        assert config.config_path() == xdg / "bacmap" / "config.toml"

    def test_missing_config_targets_home(self, monkeypatch, tmp_path: Path):
        home = tmp_path / "home"
        monkeypatch.setattr(config, "BACMAP_HOME", home)
        assert config.config_path() == home / "config.toml"
        assert config.load_config() == {}

    def test_malformed_config_is_empty(self, tmp_path: Path):
        bad = tmp_path / "bad.toml"
        bad.write_text("not valid ==", encoding="utf-8")
        assert config.load_config(bad) == {}


class TestConfigCli:
    def _run(self, monkeypatch, capsys, argv: list[str]):
        from bacmap.interfaces.cli.main import main

        monkeypatch.setattr(sys, "argv", ["bacmap", *argv])
        main()
        return capsys.readouterr().out

    def test_init_home(self, monkeypatch, capsys, tmp_path: Path):
        out = self._run(
            monkeypatch, capsys,
            ["config", "init", "--home", str(tmp_path), "--json"],
        )
        data = json.loads(out)
        assert Path(data["created"]) == tmp_path / "config.toml"
        assert "[plans.auto_confirm]" in (tmp_path / "config.toml").read_text(encoding="utf-8")

    def test_init_refuses_overwrite(self, monkeypatch, capsys, tmp_path: Path):
        (tmp_path / "config.toml").write_text("existing\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="已存在"):
            self._run(monkeypatch, capsys, ["config", "init", "--home", str(tmp_path)])

    def test_init_user_uses_xdg(self, monkeypatch, capsys, tmp_path: Path):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        out = self._run(monkeypatch, capsys, ["config", "init", "--user", "--json"])
        created = Path(json.loads(out)["created"])
        assert created == xdg / "bacmap" / "config.toml"
        assert created.is_file()

    def test_init_project_is_gitignored(self, monkeypatch, capsys, tmp_path: Path):
        repo = Path(__file__).resolve().parents[2]
        monkeypatch.chdir(tmp_path)
        out = self._run(monkeypatch, capsys, ["config", "init", "--project", "--json"])
        created = Path(json.loads(out)["created"])
        assert created == tmp_path / "config.toml"
        assert "BACMAP_CONFIG" in out
        # .gitignore uses an anchored /config.toml pattern in the repository root.
        assert (repo / ".gitignore").read_text(encoding="utf-8").count("/config.toml") >= 1

    def test_path_reports_active_config(self, monkeypatch, capsys, tmp_path: Path):
        cfg = tmp_path / "custom.toml"
        cfg.write_text("[]", encoding="utf-8")
        monkeypatch.setenv("BACMAP_CONFIG", str(cfg))
        out = self._run(monkeypatch, capsys, ["config", "path", "--json"])
        data = json.loads(out)
        assert data["path"] == str(cfg)
        assert data["exists"] is True
        assert data["bacmap_config_env"] == str(cfg)
