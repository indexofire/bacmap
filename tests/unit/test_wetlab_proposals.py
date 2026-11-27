"""P4：用户修改提案、四眼审核、归属传递与版本冲突。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store.specimen_metadata import SpecimenMetadataService
from bacmap.store.specimens import SpecimenService
from bacmap.store.users import Role, UserService


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


def _login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "next": "/console/"},
    )
    assert response.status_code == 200, response.text


def _csrf(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get("bacmap_csrf", "")}


@pytest.fixture
def proposal_home(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    monkeypatch.setenv("BACMAP_WEB_AUTH", "accounts")
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: p["task_id"]
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    db = tmp_path / "data" / "bacmap.sqlite"
    with UserService(db) as users:
        users.create("analyst", "analyst-pass", Role.ANALYST)
        users.create("alice", "alice-pass", Role.USER)
        users.create("bob", "bob-pass", Role.USER)
    from bacmap.store.isolates import IsolateService

    with SpecimenService(db) as specimens:
        specimens.ensure("SP-A", owner_user_id="alice")
        specimens.ensure("SP-B", owner_user_id="bob")
        specimens.ensure("SP-EMPTY")
    with IsolateService(db) as isolates:
        isolates.ensure("ISO-B", specimen_id="SP-EMPTY", owner_user_id="bob")
    engine = eng.DbosTaskEngine(tmp_path)
    client = TestClient(create_app(engine), base_url="http://127.0.0.1:8800")
    yield tmp_path, engine, client
    eng.shutdown_dbos()


def _propose(client: TestClient, params: dict):
    return client.post(
        "/api/v1/wetlab/proposals",
        headers=_csrf(client),
        json={"params": params},
    )


def test_user_proposes_and_analyst_approves(proposal_home):
    home, engine, client = proposal_home
    _login(client, "alice", "alice-pass")
    response = _propose(
        client,
        {
            "kind": "specimen_metadata",
            "specimen_id": "SP-A",
            "data": {"province": "广东", "patient_name": "张三"},
            "replace": True,
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["kind"] == "edit"
    assert job["created_by"] == "alice"
    assert job["target_type"] == "specimen" and job["target_id"] == "SP-A"
    assert job["base_version"]

    duplicate = _propose(
        client,
        {
            "kind": "specimen_metadata",
            "specimen_id": "SP-A",
            "data": {"province": "广西"},
        },
    )
    assert duplicate.status_code == 409
    preview = client.get(f"/api/v1/imports/{job['job_id']}/preview").json()
    assert preview["rows"][0]["data"]["province"] == "广东"
    lab = _propose(
        client,
        {
            "kind": "lab_result",
            "strain_id": "SP-A",
            "subject_type": "specimen",
            "subject_id": "SP-A",
            "category": "mngs",
            "test_name": "blaCTX-M",
            "result": "positive",
        },
    )
    assert lab.status_code == 200, lab.text
    # 业务表尚未写入
    with SpecimenMetadataService(home / "data" / "bacmap.sqlite") as store:
        assert store.get("SP-A") is None

    _login(client, "analyst", "analyst-pass")
    approved = client.post(
        f"/api/v1/imports/{job['job_id']}/approve",
        headers=_csrf(client),
        json={},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "submitted" and body["task_id"]
    assert engine.get_task(body["task_id"])["task_type"] == "record"
    import json
    import sqlite3

    with sqlite3.connect(str(engine.db)) as conn:
        row = conn.execute(
            "SELECT params_json FROM tasks WHERE task_id = ?", (body["task_id"],)
        ).fetchone()
    assert row is not None
    assert json.loads(row[0])["owner_user_id"] == "alice"
    lab_job = lab.json()
    _login(client, "analyst", "analyst-pass")
    lab_approved = client.post(
        f"/api/v1/imports/{lab_job['job_id']}/approve",
        headers=_csrf(client),
        json={},
    )
    assert lab_approved.status_code == 200, lab_approved.text


def test_user_proposes_new_specimen_and_isolate(proposal_home):
    _, engine, client = proposal_home
    _login(client, "alice", "alice-pass")
    specimen = _propose(
        client,
        {
            "kind": "specimen_create",
            "specimen_id": "SP-NEW",
            "origin": "manual",
            "note": "new",
        },
    )
    assert specimen.status_code == 200, specimen.text
    job = specimen.json()
    assert job["target_type"] == "specimen" and job["target_id"] == "SP-NEW"

    _login(client, "analyst", "analyst-pass")
    approved = client.post(
        f"/api/v1/imports/{job['job_id']}/approve",
        headers=_csrf(client),
        json={},
    )
    assert approved.status_code == 200, approved.text
    task_id = approved.json()["task_id"]
    import json
    import sqlite3

    with sqlite3.connect(str(engine.db)) as conn:
        row = conn.execute(
            "SELECT params_json FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    assert row is not None
    assert json.loads(row[0])["owner_user_id"] == "alice"


def test_user_cannot_propose_for_another_users_data(proposal_home):
    _, _, client = proposal_home
    _login(client, "alice", "alice-pass")
    response = _propose(
        client,
        {
            "kind": "specimen_metadata",
            "specimen_id": "SP-B",
            "data": {"province": "广东"},
        },
    )
    assert response.status_code == 404
    # 样本本身无主，但下面已有他人的菌株：不能通过认领样本绕过。
    response = _propose(
        client,
        {
            "kind": "specimen_metadata",
            "specimen_id": "SP-EMPTY",
            "data": {"province": "广东"},
        },
    )
    assert response.status_code == 404


def test_version_conflict_blocks_approval(proposal_home):
    home, _, client = proposal_home
    _login(client, "alice", "alice-pass")
    job = _propose(
        client,
        {
            "kind": "specimen_metadata",
            "specimen_id": "SP-A",
            "data": {"province": "广东"},
        },
    ).json()
    with SpecimenMetadataService(home / "data" / "bacmap.sqlite") as store:
        store.upsert("SP-A", {"province": "广西"})

    _login(client, "analyst", "analyst-pass")
    conflict = client.post(
        f"/api/v1/imports/{job['job_id']}/approve",
        headers=_csrf(client),
        json={},
    )
    assert conflict.status_code == 409
    assert "changed" in conflict.text


def test_user_upload_rejects_rows_for_another_users_specimen(proposal_home):
    _, _, client = proposal_home
    _login(client, "alice", "alice-pass")
    response = client.post(
        "/api/v1/imports",
        headers=_csrf(client),
        files={
            "file": (
                "specimen.tsv",
                "样本编号\t省份\nSP-B\t广东\n".encode(),
                "text/tab-separated-values",
            )
        },
    )
    assert response.status_code == 403
    assert "SP-B" in response.text
