"""版本化 JSON API（v1.5.2）：/api/v1 能力协商、任务/计划/事件/样本分页、SSE 续传。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.application.plans import PlanService, plan_task_id
from bacmap.interfaces.web import create_app
from bacmap.tasks.params import AnalyzeParams
from bacmap.tasks.spec import TaskType


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    started: list[str] = []
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: started.append(p["task_id"])
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    for sid in ("S1", "S2", "S3"):
        rep = tmp_path / "results" / sid / "report"
        rep.mkdir(parents=True)
        (rep / f"{sid}_summary.json").write_text(
            json.dumps({"sample": sid, "steps": {"species": {"verdict": "Salmonella"}}})
        )
    engine = eng.DbosTaskEngine(tmp_path)
    yield engine, TestClient(create_app(engine)), started
    eng.shutdown_dbos()


def _sse_events(text: str) -> list[dict]:
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":")
        )
        if "data" in fields:
            out.append({"id": int(fields["id"]), "event": fields["event"], **json.loads(fields["data"])})
    return out


class TestCapabilities:
    def test_versioned_and_leaks_no_paths(self, env):
        _, c, _ = env
        body = c.get("/api/v1/capabilities").json()
        assert body["api_version"] == "1"
        assert set(body["plannable_task_types"]) == {"analyze", "curate"}
        assert "events.sse" in body["features"]
        assert "/" not in json.dumps({k: v for k, v in body.items() if k != "endpoints"})


class TestTasks:
    def test_list_detail_cancel(self, env):
        engine, c, _ = env
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        assert [t["task_id"] for t in c.get("/api/v1/tasks").json()["items"]] == [tid]
        assert c.get(f"/api/v1/tasks/{tid}").json()["state"] == "running"
        assert c.post(f"/api/v1/tasks/{tid}/cancel").json()["state"] == "cancelled"
        again = c.post(f"/api/v1/tasks/{tid}/cancel")
        assert again.status_code == 409 and again.json()["code"] == "conflict"
        missing = c.get("/api/v1/tasks/nope")
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"


class TestPlans:
    def test_list_get_confirm_reject(self, env):
        engine, c, started = env
        svc = PlanService(engine, engine.db)
        rec = svc.create([AnalyzeParams(samples=["S1"])], "", "mcp-x")
        assert c.get("/api/v1/plans").json()["items"][0]["plan_id"] == rec.plan_id
        assert c.get(f"/api/v1/plans/{rec.plan_id}").json()["plan_hash"] == rec.plan_hash
        bad = c.post(
            f"/api/v1/plans/{rec.plan_id}/confirm",
            json={"version": 1, "plan_hash": "0" * 64, "confirmer": "ann"},
        )
        assert bad.status_code == 409 and started == []
        ok = c.post(
            f"/api/v1/plans/{rec.plan_id}/confirm",
            json={"version": 1, "plan_hash": rec.plan_hash, "confirmer": "ann"},
        )
        assert ok.json()["state"] == "submitted" and ok.json()["confirmed_by"] == "api:ann"
        assert started == [plan_task_id(rec.plan_id, 1, 0)]
        rec2 = svc.create([AnalyzeParams(samples=["S2"])], "", "mcp-x")
        rj = c.post(f"/api/v1/plans/{rec2.plan_id}/reject", json={"version": 1, "reason": "no"})
        assert rj.json()["state"] == "rejected"

    def test_validation_errors(self, env):
        _, c, _ = env
        r = c.post("/api/v1/plans/x/confirm", json={"version": "one"})
        assert r.status_code == 422
        assert c.get("/api/v1/plans/nope").status_code == 404


class TestEvents:
    def test_poll_with_cursor(self, env):
        engine, c, _ = env
        engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        first = c.get("/api/v1/events").json()
        assert [e["type"] for e in first["events"]] == ["task.submitted"]
        engine.submit(TaskType.ANALYZE, {"samples": ["S2"]}, "cli")
        nxt = c.get(f"/api/v1/events?after={first['last_seq']}").json()
        assert len(nxt["events"]) == 1 and nxt["events"][0]["seq"] > first["last_seq"]

    def test_sse_backlog_and_last_event_id(self, env):
        engine, c, _ = env
        engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        engine.submit(TaskType.ANALYZE, {"samples": ["S2"]}, "cli")
        r = c.get("/api/v1/events/stream?timeout=0")
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _sse_events(r.text)
        assert [e["event"] for e in events] == ["task.submitted", "task.submitted"]
        resumed = c.get(
            "/api/v1/events/stream?timeout=0", headers={"Last-Event-ID": str(events[0]["id"])}
        )
        assert [e["id"] for e in _sse_events(resumed.text)] == [events[1]["id"]]


class TestSamples:
    def test_cursor_pagination(self, env):
        _, c, _ = env
        p1 = c.get("/api/v1/samples?limit=2").json()
        assert [s["sample_id"] for s in p1["items"]] == ["S1", "S2"] and p1["next_cursor"] == "S2"
        p2 = c.get(f"/api/v1/samples?limit=2&cursor={p1['next_cursor']}").json()
        assert [s["sample_id"] for s in p2["items"]] == ["S3"] and p2["next_cursor"] is None

    def test_page_parses_only_requested_rows(self, env, monkeypatch):
        import bacmap.interfaces.views as views

        _, c, _ = env
        parsed: list[str] = []
        real = views._read_summary
        monkeypatch.setattr(views, "_read_summary", lambda p: parsed.append(p.name) or real(p))
        c.get("/api/v1/samples?limit=1")
        assert parsed == ["S1_summary.json"]


class TestCookieMode:
    def test_post_requires_csrf_header(self, env, monkeypatch):
        engine, _, _ = env
        monkeypatch.setenv("BACMAP_WEB_AUTH", "cookie")
        monkeypatch.setenv("BACMAP_WEB_SECRET", "s3cr3t-sign")
        c = TestClient(create_app(engine, auth_token="tok"))
        assert c.get("/api/v1/capabilities").status_code == 401
        c.post("/login", data={"token": "tok", "next": "/"})
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        h = {"origin": "http://testserver"}
        assert c.post(f"/api/v1/tasks/{tid}/cancel", headers=h).status_code == 403
        h["x-csrf-token"] = c.cookies.get("bacmap_csrf")
        assert c.post(f"/api/v1/tasks/{tid}/cancel", headers=h).status_code == 200
