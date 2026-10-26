"""运维命令（v1.7.2）：doctor / backup / restore / events prune。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import bacmap.interfaces.cli.main as cli


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "config.toml").write_text("[mcp]\nallow_local_trusted = false\n")
    (tmp_path / "tasks.sqlite").write_text("")  # 由引擎迁移出真实表
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    DbosTaskEngine(tmp_path)
    from bacmap.tasks.engine.dbos_engine import shutdown_dbos

    shutdown_dbos()
    return tmp_path


class TestDoctor:
    def test_reports_checks_and_exit_code(self, home, capsys):
        cli.main(["doctor", "--home", str(home), "--json"])
        data = json.loads(capsys.readouterr().out)
        names = {c["name"] for c in data["checks"]}
        assert {"home", "database", "sandbox", "llm", "disk"} <= names
        assert data["home"] == str(home)
        assert isinstance(data["ok"], bool)

    def test_missing_home_fails(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["doctor", "--home", str(tmp_path / "nope"), "--json"])
        assert exc.value.code == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False


class TestBackupRestore:
    def test_roundtrip(self, home, tmp_path, capsys):
        from bacmap.tasks.engine.dbos_engine import DbosTaskEngine, shutdown_dbos
        from bacmap.tasks.spec import TaskType

        e = DbosTaskEngine(home)
        e.submit(TaskType.RECORD, {"kind": "metadata", "strain_id": "S1", "fields": {}}, "cli")
        shutdown_dbos()
        out = tmp_path / "backup.zip"
        cli.main(["backup", "--home", str(home), "--out", str(out)])
        assert out.is_file()
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert any(n.endswith("tasks.sqlite") for n in names)
        assert "config.toml" in names

        target = tmp_path / "restored"
        cli.main(["restore", "--from", str(out), "--home", str(target)])
        assert (target / "config.toml").is_file()
        from bacmap.tasks.events import EventLog

        assert len(EventLog(target / "tasks.sqlite").list()) >= 1

    def test_restore_refuses_non_empty_without_force(self, home, tmp_path):
        out = tmp_path / "b.zip"
        cli.main(["backup", "--home", str(home), "--out", str(out)])
        (home / "extra.txt").write_text("x")
        with pytest.raises(SystemExit, match="--force"):
            cli.main(["restore", "--from", str(out), "--home", str(home)])
        cli.main(["restore", "--from", str(out), "--home", str(home), "--force"])
        assert (home / "extra.txt").is_file()  # 非库文件不被删除

    def test_restore_rejects_zip_slip(self, home, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../evil.txt", "x")
        with pytest.raises(SystemExit, match="非法路径"):
            cli.main(["restore", "--from", str(bad), "--home", str(tmp_path / "out")])
        assert not (tmp_path / "evil.txt").exists()


class TestEventPrune:
    def test_prune_by_age(self, tmp_path, capsys):
        from bacmap.tasks.events import EventLog, EventType

        log = EventLog(tmp_path / "tasks.sqlite")
        log.append(EventType.TASK_STEP, task_id="t", payload={"step": "old"})
        cli.main(["events", "prune", "--home", str(tmp_path), "--days", "0", "--json"])
        assert json.loads(capsys.readouterr().out)["pruned"] == 1
        assert log.list() == []


class TestResultsMigrate:
    def test_dry_run_and_migrate(self, tmp_path, capsys, monkeypatch):
        import bacmap.interfaces.cli.main as cli

        flat = tmp_path / "results" / "OLD" / "report"
        flat.mkdir(parents=True)
        (flat / "OLD_summary.json").write_text("{}")
        cli.main(["results", "migrate", "--home", str(tmp_path), "--dry-run"])
        assert "OLD" in capsys.readouterr().out
        assert (tmp_path / "results" / "OLD").is_dir()
        cli.main(["results", "migrate", "--home", str(tmp_path)])
        assert (tmp_path / "results" / "OLD").is_symlink()
        assert (tmp_path / "results" / "runs" / "legacy-OLD" / "OLD").is_dir()
