"""Web 任务页测试（ADR-14）：列表 / 提交 / 轮询 / 审批签名发布。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store import baseline
from bacmap.store.strain_metadata import StrainMetadataService


def _sal_summary() -> dict:
    return {
        "sample": "SAM-001",
        "steps": {
            "species": {"verdict": "Salmonella"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
            "qc": {"after_filtering": {"total_reads": 1000}},
            "dec": {},
        },
    }


class _Proc:
    returncode = 0


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    rep = tmp_path / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
    (tmp_path / "data").mkdir(exist_ok=True)
    meta = StrainMetadataService(tmp_path / "data" / "metadata.sqlite")
    meta.upsert(
        "SAM-001",
        {
            "sample_id": "S1",
            "isolation_date": "2025-06-01",
            "province": "Guangdong",
            "city": "Shenzhen",
            "sample_source": "food",
        },
    )
    monkeypatch.setattr(eng, "_run_snakemake", lambda p: _Proc())
    monkeypatch.setattr(eng, "_step_create_run", lambda p: {"run_id": "web-run-1"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda rid, p: None)
    engine = eng.DbosTaskEngine(tmp_path)
    app = create_app(engine)
    yield TestClient(app), tmp_path
    eng.shutdown_dbos()


def _poll_fragment(c: TestClient, tid: str, want: str, timeout_s: float = 30.0) -> str:
    deadline = time.time() + timeout_s
    body = ""
    while time.time() < deadline:
        body = c.get(f"/tasks/{tid}/fragment").text
        if want in body:
            return body
        time.sleep(0.2)
    return body


class TestWebInterface:
    def test_index_returns_page(self, client):
        c, _ = client
        r = c.get("/")
        assert r.status_code == 200
        assert "bacmap" in r.text
        assert "暂无任务" in r.text or "SAM-" in r.text

    def test_submit_analyze_polls_to_succeeded(self, client):
        c, _ = client
        r = c.post(
            "/tasks/submit",
            data={"task_type": "analyze", "samples": "SAM-001"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        tid = str(r.url).rstrip("/").split("/")[-1]
        body = _poll_fragment(c, tid, "succeeded")
        assert "succeeded" in body

    def test_curate_approve_publishes_baseline(self, client):
        c, home = client
        r = c.post(
            "/tasks/submit",
            data={"task_type": "curate", "scope": "{}"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        tid = str(r.url).rstrip("/").split("/")[-1]
        body = _poll_fragment(c, tid, "awaiting_approval")
        assert "awaiting_approval" in body
        assert "审批签名" in body

        r2 = c.post(
            f"/tasks/{tid}/approve",
            data={"approver": "reviewer", "decision": "approve", "signature": "sig-web"},
            follow_redirects=True,
        )
        assert r2.status_code == 200
        assert "published baseline v1" in r2.text
        releases = baseline.list_releases(home / "baseline.sqlite")
        assert len(releases) == 1
        assert releases[0]["n_strains"] == 1

    def test_unknown_task_type_rejected(self, client):
        c, _ = client
        r = c.post("/tasks/submit", data={"task_type": "deploy", "samples": "X"})
        assert r.status_code == 400

    def test_unknown_task_404(self, client):
        c, _ = client
        assert c.get("/tasks/nope").status_code == 404
        assert c.get("/tasks/nope/fragment").status_code == 404

    def test_overview_page(self, client):
        c, home = client
        from sqlite3 import connect

        conn = connect(home / "tasks.sqlite")
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at, workflow_id, current_step)"
            " VALUES ('ov-1','analyze','succeeded','{}','t','2026-01-01T00:00:00',"
            "'2026-01-01T00:00:00','','analyze')"
        )
        conn.commit()
        conn.close()
        r = c.get("/overview")
        assert r.status_code == 200
        assert "系统概览" in r.text
        assert "LLM 端点" in r.text
        assert "D1" in r.text
        assert "BACMAP_HOME" in r.text
        assert "任务分布" in r.text
        assert "succeeded" in r.text
