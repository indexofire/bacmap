"""P2 外部智能体适配器：ACP（stdio/HTTP）与 Pi RPC → 统一 AG-UI。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.agent.chat.acp import AcpHttpBackend, AcpStdioBackend
from bacmap.agent.chat.config import ExternalAgentConfig, WebChatConfig, load_chat_config
from bacmap.agent.chat.external import (
    check_external_availability,
    extract_bacmap_cards,
    format_prompt_with_context,
    resolve_external_command,
)
from bacmap.agent.chat.pi_rpc import PiRpcExternalBackend
from bacmap.agent.chat.service import ChatOrchestrator
from bacmap.agent.chat.types import ChatActor, ChatRunContext, PageContext
from bacmap.agent.llm.chat import BuiltinChatBackend
from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.interfaces.web import create_app
from bacmap.store.users import Role, UserService


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


async def _reap_pools() -> None:
    """收割池化外部子进程（kill+wait）。

    子进程 transport 绑定创建它的事件循环——必须在同一循环内、循环关闭前
    收割，否则 GC 时触发 "Event loop is closed" 告警并可能孤儿化进程。
    """
    from bacmap.agent.chat.acp import reap_acp_pool
    from bacmap.agent.chat.pi_rpc import reap_pi_pool

    await reap_acp_pool()
    await reap_pi_pool()


def _run(coro):
    """asyncio.run 的包装：在同一事件循环内先执行协程再收割进程池。"""
    async def _main():
        try:
            return await coro
        finally:
            await _reap_pools()

    return asyncio.run(_main())


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


def _ctx(session_id: str = "cs_ext", message: str = "你好", **overrides) -> ChatRunContext:
    base = {
        "session_id": session_id,
        "thread_id": session_id,
        "run_id": "run_t",
        "message": message,
        "history": [],
        "actor": _actor(),
        "backend_id": "ext",
    }
    base.update(overrides)
    return ChatRunContext(**base)


PLAN = {
    "plan_id": "plan_ext001",
    "version": 2,
    "plan_hash": "abcdef1234567890",
    "state": "awaiting_confirmation",
    "rationale": "外部代理创建",
    "tasks": [{"task_type": "analyze", "samples": ["S1"]}],
    "task_ids": [],
    "created_by": "dsh",
}

# ---- mock 外部进程脚本 ----------------------------------------------------------

ACP_MOCK = r'''
import json, os, sys

state_path = sys.argv[1]
mode = os.environ.get("MOCK_ACP_MODE", "basic")

def load():
    try:
        return json.load(open(state_path))
    except Exception:
        return {"initialize": 0, "session_new": 0, "permissions": []}

def save(st):
    json.dump(st, open(state_path, "w"))

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

session_id = "acp-test-session"
plan = json.loads(sys.argv[2])
pending_permissions = 0
pending_prompt_id = None

def maybe_finish_prompt():
    global pending_prompt_id
    if mode == "permission" and pending_permissions == 0 and pending_prompt_id is not None:
        send({"jsonrpc": "2.0", "id": pending_prompt_id, "result": {"stopReason": "end_turn"}})
        pending_prompt_id = None

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "method" not in msg:
        # 客户端对权限请求的响应
        if "result" in msg:
            st = load()
            outcome = msg["result"].get("outcome", {})
            st["permissions"].append(outcome.get("outcome", "unknown"))
            save(st)
            pending_permissions -= 1
            maybe_finish_prompt()
        continue
    method = msg["method"]
    if method == "initialize":
        st = load(); st["initialize"] += 1; save(st)
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": 1}})
    elif method == "session/new":
        st = load(); st["session_new"] += 1; save(st)
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": session_id}})
    elif method == "session/prompt":
        req = msg["id"]
        if mode == "permission":
            pending_permissions = 2
            pending_prompt_id = req
            send({"jsonrpc": "2.0", "id": 9001, "method": "session/request_permission",
                  "params": {"options": [{"optionId": "allow1", "kind": "allow_once"},
                                         {"optionId": "rej1", "kind": "reject_once"}],
                             "toolCall": {"title": "bacmap_list_species", "kind": "read"}}})
            send({"jsonrpc": "2.0", "id": 9002, "method": "session/request_permission",
                  "params": {"options": [{"optionId": "allow2", "kind": "allow_once"},
                                         {"optionId": "rej2", "kind": "reject_once"}],
                             "toolCall": {"title": "bash rm -rf /", "kind": "execute"}}})
        upd = lambda u: send({"jsonrpc": "2.0", "method": "session/update",
                              "params": {"sessionId": session_id, "update": u}})
        upd({"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "思考中"}})
        upd({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "好的"}})
        upd({"sessionUpdate": "tool_call", "toolCallId": "tc1", "title": "bacmap_create_plan",
             "rawInput": {"tasks": []}})
        upd({"sessionUpdate": "tool_call_update", "toolCallId": "tc1", "status": "completed",
             "rawOutput": json.dumps(plan)})
        if mode == "permission":
            maybe_finish_prompt()
        else:
            send({"jsonrpc": "2.0", "id": req, "result": {"stopReason": "end_turn"}})
    elif method == "session/cancel":
        pass
'''

PI_MOCK = r'''
import json, sys

state_path = sys.argv[1]
plan = json.loads(sys.argv[2])

def load():
    try:
        return json.load(open(state_path))
    except Exception:
        return {"prompts": 0}

def save(st):
    json.dump(st, open(state_path, "w"))

def emit(rec):
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    if rec.get("type") == "prompt":
        st = load(); st["prompts"] += 1; save(st)
        req_id = rec["id"]
        emit({"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "想"}})
        emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "答"}})
        emit({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_start", "toolCallId": "t1", "toolName": "bacmap_create_plan"}})
        emit({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_delta", "toolCallId": "t1", "delta": "{}"}})
        emit({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_end", "toolCallId": "t1"}})
        emit({"type": "tool_execution_end", "toolCallId": "t1", "toolName": "bacmap_create_plan",
              "result": {"content": [{"type": "text", "text": json.dumps(plan)}]}})
        emit({"type": "response", "id": req_id, "success": True})
        emit({"type": "agent_end", "willRetry": False})
        emit({"type": "agent_settled"})
    elif rec.get("type") == "abort":
        pass
'''


def _write_mock(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / name
    script.write_text(body)
    return script


def _types(events) -> list[str]:
    return [e.type for e in events]


class TestExtractCards:
    def test_plain_plan_json(self):
        events = extract_bacmap_cards("bacmap_create_plan", json.dumps(PLAN), can_confirm=True)
        cards = [e for e in events if e.name == "bacmap.plan_card"]
        assert len(cards) == 1
        assert cards[0].value["short_hash"] == "abcdef123456"
        assert cards[0].value["can_confirm"] is True

    def test_mcp_wrapped_content(self):
        wrapped = json.dumps(
            {"content": [{"type": "text", "text": json.dumps(PLAN)}]}
        )
        events = extract_bacmap_cards("bacmap_create_plan", wrapped, can_confirm=False)
        assert any(e.name == "bacmap.plan_card" for e in events)

    def test_plan_with_task_ids_emits_refs(self):
        plan = {**PLAN, "task_ids": ["t_a", "t_b"]}
        events = extract_bacmap_cards("bacmap_create_plan", json.dumps(plan), can_confirm=True)
        refs = [e for e in events if e.name == "bacmap.task_ref"]
        assert {r.value["task_id"] for r in refs} == {"t_a", "t_b"}

    def test_task_status_json(self):
        events = extract_bacmap_cards(
            "bacmap_task_status", json.dumps({"task_id": "t_x", "state": "running"}),
            can_confirm=False,
        )
        assert len(events) == 1
        assert events[0].value == {"task_id": "t_x", "state": "running"}

    def test_non_json_ignored(self):
        assert extract_bacmap_cards("x", "plain text output", can_confirm=True) == []
        assert extract_bacmap_cards("x", "", can_confirm=True) == []
        assert extract_bacmap_cards("x", "{broken", can_confirm=True) == []


class TestHelpers:
    def test_prompt_context(self):
        ctx = _ctx(page_context=PageContext(
            route="/samples/S1", entity_type="sample", entity_id="S1", title="样本"
        ))
        text = format_prompt_with_context(ctx)
        assert text.startswith("[bacmap context: sample S1 (/samples/S1)]")
        assert text.endswith("你好")
        plain = format_prompt_with_context(_ctx())
        assert plain == "你好"

    def test_default_commands(self):
        assert resolve_external_command(
            ExternalAgentConfig(id="p", name="P", protocol="pi-rpc")
        ) == ["pi", "--mode", "rpc"]
        assert resolve_external_command(
            ExternalAgentConfig(id="o", name="O", protocol="opencode")
        ) == ["opencode", "acp"]
        hermes = resolve_external_command(
            ExternalAgentConfig(id="h", name="H", protocol="hermes")
        )
        assert hermes[0] in ("hermes-acp", "hermes")
        assert resolve_external_command(
            ExternalAgentConfig(id="a", name="A", protocol="acp")
        ) == []
        explicit = resolve_external_command(
            ExternalAgentConfig(id="a", name="A", protocol="acp", command=["/bin/x", "y"])
        )
        assert explicit == ["/bin/x", "y"]

    def test_availability(self):
        ok, _ = check_external_availability(
            ExternalAgentConfig(id="x", name="X", protocol="acp", url="http://127.0.0.1:3080/")
        )
        assert ok is True
        ok, reason = check_external_availability(
            ExternalAgentConfig(id="x", name="X", protocol="acp")
        )
        assert ok is False and "command 或 url" in reason
        ok, reason = check_external_availability(
            ExternalAgentConfig(id="x", name="X", protocol="acp", command=["/nonexistent-bin-xyz"])
        )
        assert ok is False and "未找到外部命令" in reason
        ok, _ = check_external_availability(
            ExternalAgentConfig(id="x", name="X", protocol="acp", command=[sys.executable])
        )
        assert ok is True


async def _collect(backend, ctx):
    return [event async for event in backend.run_stream(ctx)]


class TestAcpStdio:
    def _cfg(self, tmp_path: Path, script: Path, *, auto: bool = False) -> ExternalAgentConfig:
        return ExternalAgentConfig(
            id="dsh", name="DSH", protocol="dsh",
            command=[sys.executable, str(script), str(tmp_path / "state.json"), json.dumps(PLAN)],
            auto_approve_permissions=auto,
        )

    def test_multi_turn_reuse_and_cards(self, tmp_path):
        script = _write_mock(tmp_path, "acp_mock.py", ACP_MOCK)
        cfg = self._cfg(tmp_path, script)

        async def run():
            backend = AcpStdioBackend(cfg, tmp_path)
            first = await _collect(backend, _ctx())
            second = await _collect(backend, _ctx(message="第二轮"))
            return first, second

        first, second = _run(run())
        types = _types(first)
        assert types[0] == "RUN_STARTED"
        assert "THINKING_TEXT_MESSAGE_CONTENT" in types
        assert "TEXT_MESSAGE_CONTENT" in types
        assert "TOOL_CALL_START" in types
        assert "TOOL_CALL_RESULT" in types
        assert types[-1] == "RUN_FINISHED"
        cards = [
            e for e in first
            if e.type == "CUSTOM" and e.name == "bacmap.plan_card"
        ]
        assert len(cards) == 1
        assert cards[0].value["plan_id"] == "plan_ext001"
        assert cards[0].value["can_confirm"] is True
        # 持久复用：两轮后 initialize/session/new 仍各一次
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["initialize"] == 1
        assert state["session_new"] == 1
        assert second[0].type == "RUN_STARTED"
        # 清理，避免泄漏子进程
        from bacmap.agent.chat.acp import close_acp_session

        close_acp_session(session_id="cs_ext")

    def test_permission_decisions_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOCK_ACP_MODE", "permission")
        script = _write_mock(tmp_path, "acp_mock.py", ACP_MOCK)
        cfg = self._cfg(tmp_path, script, auto=False)

        async def run():
            return await _collect(AcpStdioBackend(cfg, tmp_path), _ctx())

        events = _run(run())
        assert _types(events)[-1] == "RUN_FINISHED"
        decisions = json.loads((tmp_path / "state.json").read_text())["permissions"]
        assert decisions == ["selected", "selected"]
        # 第一个是 bacmap 只读（allow），第二个是破坏性 bash（reject）
        # 次序与 mock 发出顺序一致：allow 后 reject —— 由 optionId 区分在下面测试
        from bacmap.agent.chat.acp import close_acp_session

        close_acp_session(session_id="cs_ext")

    def test_permission_auto_approve(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOCK_ACP_MODE", "permission")
        script = _write_mock(tmp_path, "acp_mock.py", ACP_MOCK)
        cfg = self._cfg(tmp_path, script, auto=True)

        async def run():
            return await _collect(AcpStdioBackend(cfg, tmp_path), _ctx())

        events = _run(run())
        assert _types(events)[-1] == "RUN_FINISHED"
        from bacmap.agent.chat.acp import close_acp_session

        close_acp_session(session_id="cs_ext")


class TestPermissionDecision:
    def test_readonly_bacmap_allowed(self):
        from bacmap.agent.chat.acp import _decide_permission

        params = {
            "options": [
                {"optionId": "a1", "kind": "allow_once"},
                {"optionId": "r1", "kind": "reject_once"},
            ],
            "toolCall": {"title": "bacmap_list_species", "kind": "read"},
        }
        decision = _decide_permission(params, auto_approve=False)
        assert decision["outcome"]["optionId"] == "a1"

    def test_destructive_rejected_by_default(self):
        from bacmap.agent.chat.acp import _decide_permission

        params = {
            "options": [
                {"optionId": "a1", "kind": "allow_once"},
                {"optionId": "r1", "kind": "reject_once"},
            ],
            "toolCall": {"title": "bash rm -rf", "kind": "execute"},
        }
        decision = _decide_permission(params, auto_approve=False)
        assert decision["outcome"]["optionId"] == "r1"
        decision = _decide_permission(params, auto_approve=True)
        assert decision["outcome"]["optionId"] == "a1"


class TestAcpHttp:
    def test_http_sse_run(self, tmp_path):
        import httpx

        sse_lines = []

        def sse(obj):
            sse_lines.append(f"data: {json.dumps(obj)}")

        sse({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "http-session"}})
        sse({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "http-session",
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "HTTP 回复"}},
        }})
        sse({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "http-session",
            "update": {"sessionUpdate": "tool_call", "toolCallId": "tc9",
                       "title": "bacmap_create_plan"},
        }})
        sse({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "http-session",
            "update": {"sessionUpdate": "tool_call_update", "toolCallId": "tc9",
                       "status": "completed", "rawOutput": json.dumps(PLAN)},
        }})
        sse({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})
        sse_body = "\n\n".join(sse_lines) + "\n\n"

        seen = {"delete": False, "stream": False}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/acp":
                body = json.loads(request.content)
                if body.get("method") == "initialize":
                    return httpx.Response(
                        200,
                        json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
                        headers={"Acp-Connection-Id": "conn-1"},
                    )
                return httpx.Response(202)
            if request.method == "GET" and request.url.path == "/acp/stream":
                seen["stream"] = True
                assert request.headers.get("Acp-Connection-Id") == "conn-1"
                return httpx.Response(
                    200, headers={"Content-Type": "text/event-stream"}, content=sse_body.encode()
                )
            if request.method == "DELETE":
                seen["delete"] = True
                return httpx.Response(200)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        cfg = ExternalAgentConfig(
            id="dsh", name="DSH", protocol="dsh", url="http://127.0.0.1:3080/"
        )

        async def run():
            backend = AcpHttpBackend(cfg, tmp_path, transport=transport)
            return await _collect(backend, _ctx())

        events = _run(run())
        types = _types(events)
        assert types[0] == "RUN_STARTED"
        assert types[-1] == "RUN_FINISHED"
        assert any(
            e.type == "TEXT_MESSAGE_CONTENT" and "HTTP 回复" in e.delta for e in events
        )
        cards = [e for e in events if e.type == "CUSTOM" and e.name == "bacmap.plan_card"]
        assert len(cards) == 1
        assert seen["stream"] and seen["delete"]


class TestPiRpc:
    def test_stream_cards_and_reuse(self, tmp_path):
        script = _write_mock(tmp_path, "pi_mock.py", PI_MOCK)
        cfg = ExternalAgentConfig(
            id="pi", name="Pi", protocol="pi-rpc",
            command=[sys.executable, str(script), str(tmp_path / "pi_state.json"), json.dumps(PLAN)],
        )

        async def run():
            backend = PiRpcExternalBackend(cfg, tmp_path)
            first = await _collect(backend, _ctx())
            second = await _collect(backend, _ctx(message="第二轮"))
            return first, second

        first, _ = _run(run())
        types = _types(first)
        assert types[0] == "RUN_STARTED"
        assert types[-1] == "RUN_FINISHED"
        assert "THINKING_TEXT_MESSAGE_CONTENT" in types
        assert "TEXT_MESSAGE_CONTENT" in types
        assert "TOOL_CALL_START" in types
        assert "TOOL_CALL_RESULT" in types
        cards = [e for e in first if e.type == "CUSTOM" and e.name == "bacmap.plan_card"]
        assert len(cards) == 1
        state = json.loads((tmp_path / "pi_state.json").read_text())
        assert state["prompts"] == 2  # 同一持久进程处理两轮

        from bacmap.agent.chat.pi_rpc import close_pi_session

        close_pi_session(session_id="cs_ext")

    def test_turn_end_error_surfaces_as_run_error(self):
        """模型调用失败（stopReason=error）必须浮现为 RUN_ERROR，而非空回复。"""
        from bacmap.agent.chat.pi_rpc import PiRpcEventTranslator

        translator = PiRpcEventTranslator(can_confirm=False)
        events = translator.translate(
            {
                "type": "turn_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "provider": "zai-coding-cn",
                    "model": "glm-5.3",
                    "stopReason": "error",
                    "errorMessage": "401 unauthorized",
                },
            }
        )
        kinds = [e.type for e in events]
        assert "RUN_ERROR" in kinds
        error = next(e for e in events if e.type == "RUN_ERROR")
        assert "401 unauthorized" in error.message
        assert "zai-coding-cn/glm-5.3" in error.message

    def test_turn_end_normal_stop_is_silent(self):
        """正常收尾（stopReason=stop）不产生任何事件。"""
        from bacmap.agent.chat.pi_rpc import PiRpcEventTranslator

        translator = PiRpcEventTranslator(can_confirm=False)
        assert translator.translate(
            {"type": "turn_end", "message": {"role": "assistant", "stopReason": "stop"}}
        ) == []


# ---- Web API 集成 -----------------------------------------------------------------


def _csrf(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get("bacmap_csrf", "")}


class TestWebExternalModes:
    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(
            task_engine.DBOS, "start_workflow", lambda wf, p: p["task_id"]
        )
        monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
        home = tmp_path / "home"
        home.mkdir()
        yield home, tmp_path, monkeypatch
        eng.shutdown_dbos()

    def _app(self, home, tmp_path, monkeypatch, *, mode: str, auth: str = "") -> TestClient:
        from pydantic_ai.models.function import FunctionModel

        script = _write_mock(tmp_path, "acp_mock.py", ACP_MOCK)
        extra = (
            "\n[[web.chat.external]]\n"
            'id = "dsh"\nname = "DSH"\nprotocol = "dsh"\n'
            f'command = ["{sys.executable}", "{script}", "{tmp_path / "state.json"}", "{json.dumps(PLAN).replace(chr(34), chr(92)+chr(34))}"]\n'
            'allowed_roles = ["admin"]\n'
        )
        cfg_path = home / "config.toml"
        cfg_path.write_text(f'[web.chat]\nmode = "{mode}"\n{extra}')
        monkeypatch.setenv("BACMAP_CONFIG", str(cfg_path))
        if auth:
            monkeypatch.setenv("BACMAP_WEB_AUTH", auth)

        engine = eng.DbosTaskEngine(home)
        app = create_app(engine)

        async def _stream(messages, info):
            yield "内置回复"

        ep = LlmEndpoint(name="t", base_url="http://127.0.0.1:9/v1", model="m")
        llm = LlmConfig(endpoints={"t": ep}, routing={"chat": "t"})
        backend = BuiltinChatBackend(
            home, engine, llm, WebChatConfig().builtin,
            model_override=FunctionModel(stream_function=_stream),
        )
        orch = ChatOrchestrator(
            home, engine, load_chat_config(cfg_path),
            builtin_backend_factory=lambda: backend,
        )
        app.state.chat_orchestrator = orch
        return TestClient(app, base_url="http://127.0.0.1:8800")

    def test_mode_both_admin_sees_and_runs_external(self, env):
        home, tmp_path, monkeypatch = env
        client = self._app(home, tmp_path, monkeypatch, mode="both")
        caps = client.get("/api/v1/capabilities").json()
        ids = {b["id"]: b for b in caps["chat"]["backends"]}
        assert "builtin" in ids and "dsh" in ids
        assert ids["dsh"]["available"] is True
        assert ids["dsh"]["protocol"] == "dsh"

        sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
        run = client.post(
            f"/api/v1/chat/sessions/{sid}/run",
            json={"message": "你好", "backend_id": "dsh"},
        )
        assert run.status_code == 200
        assert "RUN_STARTED" in run.text
        assert "bacmap.plan_card" in run.text
        assert "RUN_FINISHED" in run.text
        # 持久化的 assistant 消息带外部卡片
        detail = client.get(f"/api/v1/chat/sessions/{sid}").json()
        assistant = detail["messages"][-1]
        assert assistant["backend_id"] == "dsh"
        assert any(c.get("kind") == "bacmap.plan_card" for c in assistant["cards"])

    def test_mode_both_user_role_cannot_use_external(self, env):
        home, tmp_path, monkeypatch = env
        client = self._app(home, tmp_path, monkeypatch, mode="both", auth="accounts")
        db = home / "data" / "bacmap.sqlite"
        with UserService(db) as users:
            users.create("admin", "admin-pass", Role.ADMIN)
            users.create("alice", "alice-pass", Role.USER)

        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-pass", "next": "/console/"},
        )
        assert resp.status_code == 200
        caps = client.get("/api/v1/capabilities").json()
        ids = [b["id"] for b in caps["chat"]["backends"]]
        assert "dsh" not in ids
        assert "builtin" in ids

        sid = client.post(
            "/api/v1/chat/sessions", json={}, headers=_csrf(client)
        ).json()["session_id"]
        run = client.post(
            f"/api/v1/chat/sessions/{sid}/run",
            json={"message": "hi", "backend_id": "dsh"},
            headers=_csrf(client),
        )
        assert run.status_code in (400, 403, 404)

    def test_mode_external_hides_builtin(self, env):
        home, tmp_path, monkeypatch = env
        client = self._app(home, tmp_path, monkeypatch, mode="external")
        caps = client.get("/api/v1/capabilities").json()
        ids = [b["id"] for b in caps["chat"]["backends"]]
        assert ids == ["dsh"]
