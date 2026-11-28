"""P1 对话后端：ChatStore、配置解析、AG-UI 协议、内置 pydantic-ai 后端。"""

from __future__ import annotations

import json
import os
import types
from pathlib import Path

import pytest

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from bacmap.agent.chat.agui import (
    RunStartedEvent,
    TextMessageContentEvent,
    encode_sse,
)
from bacmap.agent.chat.config import WebChatConfig, load_chat_config
from bacmap.agent.chat.service import ChatOrchestrator
from bacmap.agent.chat.types import ChatActor, ChatRunContext, PageContext
from bacmap.agent.llm.chat import BuiltinChatBackend
from bacmap.agent.llm.endpoints import DataPolicy, LlmConfig, LlmEndpoint
from bacmap.store.chat import ChatStore
from bacmap.store.migrations import schema_version
from bacmap.tools.spec import DataClass


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


def _actor(**overrides) -> ChatActor:
    base = {
        "user_id": "u_admin",
        "username": "admin",
        "role": "admin",
        "can_read_all": True,
        "can_confirm_plans": True,
        "is_admin": True,
    }
    base.update(overrides)
    return ChatActor(**base)


class TestChatStore:
    def test_migration_and_crud(self, tmp_path):
        db = tmp_path / "data" / "bacmap.sqlite"
        with ChatStore(db) as store:
            assert schema_version(db) >= 8
            session = store.create_session("u1", title="hello")
            assert session.backend_id == "builtin"
            assert store.get_session(session.session_id, "u1") is not None
            listed = store.list_sessions("u1")
            assert [s.session_id for s in listed] == [session.session_id]
            updated = store.update_session(session.session_id, "u1", title="new")
            assert updated is not None and updated.title == "new"
            assert store.delete_session(session.session_id, "u1") is True
            assert store.get_session(session.session_id, "u1") is None

    def test_cross_user_isolation(self, tmp_path):
        db = tmp_path / "bacmap.sqlite"
        with ChatStore(db) as store:
            session = store.create_session("user-a")
            sid = session.session_id
            assert store.get_session(sid, "user-b") is None
            assert store.update_session(sid, "user-b", title="x") is None
            assert store.delete_session(sid, "user-b") is False
            with pytest.raises(KeyError):
                store.append_message(sid, "user-b", role="user", content="hi")
            with pytest.raises(KeyError):
                store.list_messages(sid, "user-b")
            with pytest.raises(KeyError):
                store.link_task(sid, "user-b", "t1")
            # user-a 仍可读
            assert store.get_session(sid, "user-a") is not None

    def test_messages_auto_title_and_link_dedup(self, tmp_path):
        db = tmp_path / "bacmap.sqlite"
        with ChatStore(db) as store:
            session = store.create_session("u1")
            long_msg = "x" * 100
            store.append_message(session.session_id, "u1", role="user", content=long_msg)
            after = store.get_session(session.session_id, "u1")
            assert after is not None and after.title == "x" * 60
            store.append_message(
                session.session_id, "u1", role="assistant", content="answer",
                tool_calls=[{"id": "t1", "name": "bio_x"}],
                cards=[{"kind": "bacmap.plan_card", "plan_id": "p1"}],
            )
            messages = store.list_messages(session.session_id, "u1")
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].tool_calls[0]["name"] == "bio_x"
            assert messages[1].cards[0]["plan_id"] == "p1"
            store.link_task(session.session_id, "u1", "task-1")
            store.link_task(session.session_id, "u1", "task-1")
            store.link_task(session.session_id, "u1", "task-2")
            final = store.get_session(session.session_id, "u1")
            assert final is not None
            assert final.linked_tasks == ["task-1", "task-2"]
            # 删除会话级联删除消息
            assert store.delete_session(session.session_id, "u1") is True

    def test_list_recent_messages_returns_latest_in_order(self, tmp_path):
        db = tmp_path / "bacmap.sqlite"
        with ChatStore(db) as store:
            s = store.create_session("u1")
            for i in range(5):
                store.append_message(s.session_id, "u1", role="user", content=f"m{i}")
            recent = store.list_recent_messages(s.session_id, "u1", limit=2)
            assert [m.content for m in recent] == ["m3", "m4"]
            all_msgs = store.list_recent_messages(s.session_id, "u1", limit=50)
            assert [m.content for m in all_msgs] == [f"m{i}" for i in range(5)]

    def test_delete_is_atomic_per_owner(self, tmp_path):
        db = tmp_path / "bacmap.sqlite"
        with ChatStore(db) as store:
            s = store.create_session("u1")
            store.append_message(s.session_id, "u1", role="user", content="hi")
            assert store.delete_session(s.session_id, "u1") is True
            assert store.delete_session(s.session_id, "u1") is False


class TestChatConfig:
    def test_defaults_off_when_missing(self, tmp_path):
        cfg = load_chat_config(tmp_path / "nope.toml")
        assert cfg.mode == "off" and not cfg.enabled

    def test_missing_section_defaults_off(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[web]\nport = 8800\n")
        assert load_chat_config(path).mode == "off"

    def test_parse_builtin_and_external(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            """
[web.chat]
mode = "both"
default_backend = "builtin"

[web.chat.builtin]
purpose = "chat"
max_history_messages = 20
system_prompt_extra = "extra rules"

[[web.chat.external]]
id = "dsh"
name = "DSH"
protocol = "dsh"
url = "http://127.0.0.1:3080/"
allowed_roles = ["admin", "analyst"]
"""
        )
        cfg = load_chat_config(path)
        assert cfg.mode == "both" and cfg.enabled
        assert cfg.builtin.max_history_messages == 20
        assert cfg.builtin.system_prompt_extra == "extra rules"
        assert len(cfg.external) == 1 and cfg.external[0].id == "dsh"

    def test_non_loopback_external_url_rejected(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            """
[web.chat]
mode = "external"

[[web.chat.external]]
id = "evil"
name = "evil"
url = "https://cloud.example.com/agent"

[[web.chat.external]]
id = "ok"
name = "ok"
url = "http://localhost:9999"
"""
        )
        cfg = load_chat_config(path)
        assert [e.id for e in cfg.external] == ["ok"]

    def test_history_clamped(self):
        cfg = WebChatConfig()
        assert cfg.builtin.max_history_messages == 40
        from bacmap.agent.chat.config import BuiltinChatConfig

        assert BuiltinChatConfig(max_history_messages=99999).max_history_messages == 200
        assert BuiltinChatConfig(max_history_messages=0).max_history_messages == 2


class TestAgui:
    def test_wire_format(self):
        event = RunStartedEvent(thread_id="t1", run_id="r1", timestamp=123)
        data = json.loads(event.model_dump_json(by_alias=True, exclude_none=True))
        assert data == {"type": "RUN_STARTED", "timestamp": 123, "threadId": "t1", "runId": "r1"}
        sse = encode_sse(TextMessageContentEvent(message_id="m1", delta="hi"))
        assert sse.startswith("data: ") and sse.endswith("\n\n")
        payload = json.loads(sse[len("data: "):])
        assert payload["type"] == "TEXT_MESSAGE_CONTENT"
        assert payload["messageId"] == "m1" and payload["delta"] == "hi"


# ---- 内置后端（FunctionModel，零网络） ------------------------------------------


def _llm_config(location: str = "local", cloud_max: DataClass = DataClass.D1) -> LlmConfig:
    ep = LlmEndpoint(
        name="test-ep",
        base_url="http://127.0.0.1:9/v1",
        model="test-model",
        location=location,  # type: ignore[arg-type]
    )
    return LlmConfig(
        endpoints={"test-ep": ep},
        routing={"chat": "test-ep"},
        policy=DataPolicy(cloud_max_data_class=cloud_max),
    )


def _stub_engine(home: Path) -> types.SimpleNamespace:
    engine = types.SimpleNamespace()
    engine.home = str(home)
    engine.db = str(home / "tasks.sqlite")
    engine.list_tasks = lambda limit=20, **kw: []
    engine.get_task = lambda tid: (_ for _ in ()).throw(KeyError(tid))
    engine.status = lambda tid: (_ for _ in ()).throw(KeyError(tid))
    engine.workflow_result = lambda tid: None
    return engine


def _backend(
    home: Path,
    stream_fn,
    *,
    llm_config: LlmConfig | None = None,
    actor: ChatActor | None = None,
) -> tuple[BuiltinChatBackend, ChatOrchestrator, ChatActor]:
    from pydantic_ai.models.function import FunctionModel

    engine = _stub_engine(home)
    config = llm_config or _llm_config()
    backend = BuiltinChatBackend(
        home,
        engine,
        config,
        WebChatConfig().builtin,
        model_override=FunctionModel(stream_function=stream_fn),
    )
    chat_config = WebChatConfig(mode="builtin")
    orch = ChatOrchestrator(
        home,
        engine,
        chat_config,
        builtin_backend_factory=lambda: backend,
    )
    return backend, orch, (actor or _actor())


def _ctx(actor: ChatActor, message: str = "hello") -> ChatRunContext:
    return ChatRunContext(
        session_id="s1",
        thread_id="t1",
        run_id="r1",
        message=message,
        history=[],
        actor=actor,
        page_context=PageContext(route="/console/samples/S1", entity_type="sample", entity_id="S1"),
    )


async def _collect(aiter):
    return [event async for event in aiter]


class TestBuiltinBackend:
    def test_text_stream_events(self, tmp_path):
        async def stream_fn(messages, info):
            yield "你好"
            yield "世界"

        home = tmp_path / "home"
        home.mkdir()
        _, orch, actor = _backend(home, stream_fn)

        async def go():
            store = ChatStore(home / "data" / "bacmap.sqlite")
            with store:
                session = store.create_session(actor.user_id)
            events = await _collect(
                orch.stream_run(session.session_id, "你好", actor)
            )
            return session, events

        session, events = _run(go())
        types_seen = [e.type for e in events]
        assert types_seen[0] == "RUN_STARTED"
        assert "STATE_SNAPSHOT" in types_seen
        assert "TEXT_MESSAGE_START" in types_seen
        assert "TEXT_MESSAGE_CONTENT" in types_seen
        assert types_seen[-1] == "RUN_FINISHED"
        text = "".join(e.delta for e in events if e.type == "TEXT_MESSAGE_CONTENT")
        assert text == "你好世界"
        with ChatStore(home / "data" / "bacmap.sqlite") as store:
            messages = store.list_messages(session.session_id, actor.user_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[1].content == "你好世界"

    def test_tool_call_stream_and_persist(self, tmp_path):
        from pydantic_ai.models.function import DeltaToolCall

        async def stream_fn(messages, info):
            has_return = any(
                getattr(p, "part_kind", "") == "tool-return"
                for m in messages
                for p in getattr(m, "parts", [])
            )
            if has_return:
                yield "没有任务"
            else:
                yield {
                    0: DeltaToolCall(
                        name="bacmap_list_tasks", json_args='{"limit": 5}'
                    )
                }

        home = tmp_path / "home"
        home.mkdir()
        _, orch, actor = _backend(home, stream_fn)

        async def go():
            with ChatStore(home / "data" / "bacmap.sqlite") as store:
                session = store.create_session(actor.user_id)
            events = await _collect(orch.stream_run(session.session_id, "任务？", actor))
            return session, events

        session, events = _run(go())
        types_seen = [e.type for e in events]
        assert "TOOL_CALL_START" in types_seen
        assert "TOOL_CALL_ARGS" in types_seen
        assert "TOOL_CALL_END" in types_seen
        assert "TOOL_CALL_RESULT" in types_seen
        start = next(e for e in events if e.type == "TOOL_CALL_START")
        assert start.tool_call_name == "bacmap_list_tasks"
        with ChatStore(home / "data" / "bacmap.sqlite") as store:
            messages = store.list_messages(session.session_id, actor.user_id)
        assistant = messages[-1]
        assert assistant.tool_calls[0]["name"] == "bacmap_list_tasks"
        assert "items" in assistant.tool_calls[0]["result"]

    def test_create_plan_emits_card_awaiting_confirmation(self, tmp_path):
        from pydantic_ai.models.function import DeltaToolCall

        async def stream_fn(messages, info):
            has_return = any(
                getattr(p, "part_kind", "") == "tool-return"
                for m in messages
                for p in getattr(m, "parts", [])
            )
            if has_return:
                yield "计划已创建，请在控制台确认"
            else:
                yield {
                    0: DeltaToolCall(
                        name="bacmap_create_plan",
                        json_args=json.dumps(
                            {
                                "tasks": [{"task_type": "analyze", "samples": ["S1"]}],
                                "rationale": "test",
                            }
                        ),
                    )
                }

        home = tmp_path / "home"
        home.mkdir()
        _, orch, actor = _backend(home, stream_fn)

        async def go():
            with ChatStore(home / "data" / "bacmap.sqlite") as store:
                session = store.create_session(actor.user_id)
            events = await _collect(orch.stream_run(session.session_id, "分析 S1", actor))
            return session, events

        session, events = _run(go())
        cards = [
            e for e in events
            if e.type == "CUSTOM" and e.name == "bacmap.plan_card"
        ]
        assert len(cards) == 1
        card = cards[0].value
        assert card["state"] == "awaiting_confirmation"
        assert card["can_confirm"] is True
        assert card["tasks"][0]["task_type"] == "analyze"
        with ChatStore(home / "data" / "bacmap.sqlite") as store:
            messages = store.list_messages(session.session_id, actor.user_id)
        assert any(c.get("plan_id") == card["plan_id"] for c in messages[-1].cards)

    def test_user_role_cannot_create_mine_plan(self, tmp_path):
        from pydantic_ai.models.function import DeltaToolCall

        async def stream_fn(messages, info):
            has_return = any(
                getattr(p, "part_kind", "") == "tool-return"
                for m in messages
                for p in getattr(m, "parts", [])
            )
            if has_return:
                yield "被拒绝"
            else:
                yield {
                    0: DeltaToolCall(
                        name="bacmap_create_plan",
                        json_args=json.dumps(
                            {
                                "tasks": [
                                    {
                                        "task_type": "mine",
                                        "objective": "x",
                                        "script": "print(1)",
                                    }
                                ]
                            }
                        ),
                    )
                }

        home = tmp_path / "home"
        home.mkdir()
        user_actor = _actor(
            user_id="u_alice", username="alice", role="user",
            can_read_all=False, can_confirm_plans=False, is_admin=False,
        )
        _, orch, actor = _backend(home, stream_fn, actor=user_actor)

        async def go():
            with ChatStore(home / "data" / "bacmap.sqlite") as store:
                session = store.create_session(actor.user_id)
            events = await _collect(orch.stream_run(session.session_id, "mine", actor))
            return events

        events = _run(go())
        result = next(e for e in events if e.type == "TOOL_CALL_RESULT")
        assert "只能创建 analyze/reanalyze" in result.content
        assert not [
            e for e in events if e.type == "CUSTOM" and e.name == "bacmap.plan_card"
        ]

    def test_data_class_filtering_cloud_d1(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        backend, _, actor = _backend(
            home,
            _never_called,
            llm_config=_llm_config(location="cloud", cloud_max=DataClass.D1),
        )
        endpoint, ceiling = backend.resolve_chat_endpoint()
        assert endpoint.location == "cloud" and ceiling == DataClass.D1
        ctx = _ctx(actor)
        tools = backend._build_tools(ctx, ceiling, [])
        names = {t.name for t in tools}
        # D2/D3/D4 工具被隐藏；D0 工具保留
        assert "bio_get_result" not in names
        assert "bio_query_metadata" not in names
        assert "bio_seq_stats" not in names
        assert "bio_list_samples" not in names
        assert "bio_diagnose" in names
        assert "bio_list_reference_genomes" in names

    def test_local_endpoint_keeps_d2_tools(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        backend, _, actor = _backend(home, _never_called)
        _ep, ceiling = backend.resolve_chat_endpoint()
        assert ceiling == DataClass.D4  # ai_max 默认 D4，local 无位置收紧
        tools = backend._build_tools(_ctx(actor), ceiling, [])
        names = {t.name for t in tools}
        assert "bio_get_result" in names
        assert "bio_list_samples" in names

    def test_user_role_tool_face(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        backend, _, _ = _backend(home, _never_called)
        user_actor = _actor(
            user_id="u_alice", username="alice", role="user",
            can_read_all=False, can_confirm_plans=False, is_admin=False,
        )
        _, ceiling = backend.resolve_chat_endpoint()
        tools = backend._build_tools(_ctx(user_actor), ceiling, [])
        names = {t.name for t in tools}
        assert "bio_list_samples" not in names
        assert "bio_get_result" not in names
        assert "bio_query_metadata" not in names
        assert "bacmap_my_samples" in names
        assert "bacmap_my_tasks" in names
        assert "bacmap_task_status" in names
        assert "bacmap_create_plan" in names
        # 管理员面
        admin_tools = backend._build_tools(_ctx(_actor()), ceiling, [])
        admin_names = {t.name for t in admin_tools}
        assert "bacmap_list_tasks" in admin_names
        assert "bacmap_task_result" in admin_names
        assert "bacmap_my_samples" not in admin_names

    def test_user_task_status_owner_isolation(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        backend, _, _ = _backend(home, _never_called)
        engine = backend._engine
        engine.get_task = lambda tid: {"task_id": tid, "submitted_by": "bob"}
        user_actor = _actor(
            user_id="u_alice", username="alice", role="user",
            can_read_all=False, can_confirm_plans=False, is_admin=False,
        )
        _, ceiling = backend.resolve_chat_endpoint()
        tools = {t.name: t for t in backend._build_tools(_ctx(user_actor), ceiling, [])}
        out = json.loads(tools["bacmap_task_status"].function(task_id="t1"))
        assert out == {"error": "task not found"}
        engine.get_task = lambda tid: {"task_id": tid, "submitted_by": "alice"}
        st = types.SimpleNamespace(model_dump=lambda mode: {"state": "running"})
        engine.status = lambda tid: st
        out = json.loads(tools["bacmap_task_status"].function(task_id="t1"))
        assert out["state"] == "running"

    def test_endpoint_unavailable_run_error(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        empty = LlmConfig(endpoints={}, routing={})

        async def stream_fn(messages, info):
            yield "x"

        engine = _stub_engine(home)
        from pydantic_ai.models.function import FunctionModel

        backend = BuiltinChatBackend(
            home, engine, empty, WebChatConfig().builtin,
            model_override=FunctionModel(stream_function=stream_fn),
        )
        actor = _actor()

        async def go():
            return await _collect(backend.run_stream(_ctx(actor)))

        events = _run(go())
        assert events[-1].type == "RUN_ERROR"
        assert events[0].type == "RUN_STARTED"


async def _never_called(messages, info):
    yield "never"  # pragma: no cover


def _run(coro):
    import asyncio

    return asyncio.run(coro)
