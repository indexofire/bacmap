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
def engine(tmp_path: Path, monkeypatch):
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
    monkeypatch.setattr(eng, "_generate_report_for", lambda s: {"sample_id": s})
    monkeypatch.setattr(eng, "_step_create_run", lambda p: {"run_id": "web-run-1"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda rid, p: None)
    import contextlib

    class _Arb:
        @contextlib.contextmanager
        def heavy_step(self):
            yield

    monkeypatch.setattr(eng, "_memory_arbiter", lambda: _Arb())
    e = eng.DbosTaskEngine(tmp_path)
    yield e
    eng.shutdown_dbos()


@pytest.fixture
def client(engine):
    yield TestClient(create_app(engine)), Path(engine.home)


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


class TestResultsPages:
    """结果查询界面（深度补全：任务台之外的人工查询面）。"""

    def test_samples_page_lists_completed(self, client):
        c, _ = client
        r = c.get("/samples")
        assert r.status_code == 200
        assert "SAM-001" in r.text
        assert "Salmonella" in r.text

    def test_sample_detail_shows_species(self, client):
        c, _ = client
        r = c.get("/samples/SAM-001")
        assert r.status_code == 200
        assert "Salmonella" in r.text
        assert "blaCTX-M-15" in r.text

    def test_missing_sample_404(self, client):
        c, _ = client
        assert c.get("/samples/NOPE").status_code == 404

    def test_search_finds_by_gene(self, client):
        c, _ = client
        r = c.get("/search", params={"query": "blaCTX-M-15"})
        assert r.status_code == 200
        assert "SAM-001" in r.text

    def test_report_file_route_404_when_absent(self, client):
        c, _ = client
        assert c.get("/samples/SAM-001/report").status_code == 404

    def test_report_route_rejects_path_traversal(self, client):
        c, _ = client
        # urllib 对 ..%2f 的处理因版本而异；用编码斜杠确保路径参数带 .. 语义
        r = c.get("/samples/..%2f..%2fetc%2fpasswd/report")
        assert r.status_code in (400, 404)

    def test_sample_detail_rejects_path_traversal(self, client):
        c, _ = client
        r = c.get("/samples/..%2f..%2fetc%2fpasswd")
        assert r.status_code in (400, 404)


class TestWebAuth:
    """ADR-14：配置 token 时局域网访问需鉴权（未配置则本机直通）。"""

    def test_token_enforced(self, engine):
        c = TestClient(create_app(engine, auth_token="tok"))
        assert c.get("/").status_code == 401
        assert c.get("/", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/", headers={"Authorization": "Bearer tok"}).status_code == 200

    def test_no_token_means_no_auth(self, engine):
        c = TestClient(create_app(engine))
        assert c.get("/").status_code == 200
