"""Web 计划审阅与确认（v1.5.1，ADR-21 可信确认面）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.application.plans import PlanService, plan_task_id
from bacmap.interfaces.web import create_app
from bacmap.tasks.params import AnalyzeParams


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    started: list[str] = []
    from bacmap.tasks.engine import task_engine

    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: started.append(p["task_id"])
    )
    engine = eng.DbosTaskEngine(tmp_path)
    service = PlanService(engine, engine.db)
    rec = service.create([AnalyzeParams(samples=["SAM-001"])], "from harness", "mcp-x")
    yield engine, service, rec, started
    eng.shutdown_dbos()


def test_list_and_detail_show_full_parameters(setup):
    engine, _, rec, _ = setup
    c = TestClient(create_app(engine))
    assert rec.plan_id in c.get("/plans").text
    body = c.get(f"/plans/{rec.plan_id}").text
    assert "SAM-001" in body and rec.short_hash in body and "确认并提交" in body
    assert c.get("/plans/nope").status_code == 404


def test_confirm_submits_and_is_idempotent(setup):
    engine, service, rec, started = setup
    c = TestClient(create_app(engine))
    form = {"version": "1", "plan_hash": rec.plan_hash, "confirmer": "alice"}
    r = c.post(f"/plans/{rec.plan_id}/confirm", data=form, follow_redirects=False)
    assert r.status_code == 303
    c.post(f"/plans/{rec.plan_id}/confirm", data=form, follow_redirects=False)
    assert started == [plan_task_id(rec.plan_id, 1, 0)]
    done = service.get(rec.plan_id)
    assert done.state.value == "submitted" and done.confirmed_by == "web:alice"
    assert plan_task_id(rec.plan_id, 1, 0) in c.get(f"/plans/{rec.plan_id}").text


def test_stale_version_conflict(setup):
    engine, service, rec, started = setup
    service.revise(rec.plan_id, [AnalyzeParams(samples=["SAM-002"])], "", "mcp-x")
    c = TestClient(create_app(engine))
    r = c.post(
        f"/plans/{rec.plan_id}/confirm",
        data={"version": "1", "plan_hash": rec.plan_hash, "confirmer": "alice"},
    )
    assert r.status_code == 409 and "superseded" in r.text
    assert started == []


def test_reject(setup):
    engine, service, rec, _ = setup
    c = TestClient(create_app(engine))
    r = c.post(
        f"/plans/{rec.plan_id}/reject",
        data={"version": "1", "reason": "wrong sample"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert service.get(rec.plan_id).state.value == "rejected"


def test_cookie_mode_requires_csrf(setup, monkeypatch):
    engine, _, rec, started = setup
    monkeypatch.setenv("BACMAP_WEB_AUTH", "cookie")
    monkeypatch.setenv("BACMAP_WEB_SECRET", "s3cr3t-sign")
    c = TestClient(create_app(engine, auth_token="tok"))
    c.post("/login", data={"token": "tok", "next": "/"})
    form = {"version": "1", "plan_hash": rec.plan_hash, "confirmer": "alice"}
    r = c.post(f"/plans/{rec.plan_id}/confirm", data=form, headers={"origin": "http://testserver"})
    assert r.status_code == 403 and started == []
    form["csrf"] = c.cookies.get("bacmap_csrf")
    r = c.post(
        f"/plans/{rec.plan_id}/confirm",
        data=form,
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and len(started) == 1
