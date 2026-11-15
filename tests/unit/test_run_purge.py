"""清理运行物理产物（v1.10.35）：记录与 GOM 保留，最新/运行中 run 拒绝。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store import runs as runs_store


def _home(tmp_path: Path, *, state: str = "succeeded") -> tuple[Path, str]:
    home = tmp_path / "home"
    cfg = home / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text("seeds:\n  iqtree: 1\n")
    db = home / "runs.sqlite"
    run = runs_store.create_run(
        workflow="bacmap",
        workflow_dir=home / "workflows" / "bacmap",
        strain_ids=["S1"],
        db_path=db,
        task_id="t1",
        refs_dir=tmp_path / "refs",
    )
    runs_store.finalize_run(run.run_id, db, home / "runs")
    with sqlite3.connect(home / "tasks.sqlite") as conn:
        conn.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, state TEXT)")
        conn.execute("INSERT INTO tasks VALUES ('t1', ?)", (state,))
    sample_dir = home / "results" / "runs" / "t1" / "S1"
    sample_dir.mkdir(parents=True)
    (sample_dir / "summary.json").write_text("{}")
    (sample_dir / "big.bin").write_bytes(b"x" * 1024)
    return home, run.run_id


def test_purge_removes_artifacts_and_keeps_record(tmp_path: Path):
    home, run_id = _home(tmp_path)
    result = runs_store.purge_run_artifacts(home, run_id, actor="test")
    assert result["purged"] is True
    assert result["files"] == 2 and result["bytes"] >= 1024
    assert not (home / "results" / "runs" / "t1").exists()
    assert runs_store.read_run(run_id, home / "runs.sqlite") is not None
    assert (home / "runs" / run_id / "run_manifest.json").is_file()
    with sqlite3.connect(home / "runs.sqlite") as conn:
        row = conn.execute(
            "SELECT actor, files FROM run_artifact_purges WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert row == ("test", 2)


def test_purge_is_idempotent(tmp_path: Path):
    home, run_id = _home(tmp_path)
    runs_store.purge_run_artifacts(home, run_id)
    again = runs_store.purge_run_artifacts(home, run_id)
    assert again["purged"] is False
    assert again["already_purged"] is True
    assert again["purged_at"]


def test_latest_alias_blocks_purge(tmp_path: Path):
    home, run_id = _home(tmp_path)
    (home / "results" / "S1").symlink_to(
        home / "results" / "runs" / "t1" / "S1"
    )
    with pytest.raises(ValueError, match="latest result"):
        runs_store.purge_run_artifacts(home, run_id)
    assert (home / "results" / "runs" / "t1" / "S1").is_dir()


@pytest.mark.parametrize("state", ["running", "paused", "pending", "awaiting_approval"])
def test_active_task_blocks_purge(tmp_path: Path, state: str):
    home, run_id = _home(tmp_path, state=state)
    with pytest.raises(ValueError, match=state):
        runs_store.purge_run_artifacts(home, run_id)
    assert (home / "results" / "runs" / "t1").is_dir()


def test_dry_run_and_missing_run(tmp_path: Path):
    home, run_id = _home(tmp_path)
    dry = runs_store.purge_run_artifacts(home, run_id, dry_run=True)
    assert dry["files"] == 2 and dry["purged"] is False
    assert (home / "results" / "runs" / "t1").is_dir()
    with pytest.raises(KeyError):
        runs_store.purge_run_artifacts(home, "nope")


def test_cli_purge(tmp_path: Path, capsys):
    from bacmap.interfaces.cli import main as cli

    home, run_id = _home(tmp_path)
    cli.main(["run", "purge", run_id, "--home", str(home), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["purged"] is True and payload["files"] == 2
    cli.main(["run", "purge", run_id, "--home", str(home), "--json"])
    assert json.loads(capsys.readouterr().out)["already_purged"] is True


def test_api_purge_and_latest_conflict(tmp_path: Path):
    home, run_id = _home(tmp_path)
    engine = eng.DbosTaskEngine(home)
    try:
        client = TestClient(create_app(engine))
        (home / "results" / "S1").symlink_to(
            home / "results" / "runs" / "t1" / "S1"
        )
        blocked = client.post(f"/api/v1/runs/{run_id}/purge")
        assert blocked.status_code == 409
        (home / "results" / "S1").unlink()
        ok = client.post(f"/api/v1/runs/{run_id}/purge")
        assert ok.status_code == 200 and ok.json()["purged"] is True
        assert client.post("/api/v1/runs/nope/purge").status_code == 404
    finally:
        eng.shutdown_dbos()
