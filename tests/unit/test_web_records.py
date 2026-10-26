"""Web 数据记录页（v1.7）：元数据 / 化验 / 知识库——只提交 record 任务。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    started: list[str] = []
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: started.append(p["task_id"])
    )
    e = eng.DbosTaskEngine(tmp_path)
    yield e, TestClient(create_app(e)), started
    eng.shutdown_dbos()


def test_page_lists_three_forms(setup):
    _, c, _ = setup
    body = c.get("/records").text
    for frag in ("菌株元数据", "化验结果", "文献知识库", 'action="/records/metadata"'):
        assert frag in body
    assert 'href="/records"' in c.get("/").text


def test_metadata_form_creates_task(setup):
    engine, c, started = setup
    r = c.post(
        "/records/metadata",
        data={"strain_id": "S1", "fields": "province=Guangdong\nsample_source=food"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/tasks/")
    assert len(started) == 1
    row = engine.list_tasks(1)[0]
    assert row["task_type"] == "record" and row["submitted_by"] == "web"


def test_lab_and_knowledge_forms(setup):
    _, c, started = setup
    assert c.post(
        "/records/lab",
        data={"strain_id": "S1", "category": "mic", "test_name": "meropenem", "result": "0.25"},
        follow_redirects=False,
    ).status_code == 303
    assert c.post(
        "/records/knowledge-import",
        data={"title": "Paper", "identifier": "PMID:1"},
        follow_redirects=False,
    ).status_code == 303
    assert c.post(
        "/records/knowledge-approve", data={"entry_id": "3"}, follow_redirects=False
    ).status_code == 303
    assert len(started) == 3


def test_validation_errors(setup):
    _, c, started = setup
    assert c.post("/records/metadata", data={"strain_id": "S1", "fields": "nope"}).status_code == 400
    assert c.post("/records/metadata", data={"strain_id": "S1", "fields": "unknown=1"}).status_code == 400
    assert c.post("/records/lab", data={"strain_id": "S1"}).status_code == 400
    assert c.post("/records/knowledge-approve", data={"entry_id": "x"}).status_code == 400
    assert c.post("/records/bogus", data={}).status_code == 404
    assert started == []


def test_cookie_mode_requires_csrf(setup, monkeypatch):
    engine, _, started = setup
    monkeypatch.setenv("BACMAP_WEB_AUTH", "cookie")
    monkeypatch.setenv("BACMAP_WEB_SECRET", "s3cr3t-sign")
    c = TestClient(create_app(engine, auth_token="tok"))
    c.post("/login", data={"token": "tok", "next": "/"})
    r = c.post("/records/metadata", data={"strain_id": "S1"}, headers={"origin": "http://testserver"})
    assert r.status_code == 403 and started == []
    r = c.post(
        "/records/metadata",
        data={"strain_id": "S1", "csrf": c.cookies.get("bacmap_csrf")},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and len(started) == 1
