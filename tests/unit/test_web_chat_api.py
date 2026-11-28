"""P1 Web 对话 API：/api/v1/chat/* 的能力面、会话 CRUD、SSE 运行与多用户隔离。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.agent.chat.config import WebChatConfig
from bacmap.agent.chat.service import ChatOrchestrator
from bacmap.agent.llm.chat import BuiltinChatBackend
from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.interfaces.web import create_app
from bacmap.store.users import Role, UserService


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


def _csrf(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get("bacmap_csrf", "")}


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def _write_config(home: Path, mode: str = "builtin", extra: str = "") -> Path:
    path = home / "config.toml"
    path.write_text(f'[web.chat]\nmode = "{mode}"\n{extra}')
    return path


def _make_chat_app(
    home: Path, monkeypatch, stream_fn, *, mode: str = "builtin", extra: str = ""
) -> TestClient:
    """装配启用对话的测试应用（内置后端使用 FunctionModel，零网络）。"""
    from pydantic_ai.models.function import FunctionModel

    cfg_path = _write_config(home, mode, extra)
    monkeypatch.setenv("BACMAP_CONFIG", str(cfg_path))

    engine = eng.DbosTaskEngine(home)
    app = create_app(engine)

    ep = LlmEndpoint(name="t", base_url="http://127.0.0.1:9/v1", model="m")
    llm = LlmConfig(endpoints={"t": ep}, routing={"chat": "t"})
    backend = BuiltinChatBackend(
        home, engine, llm, WebChatConfig().builtin,
        model_override=FunctionModel(stream_function=stream_fn),
    )
    from bacmap.agent.chat.config import load_chat_config

    orch = ChatOrchestrator(
        home, engine, load_chat_config(cfg_path),
        builtin_backend_factory=lambda: backend,
    )
    app.state.chat_orchestrator = orch
    return TestClient(app, base_url="http://127.0.0.1:8800")


async def _text_stream(messages, info):
    yield "你好，这里是 bacmap"


async def _plan_stream(messages, info):
    from pydantic_ai.models.function import DeltaToolCall

    has_return = any(
        getattr(p, "part_kind", "") == "tool-return"
        for m in messages
        for p in getattr(m, "parts", [])
    )
    if has_return:
        yield "计划已创建，请确认"
    else:
        yield {
            0: DeltaToolCall(
                name="bacmap_create_plan",
                json_args=json.dumps(
                    {"tasks": [{"task_type": "analyze", "samples": ["S1"]}]}
                ),
            )
        }


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: p["task_id"]
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    home = tmp_path / "home"
    home.mkdir()
    yield home, monkeypatch
    eng.shutdown_dbos()


class TestChatDisabled:
    def test_mode_off_hides_chat(self, chat_env):
        home, monkeypatch = chat_env
        cfg_path = _write_config(home, "off")
        monkeypatch.setenv("BACMAP_CONFIG", str(cfg_path))
        client = TestClient(create_app(eng.DbosTaskEngine(home)))
        caps = client.get("/api/v1/capabilities").json()
        assert caps["chat"]["enabled"] is False
        assert "chat" not in caps["features"]
        created = client.post("/api/v1/chat/sessions", json={})
        sid = created.json()["session_id"]
        run = client.post(f"/api/v1/chat/sessions/{sid}/run", json={"message": "hi"})
        assert run.status_code == 400


class TestLegacyModeChat:
    def test_run_stream_and_persistence(self, chat_env):
        home, monkeypatch = chat_env
        client = _make_chat_app(home, monkeypatch, _plan_stream)
        caps = client.get("/api/v1/capabilities").json()
        assert caps["chat"]["enabled"] is True
        assert "chat" in caps["features"]
        assert caps["chat"]["backends"][0]["id"] == "builtin"

        created = client.post("/api/v1/chat/sessions", json={"title": ""})
        assert created.status_code == 200
        sid = created.json()["session_id"]

        run = client.post(
            f"/api/v1/chat/sessions/{sid}/run",
            json={"message": "帮我分析 S1"},
        )
        assert run.status_code == 200
        assert run.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(run.text)
        types_seen = [e["type"] for e in events]
        assert "RUN_STARTED" in types_seen
        assert "TEXT_MESSAGE_CONTENT" in types_seen
        assert types_seen[-1] == "RUN_FINISHED"
        cards = [
            e for e in events
            if e["type"] == "CUSTOM" and e["name"] == "bacmap.plan_card"
        ]
        assert len(cards) == 1
        assert cards[0]["value"]["state"] == "awaiting_confirmation"

        detail = client.get(f"/api/v1/chat/sessions/{sid}").json()
        roles = [m["role"] for m in detail["messages"]]
        assert roles == ["user", "assistant"]
        assistant = detail["messages"][1]
        assert "计划已创建" in assistant["content"]
        assert any(
            c.get("plan_id") == cards[0]["value"]["plan_id"] for c in assistant["cards"]
        )
        assert detail["session"]["title"] == "帮我分析 S1"

    def test_run_agui_input_shape_and_validation(self, chat_env):
        home, monkeypatch = chat_env
        client = _make_chat_app(home, monkeypatch, _text_stream)
        sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
        run = client.post(
            f"/api/v1/chat/sessions/{sid}/run",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )
        assert run.status_code == 200
        assert "RUN_STARTED" in run.text
        empty = client.post(
            f"/api/v1/chat/sessions/{sid}/run", json={"message": "  "}
        )
        assert empty.status_code == 400
        missing = client.post(
            "/api/v1/chat/sessions/cs_nope/run", json={"message": "hi"}
        )
        assert missing.status_code == 404

    def test_session_crud(self, chat_env):
        home, monkeypatch = chat_env
        client = _make_chat_app(home, monkeypatch, _text_stream)
        sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
        assert client.get("/api/v1/chat/sessions").json()["items"][0]["session_id"] == sid
        patched = client.patch(
            f"/api/v1/chat/sessions/{sid}", json={"title": "新标题"}
        )
        assert patched.json()["title"] == "新标题"
        assert client.delete(f"/api/v1/chat/sessions/{sid}").json()["deleted"] is True
        assert client.get(f"/api/v1/chat/sessions/{sid}").status_code == 404


class TestAccountsModeChat:
    @pytest.fixture
    def accounts(self, chat_env):
        home, monkeypatch = chat_env
        monkeypatch.setenv("BACMAP_WEB_AUTH", "accounts")
        db = home / "data" / "bacmap.sqlite"
        with UserService(db) as users:
            users.create("admin", "admin-pass", Role.ADMIN)
            users.create("alice", "alice-pass", Role.USER)
        extra = (
            "\n[[web.chat.external]]\n"
            'id = "dsh"\nname = "DSH"\nprotocol = "dsh"\n'
            'url = "http://127.0.0.1:3080/"\nallowed_roles = ["admin"]\n'
        )
        client = _make_chat_app(home, monkeypatch, _text_stream, mode="both", extra=extra)
        yield home, client

    def _login(self, client: TestClient, username: str, password: str) -> TestClient:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password, "next": "/console/"},
        )
        assert response.status_code == 200, response.text
        return client

    def test_cross_user_session_isolation(self, accounts):
        _, client_admin = accounts
        self._login(client_admin, "admin", "admin-pass")
        sid = client_admin.post(
            "/api/v1/chat/sessions", json={}, headers=_csrf(client_admin)
        ).json()["session_id"]

        client_alice = TestClient(client_admin.app, base_url="http://127.0.0.1:8800")
        self._login(client_alice, "alice", "alice-pass")
        assert client_alice.get(f"/api/v1/chat/sessions/{sid}").status_code == 404
        assert (
            client_alice.patch(
                f"/api/v1/chat/sessions/{sid}",
                json={"title": "x"},
                headers=_csrf(client_alice),
            ).status_code
            == 404
        )
        assert (
            client_alice.delete(
                f"/api/v1/chat/sessions/{sid}", headers=_csrf(client_alice)
            ).status_code
            == 404
        )
        assert (
            client_alice.post(
                f"/api/v1/chat/sessions/{sid}/run",
                json={"message": "hi"},
                headers=_csrf(client_alice),
            ).status_code
            == 404
        )
        # admin 自己的会话仍可用
        assert client_admin.get(f"/api/v1/chat/sessions/{sid}").status_code == 200
        # alice 看不到 admin 的会话
        items = client_alice.get("/api/v1/chat/sessions").json()["items"]
        assert items == []

    def test_csrf_enforced_on_writes(self, accounts):
        _, client = accounts
        self._login(client, "admin", "admin-pass")
        assert client.post("/api/v1/chat/sessions", json={}).status_code == 403
        created = client.post(
            "/api/v1/chat/sessions", json={}, headers=_csrf(client)
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        assert (
            client.patch(f"/api/v1/chat/sessions/{sid}", json={"title": "x"}).status_code
            == 403
        )
        assert client.delete(f"/api/v1/chat/sessions/{sid}").status_code == 403
        assert (
            client.post(
                f"/api/v1/chat/sessions/{sid}/run", json={"message": "hi"}
            ).status_code
            == 403
        )

    def test_external_backends_filtered_by_role(self, accounts):
        _, client = accounts
        self._login(client, "admin", "admin-pass")
        cfg = client.get("/api/v1/chat/config").json()
        ext = [b for b in cfg["backends"] if b["kind"] == "external"]
        assert len(ext) == 1 and ext[0]["id"] == "dsh"
        assert ext[0]["available"] is True  # P2：配置了回环 url 即可用

        client_alice = TestClient(client.app, base_url="http://127.0.0.1:8800")
        self._login(client_alice, "alice", "alice-pass")
        cfg_alice = client_alice.get("/api/v1/chat/config").json()
        assert [b for b in cfg_alice["backends"] if b["kind"] == "external"] == []
        assert cfg_alice["can_confirm_plans"] is False

    def test_user_run_streams_and_persists(self, accounts):
        _, client = accounts
        self._login(client, "alice", "alice-pass")
        sid = client.post(
            "/api/v1/chat/sessions", json={}, headers=_csrf(client)
        ).json()["session_id"]
        run = client.post(
            f"/api/v1/chat/sessions/{sid}/run",
            json={"message": "你好"},
            headers=_csrf(client),
        )
        assert run.status_code == 200
        events = _parse_sse(run.text)
        assert events[-1]["type"] == "RUN_FINISHED"
        detail = client.get(f"/api/v1/chat/sessions/{sid}").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
