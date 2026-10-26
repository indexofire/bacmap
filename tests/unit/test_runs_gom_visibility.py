"""证据可见性（v1.7.1）：运行记录与 GOM 的 CLI/API/Web 只读入口（ADR-18/13）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store import runs as runs_store


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text("seeds:\n  iqtree: 1\n")
    db = tmp_path / "runs.sqlite"
    run = runs_store.create_run(
        workflow="bacmap",
        workflow_dir=tmp_path / "workflows" / "bacmap",
        strain_ids=["S1"],
        input_files=[],
        db_path=db,
        task_id="t1",
    )
    run.resolved_config = {"cores": 8}
    runs_store.finalize_run(run.run_id, db, tmp_path / "runs")
    monkeypatch.setattr("bacmap.config.RUNS_DB", db)
    from datetime import UTC, datetime

    from bacmap.store.genome_object_service import GenomeObject, GenomeObjectService, ObjectType

    svc = GenomeObjectService(tmp_path / "gom.sqlite")
    svc.create(
        GenomeObject(
            object_id="obj-1",
            object_type=ObjectType.ANALYSIS,
            version=1,
            schema_version="1.0.0",
            created_at=datetime.now(UTC),
            created_by="cli",
            payload={"sample": "S1", "steps": {"species": {"verdict": "Salmonella"}}},
            pipeline_version="p1",
            tool_versions={"gside": "0.1.4"},
            strain_id="S1",
        )
    )
    svc.close()
    monkeypatch.setattr("bacmap.config.GOM_DB", tmp_path / "gom.sqlite")
    e = eng.DbosTaskEngine(tmp_path)
    yield e, TestClient(create_app(e)), run.run_id, tmp_path
    eng.shutdown_dbos()


class TestRunViews:
    def test_list_and_detail(self, seeded):
        from bacmap.interfaces import views

        _, _, run_id, home = seeded
        rows = views.list_runs(home)
        assert [r["run_id"] for r in rows] == [run_id]
        assert rows[0]["strain_ids"] == ["S1"]
        detail = views.run_detail(home, run_id)
        assert detail["workflow"] == "bacmap" and detail["config_sha256"] is not None
        assert views.run_detail(home, "nope") is None

    def test_compare(self, seeded):
        from bacmap.interfaces import views

        _, _, run_id, home = seeded
        out = views.compare_run_records(home, run_id, run_id)
        assert out["same_provenance"] is True and out["diffs"] == []


class TestGomViews:
    def test_list_and_detail(self, seeded):
        from bacmap.interfaces import views

        _, _, _, home = seeded
        objs = views.list_gom_objects(home, object_type="analysis")
        assert len(objs) == 1 and objs[0]["strain_id"] == "S1"
        assert objs[0]["payload_keys"] == ["sample", "steps"]
        assert views.list_gom_objects(home, object_type="nope") == []
        full = views.gom_object(home, objs[0]["object_id"], objs[0]["version"])
        assert full is not None and full["payload"]["steps"]["species"]["verdict"] == "Salmonella"


class TestRunCli:
    def test_run_ls_show_compare(self, seeded, monkeypatch, capsys):
        import bacmap.interfaces.cli.main as cli

        engine, _, run_id, home = seeded
        monkeypatch.setattr(cli, "_engine", lambda h: engine)
        cli.main(["run", "ls", "--home", str(home), "--json"])
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["run_id"] == run_id
        cli.main(["run", "show", run_id, "--home", str(home), "--json"])
        assert json.loads(capsys.readouterr().out)["workflow"] == "bacmap"
        cli.main(["run", "compare", run_id, run_id, "--home", str(home), "--json"])
        same = json.loads(capsys.readouterr().out)
        assert same["same_provenance"] is True
        with pytest.raises(SystemExit, match="运行记录不存在"):
            cli.main(["run", "compare", "a" * 8, "b" * 8, "--home", str(home)])


class TestRunApi:
    def test_runs_and_compare(self, seeded):
        _, c, run_id, _ = seeded
        items = c.get("/api/v1/runs").json()["items"]
        assert [r["run_id"] for r in items] == [run_id]
        assert c.get(f"/api/v1/runs/{run_id}").json()["workflow"] == "bacmap"
        same = c.get(f"/api/v1/runs/{run_id}/compare?other={run_id}").json()
        assert same["same_provenance"] is True
        assert c.get("/api/v1/runs/nope").status_code == 404

    def test_gom(self, seeded):
        _, c, _, _ = seeded
        objs = c.get("/api/v1/gom/objects?type=analysis").json()["items"]
        assert objs and objs[0]["strain_id"] == "S1"
        got = c.get(f"/api/v1/gom/objects/{objs[0]['object_id']}?version={objs[0]['version']}")
        assert got.json()["payload"]["sample"] == "S1"
        assert c.get("/api/v1/gom/objects/nope").status_code == 404


class TestRunWeb:
    def test_pages(self, seeded):
        _, c, run_id, _ = seeded
        assert run_id[:8] in c.get("/runs").text
        assert "bacmap" in c.get(f"/runs/{run_id}").text
        listing = c.get("/gom").text
        assert "S1" in listing and "steps" in listing
        detail = c.get("/gom/obj-1").text
        assert "Salmonella" in detail and "sample" in detail
        assert c.get("/runs/nope").status_code == 404
        assert c.get("/gom/nope").status_code == 404
