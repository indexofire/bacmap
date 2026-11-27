"""个人模式 hash-key 登录（v1.10.54，P2）。"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store.personal import (
    ACCESS_KEY_PREFIX,
    create_personal,
    load_personal,
    personal_ready,
    personal_status,
    verify_access_key,
)
from bacmap.store.users import Role, UserService


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


def test_personal_key_lifecycle(tmp_path: Path):
    key, access = create_personal(tmp_path)
    assert key.startswith(ACCESS_KEY_PREFIX)
    assert access.username == "owner"
    assert personal_ready(tmp_path)
    assert verify_access_key(tmp_path, key)
    assert not verify_access_key(tmp_path, "bk_wrong")

    path = tmp_path / "personal.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert key not in json.dumps(raw), "plaintext key must never be persisted"
    assert raw["key_hash"].startswith("scrypt$")

    with UserService(tmp_path / "data" / "bacmap.sqlite") as users:
        owner = users.get_by_username("owner")
        assert owner is not None and owner.role is Role.ADMIN

    with pytest.raises(FileExistsError):
        create_personal(tmp_path)

    # 组织部署误跑 personal init 时不得把普通 owner 提权
    other = tmp_path / "org"
    with UserService(other / "data" / "bacmap.sqlite") as users:
        users.create("owner", "owner-pass", Role.USER)
    with pytest.raises(ValueError):
        create_personal(other)

    new_key, rotated = create_personal(tmp_path, rotate=True)
    assert new_key != key
    assert rotated.rotated_at
    assert verify_access_key(tmp_path, new_key)
    assert not verify_access_key(tmp_path, key)
    assert personal_status(tmp_path)["ready"] is True


def test_web_personal_login_and_full_features(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    key, _ = create_personal(tmp_path)
    monkeypatch.setenv("BACMAP_WEB_AUTH", "personal")
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: p["task_id"]
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    engine = eng.DbosTaskEngine(tmp_path)
    client = TestClient(
        create_app(engine), base_url="http://127.0.0.1:8800"
    )
    try:
        status = client.get("/api/v1/auth/status").json()
        assert status["mode"] == "personal"
        assert status["personal_ready"] is True
        assert status["authenticated"] is False

        bad = client.post("/api/v1/auth/login", json={"token": "bk_nope"})
        assert bad.status_code == 401
        assert client.get("/api/v1/stats").status_code == 401

        login = client.post(
            "/api/v1/auth/login", json={"token": key, "next": "/console/"}
        )
        assert login.status_code == 200, login.text
        status = client.get("/api/v1/auth/status").json()
        assert status["authenticated"] is True
        assert status["role"] == "admin"
        assert status["username"] == "owner"
        assert "record.write" in status["permissions"]
        assert "import.review" in status["permissions"]
        # 个人模式 = 全功能（不是受限 user）
        assert client.get("/api/v1/stats").status_code == 200
        assert client.get("/api/v1/users").status_code == 200

        # 个人模式也执行角色权限（不能因为不是 accounts 而绕过 RBAC）
        with UserService(tmp_path / "data" / "bacmap.sqlite") as users:
            bob = users.create("bob", "bob-pass", Role.USER)
            bob_session = users.create_session(bob.user_id)
        bob_cookie = {"cookie": f"bacmap_session={bob_session}"}
        assert client.get("/api/v1/auth/status", headers=bob_cookie).json()["role"] == "user"
        assert client.get("/api/v1/users", headers=bob_cookie).status_code == 403

        # 个人模式使用 cookie 会话，状态变更必须带 CSRF
        assert client.post("/api/v1/auth/logout").status_code == 403
        csrf = client.cookies.get("bacmap_csrf", "")
        logout = client.post(
            "/api/v1/auth/logout", headers={"x-csrf-token": csrf}
        )
        assert logout.status_code == 200
        assert client.get("/api/v1/stats").status_code == 401
    finally:
        eng.shutdown_dbos()


def test_personal_login_before_init_fails_closed(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    monkeypatch.setenv("BACMAP_WEB_AUTH", "personal")
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: p["task_id"]
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    engine = eng.DbosTaskEngine(tmp_path)
    client = TestClient(create_app(engine), base_url="http://127.0.0.1:8800")
    try:
        response = client.post("/api/v1/auth/login", json={"token": "bk_anything"})
        assert response.status_code == 503
        assert "bacmap personal init" in response.text
        assert load_personal(tmp_path) is None
    finally:
        eng.shutdown_dbos()
