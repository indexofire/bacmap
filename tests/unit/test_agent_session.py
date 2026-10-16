"""会话式分析助手（agent/session.py）与计划执行（interfaces/assistant.py）测试。

不依赖真实 LLM：用注入的 tool_agent_factory 返回罐头 AnalysisPlan。
"""

from __future__ import annotations

import json as _json

from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.agent.llm.gateway import LlmGateway
from bacmap.agent.session import (
    AgentSession,
    AnalysisPlan,
    PlannedTask,
    build_read_tools,
)
from bacmap.interfaces.assistant import execute_plan, format_plan


class _Result:
    def __init__(self, output, messages):
        self.output = output
        self._messages = messages

    def all_messages(self):
        return self._messages


class _FakeToolAgent:
    def __init__(self, output):
        self._output = output
        self.calls = 0

    def run_sync(self, prompt, message_history=None):
        self.calls += 1
        history = list(message_history or []) + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "done"},
        ]
        return _Result(self._output, history)


def _factory(output):
    return lambda ep, ot, instructions, tools: _FakeToolAgent(output)


def _cfg():
    return LlmConfig(
        endpoints={"e": LlmEndpoint(name="e", base_url="http://x/v1", model="m")},
        routing={"intent_classifier": "e"},
    )


class TestAgentSession:
    def test_plan_and_multi_turn_history(self):
        plan = AnalysisPlan(
            reply="好的",
            tasks=[PlannedTask(task_type="analyze", params={"samples": ["SAM-1"]})],
        )
        session = AgentSession(LlmGateway(_cfg(), tool_agent_factory=_factory(plan)))
        reply = session.respond("跑 SAM-1 的分析")
        assert reply.plan is not None
        assert reply.plan.tasks[0].task_type == "analyze"
        assert reply.plan.tasks[0].requires_confirmation is True
        assert session.history_length == 2
        session.respond("再按 ST 统计并画图")
        assert session.history_length == 4  # 续接前一轮

    def test_clarification_plan(self):
        plan = AnalysisPlan(reply="请提供样本 ID", needs_clarification=True)
        session = AgentSession(LlmGateway(_cfg(), tool_agent_factory=_factory(plan)))
        reply = session.respond("分析一下")
        assert reply.plan is not None and reply.plan.needs_clarification is True

    def test_degraded_when_no_endpoint(self):
        gw = LlmGateway(
            LlmConfig(endpoints={}, routing={}),
            tool_agent_factory=_factory(AnalysisPlan(reply="x")),
        )
        reply = AgentSession(gw).respond("hi")
        assert reply.degraded is True
        assert reply.plan is None

    def test_deep_mine_multi_task_plan(self):
        plan = AnalysisPlan(
            reply="分三步",
            tasks=[
                PlannedTask(task_type="mine", params={"script": "print(1)"}, rationale="统计"),
                PlannedTask(task_type="mine", params={"script": "print(2)"}, rationale="绘图"),
            ],
        )
        session = AgentSession(LlmGateway(_cfg(), tool_agent_factory=_factory(plan)))
        reply = session.respond("统计并画图")
        assert [t.task_type for t in reply.plan.tasks] == ["mine", "mine"]

    def test_build_read_tools(self):
        names = {t.name for t in build_read_tools()}
        assert "bio_list_samples" in names
        assert "bio_query_metadata" in names


class TestExecutePlan:
    def test_submits_each_task_in_order(self):
        seen: list[tuple[str, dict, str]] = []

        class _Engine:
            def submit(self, task_type, params, submitted_by):
                seen.append((str(task_type), params, submitted_by))
                return f"tid-{len(seen)}"

        plan = AnalysisPlan(
            reply="",
            tasks=[
                PlannedTask(task_type="analyze", params={"samples": ["S1"]}),
                PlannedTask(task_type="curate", params={}),
            ],
        )
        results = execute_plan(_Engine(), plan, submitted_by="test")
        assert [r["ok"] for r in results] == [True, True]
        assert [s[0] for s in seen] == ["analyze", "curate"]

    def test_invalid_task_reported_not_raised(self):
        class _Engine:
            def submit(self, task_type, params, submitted_by):
                raise ValueError("invalid sample id(s): ['../evil']")

        results = execute_plan(
            _Engine(),
            AnalysisPlan(reply="", tasks=[PlannedTask(task_type="analyze", params={})]),
        )
        assert results[0]["ok"] is False
        assert "invalid sample" in results[0]["error"]

    def test_format_plan(self):
        plan = AnalysisPlan(
            reply="",
            tasks=[
                PlannedTask(task_type="mine", rationale="按 ST 统计"),
                PlannedTask(task_type="write", rationale="写简报"),
            ],
        )
        text = format_plan(plan)
        assert "mine" in text and "按 ST 统计" in text and "write" in text


class TestBuildSessionGuardrail:
    def test_warns_on_home_mismatch(self, tmp_path, monkeypatch, caplog):
        import logging

        from bacmap import config as cfg
        from bacmap.interfaces.assistant import build_session

        monkeypatch.setattr(cfg, "BACMAP_HOME", tmp_path / "default-home")

        class _Engine:
            home = tmp_path / "other-home"

        with caplog.at_level(logging.WARNING):
            build_session(_Engine())  # type: ignore[arg-type]
        assert any("BACMAP_HOME" in r.message for r in caplog.records)

    def test_no_warning_when_same_home(self, tmp_path, monkeypatch, caplog):
        import logging

        from bacmap import config as cfg
        from bacmap.interfaces.assistant import build_session

        monkeypatch.setattr(cfg, "BACMAP_HOME", tmp_path)

        class _Engine:
            home = tmp_path

        with caplog.at_level(logging.WARNING):
            build_session(_Engine())  # type: ignore[arg-type]
        assert not any("read tools follow" in r.message for r in caplog.records)


class TestEndpointStatus:
    """端点状态行：让 TUI/CLI 用户看到是否连上 LLM（避免"看起来没连上"）。"""

    def test_not_connected(self, tmp_path, monkeypatch):
        import httpx

        from bacmap.interfaces.assistant import endpoint_status

        def _boom(*a, **k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "get", _boom)

        class _Engine:
            home = tmp_path

        status = endpoint_status(_Engine())  # type: ignore[arg-type]
        assert "未连接" in status and "strata" in status

    def test_connected(self, tmp_path, monkeypatch):
        import httpx

        from bacmap.interfaces.assistant import endpoint_status

        class _Resp:
            status_code = 200

        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())

        class _Engine:
            home = tmp_path

        assert "已连接" in endpoint_status(_Engine())  # type: ignore[arg-type]


class TestSandboxTool:
    """让 LLM 执行脚本/绘图：sandbox_run（ADR-11 L2）。"""

    def test_build_tool_named_sandbox_run(self, tmp_path):
        from bacmap.agent.sandbox.tool import build_sandbox_tool

        tool = build_sandbox_tool(tmp_path)
        assert tool.name == "sandbox_run"

    def test_session_includes_sandbox_tool(self, tmp_path):
        from bacmap.agent.sandbox.tool import build_sandbox_tool

        gw = LlmGateway(_cfg(), tool_agent_factory=_factory(AnalysisPlan(reply="x")))
        session = AgentSession(gw, extra_tools=[build_sandbox_tool(tmp_path)])
        names = {t.name for t in session._tools}
        assert "sandbox_run" in names and "bio_list_samples" in names

    def test_run_script_plotting_via_passthrough(self, tmp_path, monkeypatch):
        # 无 apptainer/podman：显式开启受控直通，脚本在本机 python 中绘图。
        monkeypatch.setenv("BACMAP_ALLOW_UNSANDBOXED", "1")
        from bacmap.agent.sandbox.tool import run_script

        script = (
            "import matplotlib; matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1,2,3],[1,4,9]); plt.savefig('plot.png')\n"
            "print('done')\n"
        )
        out = _json.loads(run_script(tmp_path, script, "plot"))
        assert out["returncode"] == 0, out
        assert any(a["name"] == "plot.png" and a["size"] > 0 for a in out["artifacts"])
        assert "done" in out["stdout"]

    def test_run_script_no_sandbox_is_explicit_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BACMAP_ALLOW_UNSANDBOXED", raising=False)

        import bacmap.agent.sandbox as sb
        from bacmap.agent.sandbox import SandboxUnavailableError
        from bacmap.agent.sandbox import tool as st

        class _Boom:
            def run(self, spec):
                raise SandboxUnavailableError("no apptainer/podman on PATH")

        monkeypatch.setattr(sb, "SandboxExecutor", lambda *a, **k: _Boom())
        out = _json.loads(st.run_script(tmp_path, "print(1)"))
        assert "error" in out and "沙箱不可用" in out["error"]


class TestAssistantRoleToolAlignment:
    """assistant.role.yaml 的工具白名单必须与实际会话工具一致（防漂移）。"""

    def test_role_tools_match_session_tools(self, tmp_path):
        from bacmap.agent import roledef
        from bacmap.agent.sandbox.tool import build_sandbox_tool
        from bacmap.agent.session import READ_TOOL_NAMES

        gw = LlmGateway(_cfg(), tool_agent_factory=_factory(AnalysisPlan(reply="x")))
        session = AgentSession(gw, extra_tools=[build_sandbox_tool(tmp_path)])
        session_names = {t.name for t in session._tools}
        role_tools = set(roledef.load_role_def("assistant").tools)
        assert role_tools == session_names
        assert set(READ_TOOL_NAMES) | {"sandbox_run"} == role_tools
