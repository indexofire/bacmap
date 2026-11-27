"""本地账号、RBAC 与个人数据可见性（v1.10.x）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store.strain_index import StrainGenotypeIndex
from bacmap.store.users import Role, UserService, hash_password, verify_password
from bacmap.tasks.spec import TaskType


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


def _client(home: Path) -> TestClient:
    return TestClient(create_app(eng.DbosTaskEngine(home)), base_url="http://127.0.0.1:8800")


def _login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "next": "/console/"},
    )
    assert response.status_code == 200, response.text


def _csrf(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get("bacmap_csrf", "")}


@pytest.fixture
def accounts_home(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    monkeypatch.setenv("BACMAP_WEB_AUTH", "accounts")
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: p["task_id"]
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    db = tmp_path / "data" / "bacmap.sqlite"
    with UserService(db) as users:
        users.create("admin", "admin-pass", Role.ADMIN)
        users.create("alice", "alice-pass", Role.USER)
        users.create("bob", "bob-pass", Role.USER)
        users.create("analyst", "analyst-pass", Role.ANALYST)
    engine = eng.DbosTaskEngine(tmp_path)
    # 两条归属不同的任务：alice 只能看到自己那条。
    alice_task = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "alice")
    bob_task = engine.submit(TaskType.ANALYZE, {"samples": ["S2"]}, "bob")
    client = _client(tmp_path)
    yield tmp_path, engine, client, alice_task, bob_task
    eng.shutdown_dbos()


class TestPasswordAndStore:
    def test_password_roundtrip(self):
        encoded = hash_password("correct horse")
        assert verify_password("correct horse", encoded)
        assert not verify_password("wrong", encoded)
        assert not verify_password("correct horse", "not-a-hash")

    def test_short_password_rejected(self, tmp_path):
        with UserService(tmp_path / "bacmap.sqlite") as users, pytest.raises(ValueError):
            users.create("alice", "short")

    def test_duplicate_and_case_insensitive(self, tmp_path):
        with UserService(tmp_path / "bacmap.sqlite") as users:
            users.create("Alice", "alice-pass")
            assert users.get_by_username("alice") is not None
            with pytest.raises(ValueError):
                users.create("alice", "other-pass")

    def test_last_admin_cannot_be_disabled_or_demoted(self, tmp_path):
        with UserService(tmp_path / "bacmap.sqlite") as users:
            admin = users.create("admin", "admin-pass", Role.ADMIN)
            with pytest.raises(ValueError):
                users.set_disabled(admin.user_id, True)
            with pytest.raises(ValueError):
                users.set_role(admin.user_id, Role.USER)
            users.create("admin2", "admin2-pass", Role.ADMIN)
            users.set_role(admin.user_id, Role.ANALYST)  # 还有第二个管理员

    def test_session_revoked_by_password_change(self, tmp_path):
        with UserService(tmp_path / "bacmap.sqlite") as users:
            user = users.create("alice", "alice-pass")
            token = users.create_session(user.user_id)
            assert users.resolve_session(token) is not None
            users.set_password(user.user_id, "new-password")
            assert users.resolve_session(token) is None

    def test_api_token_lifecycle(self, tmp_path):
        with UserService(tmp_path / "bacmap.sqlite") as users:
            user = users.create("alice", "alice-pass")
            token = users.create_api_token(user.user_id, "cli")
            assert users.resolve_api_token(token) is not None
            listed = users.list_api_tokens(user.user_id)
            assert listed and not listed[0]["revoked"]
            assert users.revoke_api_token(user.user_id, str(listed[0]["id"]))
            assert users.resolve_api_token(token) is None


class TestAccountsWeb:
    def test_login_status_and_permissions(self, accounts_home):
        _, _, client, _, _ = accounts_home
        _login(client, "alice", "alice-pass")
        status = client.get("/api/v1/auth/status").json()
        assert status["authenticated"] and status["role"] == "user"
        assert status["username"] == "alice"
        assert "data.read_all" not in status["permissions"]
        # user 不能进管理/全库视图
        assert client.get("/api/v1/users").status_code == 403
        assert client.get("/api/v1/stats").status_code == 403
        assert client.get("/api/v1/research/capabilities").status_code == 403

    def test_user_sees_only_own_tasks(self, accounts_home):
        _, _, client, alice_task, bob_task = accounts_home
        _login(client, "alice", "alice-pass")
        body = client.get("/api/v1/tasks").json()
        assert [t["task_id"] for t in body["items"]] == [alice_task]
        assert body["total"] == 1
        assert client.get(f"/api/v1/tasks/{bob_task}").status_code == 404

    def test_analyst_sees_all_tasks_and_admin_manages_users(self, accounts_home):
        _, _, client, _, _ = accounts_home
        _login(client, "analyst", "analyst-pass")
        assert len(client.get("/api/v1/tasks").json()["items"]) == 2
        assert client.get("/api/v1/users").status_code == 403

        admin = _client(Path(accounts_home[0]))
        _login(admin, "admin", "admin-pass")
        users = admin.get("/api/v1/users").json()["items"]
        assert {u["username"] for u in users} >= {"admin", "alice", "analyst"}
        created = admin.post(
            "/api/v1/users",
            headers=_csrf(admin),
            json={"username": "carol", "password": "carol-pass", "role": "user"},
        )
        assert created.status_code == 200, created.text
        assert created.json()["role"] == "user"
        assert admin.get("/api/v1/users").status_code == 200

    def test_invalid_login_and_logout(self, accounts_home):
        _, _, client, _, _ = accounts_home
        bad = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong", "next": "/"},
        )
        assert bad.status_code == 401
        _login(client, "alice", "alice-pass")
        out = client.post("/api/v1/auth/logout", headers=_csrf(client), json={})
        assert out.status_code == 200
        assert client.get("/api/v1/auth/status").json()["authenticated"] is False

    def test_owner_scoped_samples_and_specimens(self, accounts_home):
        home, _, client, _, _ = accounts_home
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
            isolates.ensure("ISO-ALICE", specimen_id="SP-ALICE", owner_user_id="alice")
            isolates.ensure("ISO-BOB", specimen_id="SP-BOB", owner_user_id="bob")
        with SpecimenService(home / "data" / "bacmap.sqlite") as specimens:
            specimens.ensure("SP-ALICE", owner_user_id="alice")
            specimens.ensure("SP-BOB", owner_user_id="bob")
        with StrainGenotypeIndex(home / "gom.sqlite") as index:
            index.upsert(
                strain_id="LIB-ALICE",
                organism="Escherichia coli",
                owner_user_id="alice",
                specimen_id="SP-ALICE",
                isolate_id="ISO-ALICE",
            )
            index.upsert(
                strain_id="LIB-BOB",
                organism="Salmonella enterica",
                owner_user_id="bob",
                specimen_id="SP-BOB",
                isolate_id="ISO-BOB",
            )

        _login(client, "alice", "alice-pass")
        samples = client.get("/api/v1/samples").json()["items"]
        assert [s["sample_id"] for s in samples] == ["LIB-ALICE"]
        specimens = client.get("/api/v1/specimens").json()["items"]
        assert [s["specimen_id"] for s in specimens] == ["SP-ALICE"]
        isolates = client.get("/api/v1/isolates").json()["items"]
        assert [i["isolate_id"] for i in isolates] == ["ISO-ALICE"]
        assert client.get("/api/v1/samples/LIB-BOB").status_code == 404
        assert client.get("/api/v1/specimens/SP-BOB").status_code == 404

        _login(client, "analyst", "analyst-pass")
        assert len(client.get("/api/v1/samples").json()["items"]) == 2
        assert len(client.get("/api/v1/specimens").json()["items"]) == 2

    def test_species_summary_is_scoped(self, accounts_home):
        home, _, client, _, _ = accounts_home
        with StrainGenotypeIndex(home / "gom.sqlite") as index:
            index.upsert(strain_id="A", organism="Escherichia coli", owner_user_id="alice")
            index.upsert(strain_id="B", organism="Salmonella enterica", owner_user_id="bob")
        _login(client, "alice", "alice-pass")
        items = client.get("/api/v1/species").json()["items"]
        assert [item["species"] for item in items] == ["Escherichia coli"]


    def test_result_index_filters_and_sort(self, accounts_home):
        home, _, client, _, _ = accounts_home
        with StrainGenotypeIndex(home / "gom.sqlite") as index:
            index.upsert(
                strain_id="EC1", organism="Escherichia coli", mlst_st="ST10",
                genome_size=5_000_000, owner_user_id="alice",
            )
            index.upsert(
                strain_id="EC2", organism="Escherichia coli", mlst_st="ST131",
                genome_size=4_000_000, owner_user_id="alice",
            )
            index.upsert(
                strain_id="SAL1", organism="Salmonella enterica", mlst_st="ST11",
                genome_size=4_800_000, owner_user_id="bob",
            )
        _login(client, "analyst", "analyst-pass")
        body = client.get(
            "/api/v1/samples?species=Escherichia%20coli&sort=genome_size&order=desc"
        ).json()
        assert [row["sample_id"] for row in body["items"]] == ["EC1", "EC2"]
        assert body["total"] == 2
        species = {
            row["species"]: row["n_samples"]
            for row in client.get("/api/v1/species").json()["items"]
        }
        assert species["Escherichia coli"] == 2
        assert species["Salmonella enterica"] == 1


    def test_user_upload_and_analyst_approve_import(self, accounts_home):
        home, engine, client, _, _ = accounts_home
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        db = home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-IMPORT")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-IMPORT", specimen_id="SP-IMPORT")
        payload = "菌株编号\t省份\nISO-IMPORT\t广东\n".encode()
        _login(client, "alice", "alice-pass")
        uploaded = client.post(
            "/api/v1/imports",
            headers=_csrf(client),
            files={"file": ("wetlab.tsv", payload, "text/tab-separated-values")},
        )
        assert uploaded.status_code == 201, uploaded.text
        job = uploaded.json()
        assert job["status"] == "pending_review"
        assert job["created_by"] == "alice"
        assert job["summary"]["isolate_rows"] == 1
        assert client.get("/api/v1/imports").json()["total"] == 1
        preview = client.get(f"/api/v1/imports/{job['job_id']}/preview").json()
        assert preview["rows"][0]["kind"] == "metadata"

        _login(client, "analyst", "analyst-pass")
        jobs = client.get("/api/v1/imports").json()["items"]
        assert [item["job_id"] for item in jobs] == [job["job_id"]]
        approved = client.post(
            f"/api/v1/imports/{job['job_id']}/approve",
            headers=_csrf(client),
            json={},
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["status"] == "submitted" and body["task_id"]
        assert body["reviewed_by"] == "analyst"
        assert engine.get_task(body["task_id"])["task_type"] == "record"


    def test_ai_mapping_advice_is_read_only(self, accounts_home, monkeypatch):
        home, _engine, client, _, _ = accounts_home
        from bacmap.agent.llm.import_mapping import (
            ColumnSuggestion,
            ImportMappingAdvice,
            MappingAdviceResult,
        )
        from bacmap.interfaces.web import imports as imports_module
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimen_metadata import SpecimenMetadataService
        from bacmap.store.specimens import SpecimenService
        from bacmap.tools.spec import DataClass

        db = home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-ADV")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-ADV", specimen_id="SP-ADV")
        payload = "菌株编号\t省份\t联系电话\nISO-ADV\t广东\t13800000000\n".encode()
        _login(client, "alice", "alice-pass")
        uploaded = client.post(
            "/api/v1/imports",
            headers=_csrf(client),
            files={"file": ("adv.tsv", payload, "text/tab-separated-values")},
        )
        assert uploaded.status_code == 201, uploaded.text
        job = uploaded.json()

        def fake_advice(record, config, gateway):
            assert len(record.rows) == 1
            return MappingAdviceResult(
                advice=ImportMappingAdvice(
                    columns=[
                        ColumnSuggestion(
                            layer="isolate",
                            source_column="联系电话",
                            suggested_field="patient_phone",
                            action="map",
                            confidence="high",
                            reason="同义列名",
                        )
                    ],
                    warnings=["D4 字段请人工确认"],
                    notes="只给建议",
                ),
                endpoint="fake-local",
                location="local",
                data_class=DataClass.D1,
                included_values=False,
            )

        monkeypatch.setattr(imports_module, "advise_import_mapping", fake_advice)
        advised = client.post(
            f"/api/v1/imports/{job['job_id']}/advise", headers=_csrf(client)
        )
        assert advised.status_code == 200, advised.text
        body = advised.json()
        assert body["data_class"] == "D1"
        assert body["included_values"] is False
        assert body["columns"][0]["suggested_field"] == "patient_phone"
        assert body["warnings"] == ["D4 字段请人工确认"]
        # 建议不改变审批状态，也不写入业务表
        assert client.get(f"/api/v1/imports/{job['job_id']}").json()["status"] == "pending_review"
        with SpecimenMetadataService(db) as meta:
            assert meta.get("ISO-ADV") is None

        _login(client, "bob", "bob-pass")
        assert client.post(
            f"/api/v1/imports/{job['job_id']}/advise", headers=_csrf(client)
        ).status_code == 404


    def test_user_cannot_edit_wetlab_but_analyst_can(self, accounts_home):
        home, _engine, client, _, _ = accounts_home
        from bacmap.store.specimens import SpecimenService

        with SpecimenService(home / "data" / "bacmap.sqlite") as specimens:
            specimens.ensure("SP-RBAC")
        _login(client, "alice", "alice-pass")
        denied = client.post(
            "/api/v1/wetlab/specimens/SP-RBAC/metadata",
            headers=_csrf(client),
            json={"data": {"province": "广东"}},
        )
        assert denied.status_code == 403

        _login(client, "analyst", "analyst-pass")
        allowed = client.post(
            "/api/v1/wetlab/specimens/SP-RBAC/metadata",
            headers=_csrf(client),
            json={"data": {"province": "广东"}},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["kind"] == "specimen_metadata"

    def test_accounts_mode_requires_auth(self, accounts_home):
        _, _, _, _, _ = accounts_home
        anonymous = _client(Path(accounts_home[0]))
        assert anonymous.get("/api/v1/tasks").status_code == 401
        assert anonymous.get("/api/v1/auth/status").status_code == 200
