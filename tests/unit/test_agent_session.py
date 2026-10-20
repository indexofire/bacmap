"""会话式分析助手（agent/session.py）与计划执行（interfaces/assistant.py）测试。

不依赖真实 LLM：用注入的 tool_agent_factory 返回罐头 AnalysisPlan。
"""

from __future__ import annotations

import json as _json

import pytest

from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.agent.llm.gateway import LlmGateway
from bacmap.agent.session import (
    AgentSession,
    AnalysisPlan,
    PlannedTask,
    build_read_tools,
)
from bacmap.interfaces.assistant import PlanNotConfirmedError, execute_plan, format_plan


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
        history = [*(message_history or []),
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
        results = execute_plan(_Engine(), plan, submitted_by="test", confirmed=True)
        assert [r["ok"] for r in results] == [True, True]
        assert [s[0] for s in seen] == ["analyze", "curate"]

    def test_invalid_task_reported_not_raised(self):
        class _Engine:
            def submit(self, task_type, params, submitted_by):
                raise ValueError("invalid sample id(s): ['../evil']")

        results = execute_plan(
            _Engine(),
            AnalysisPlan(reply="", tasks=[PlannedTask(task_type="analyze", params={})]),
            confirmed=True,
        )
        assert results[0]["ok"] is False
        assert "invalid sample" in results[0]["error"]

    def test_unconfirmed_plan_is_refused(self):
        # requires_confirmation 的强制点：未经接口层确认的计划拒绝提交。
        class _Engine:
            def submit(self, task_type, params, submitted_by):  # pragma: no cover
                raise AssertionError("must not be called")

        with pytest.raises(PlanNotConfirmedError, match="human confirmation"):
            execute_plan(_Engine(), AnalysisPlan(reply="", tasks=[PlannedTask(task_type="mine")]))

    def test_confirmed_false_tasks_pass_without_confirmation(self):
        # 计划内所有任务都声明不需要确认时，可直接提交（读侧快速路径）。
        seen: list[str] = []

        class _Engine:
            def submit(self, task_type, params, submitted_by):
                seen.append(str(task_type))
                return "tid-1"

        plan = AnalysisPlan(
            reply="",
            tasks=[PlannedTask(task_type="analyze", params={}, requires_confirmation=False)],
        )
        results = execute_plan(_Engine(), plan)
        assert results[0]["ok"] is True and seen == ["analyze"]

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
            def backend_name(self):
                return "unavailable"

            def run(self, spec):
                raise SandboxUnavailableError("no apptainer/podman on PATH")

        monkeypatch.setattr(sb, "SandboxExecutor", lambda *a, **k: _Boom())
        out = _json.loads(st.run_script(tmp_path, "print(1)"))
        assert "error" in out and "沙箱不可用" in out["error"]


class TestHistoryBound:
    """无界历史的安全上界：按用户轮次裁剪，不拆散 tool-call/return 配对。"""

    class _Part:
        def __init__(self, kind: str) -> None:
            self.part_kind = kind

    class _Msg:
        def __init__(self, *kinds: str) -> None:
            self.parts = [TestHistoryBound._Part(k) for k in kinds]

    def test_trim_keeps_last_turns(self):
        from bacmap.agent.session import _is_user_prompt, _trim_history

        msgs = []
        for _ in range(20):
            msgs.append(self._Msg("user-prompt"))
            msgs.append(self._Msg("tool-call"))
            msgs.append(self._Msg("tool-return"))
        trimmed = _trim_history(msgs, max_turns=3)
        assert len(trimmed) == 9
        assert _is_user_prompt(trimmed[0])
        assert sum(1 for m in trimmed if _is_user_prompt(m)) == 3

    def test_trim_noop_below_cap(self):
        from bacmap.agent.session import _trim_history

        msgs = [self._Msg("user-prompt"), self._Msg("text")]
        assert _trim_history(msgs, max_turns=3) == msgs

    def test_build_prompt_truncates(self):
        from bacmap.agent.session import _MAX_PROMPT_CHARS, _build_prompt

        prompt = _build_prompt("x" * (_MAX_PROMPT_CHARS + 500), None)
        assert prompt == "用户请求：" + "x" * _MAX_PROMPT_CHARS


class TestAssistantRoleToolAlignment:
    """assistant.role.yaml 的工具白名单必须与实际会话工具一致（防漂移）。"""

    def test_role_tools_match_session_tools(self, tmp_path):
        from bacmap.agent import roledef
        from bacmap.agent.sandbox.tool import build_sandbox_tool, build_shell_tool
        from bacmap.agent.session import READ_TOOL_NAMES

        gw = LlmGateway(_cfg(), tool_agent_factory=_factory(AnalysisPlan(reply="x")))
        session = AgentSession(
            gw, extra_tools=[build_sandbox_tool(tmp_path), build_shell_tool(tmp_path)]
        )
        session_names = {t.name for t in session._tools}
        role_tools = set(roledef.load_role_def("assistant").tools)
        assert role_tools == session_names
        assert set(READ_TOOL_NAMES) | {"sandbox_run", "sandbox_shell"} == role_tools


class TestCloudAssistantBelt:
    """云端助手（v1.4.28）：工具带按云端上限裁剪，D3/D4 永不路由到 cloud。"""

    def test_belt_d2_excludes_d3_d4(self):
        from bacmap.agent.session import READ_TOOL_NAMES, session_belt
        from bacmap.tools.spec import DataClass

        names, dc = session_belt(DataClass.D2)
        assert set(names) <= set(READ_TOOL_NAMES)
        assert "bio_query_metadata" not in names  # D4（患者元数据）
        assert "bio_inspect_dataset" not in names  # D3（原始数据集）
        assert "bio_list_samples" in names  # D2（菌株级结果）在带内
        assert dc == DataClass.D2  # 会话级别 = 工具带最高级别

    def test_belt_d1_keeps_only_public_tools(self):
        from bacmap.agent.session import session_belt
        from bacmap.tools.spec import DataClass

        names, dc = session_belt(DataClass.D1)
        assert all(n in names for n in ("bio_list_reference_genomes", "bio_diagnose"))
        assert "bio_list_samples" not in names
        assert dc <= DataClass.D1

    def test_belt_d4_is_full_belt(self):
        from bacmap.agent.session import READ_TOOL_NAMES, session_belt
        from bacmap.tools.spec import DataClass

        names, dc = session_belt(DataClass.D4)
        assert set(names) == set(READ_TOOL_NAMES)
        assert dc == DataClass.D4

    def test_belt_never_empty(self):
        """任意上限下工具带非空（D0 工具恒在）——助手在云端不至失明。"""
        from bacmap.agent.session import session_belt
        from bacmap.tools.spec import DataClass

        for limit in DataClass:
            names, _dc = session_belt(limit)
            assert names, f"belt empty at {limit}"

    def test_cloud_belt_subset_of_role_tools(self):
        """云端工具带必须是角色白名单的子集（角色清单仍是权威边界）。"""
        from bacmap.agent import roledef
        from bacmap.agent.session import session_belt
        from bacmap.tools.spec import DataClass

        role_tools = set(roledef.load_role_def("assistant").tools)
        names, _dc = session_belt(DataClass.D2)
        assert set(names) <= role_tools


_CLOUD_CONFIG = """\
[llm.endpoints.glm]
location = "cloud"
base_url = "https://api.example.com/v1"
model = "glm-test"
api_key_env = "GLM_API_KEY"
tier = "T2"

[llm.routing]
intent_classifier = "glm"

[llm.data_policy]
cloud_max_data_class = "D2"
"""


class TestBuildSessionCloudBelt:
    """build_session 按端点位置选工具带：cloud 裁剪 + 排除沙箱工具。"""

    def test_cloud_session_trimmed(self, tmp_path, monkeypatch):
        from bacmap import config as cfg
        from bacmap.interfaces.assistant import build_session

        (tmp_path / "config.toml").write_text(_CLOUD_CONFIG, encoding="utf-8")
        monkeypatch.setattr(cfg, "BACMAP_HOME", tmp_path)

        class _Engine:
            home = tmp_path

        session = build_session(_Engine())  # type: ignore[arg-type]
        names = {t.name for t in session._tools}
        assert "bio_query_metadata" not in names
        assert "bio_inspect_dataset" not in names
        assert "bio_list_samples" in names
        assert "sandbox_run" not in names and "sandbox_shell" not in names
        from bacmap.tools.spec import DataClass

        assert session._data_class == DataClass.D2

    def test_local_session_full_belt(self, tmp_path, monkeypatch):
        from bacmap import config as cfg
        from bacmap.interfaces.assistant import build_session

        # 无 config.toml → 内置本地默认端点，全量工具带 + 沙箱。
        monkeypatch.setattr(cfg, "BACMAP_HOME", tmp_path)

        class _Engine:
            home = tmp_path

        session = build_session(_Engine())  # type: ignore[arg-type]
        names = {t.name for t in session._tools}
        assert "bio_query_metadata" in names
        assert "sandbox_run" in names and "sandbox_shell" in names
        from bacmap.tools.spec import DataClass

        assert session._data_class == DataClass.D4

    def test_cloud_session_passes_gateway_data_class_check(self):
        """裁剪后的 D2 会话在 cloud 端点 + D2 策略下通过网关校验（不再被拦截）。"""
        from bacmap.agent.llm.endpoints import DataPolicy
        from bacmap.agent.session import AgentSession, build_read_tools, session_belt
        from bacmap.tools.spec import DataClass

        gw = LlmGateway(
            LlmConfig(
                endpoints={
                    "glm": LlmEndpoint(
                        name="glm",
                        location="cloud",
                        base_url="https://api.example.com/v1",
                        model="glm-test",
                        tier="T2",
                    )
                },
                routing={"intent_classifier": "glm"},
                policy=DataPolicy(cloud_max_data_class=DataClass.D2),
            ),
            tool_agent_factory=_factory(AnalysisPlan(reply="x")),
        )
        names, dc = session_belt(DataClass.D2)
        session = AgentSession(gw, tools=build_read_tools(names), data_class=dc)
        reply = session.respond("列出所有样本")
        assert reply.degraded is False  # 未触发 DataClassViolationError（否则降级）
        assert reply.message == "x"


class TestReplyPrefixExtraction:
    """输出工具参数的 reply 增量提取（v1.4.31 流式展示的纯函数核心）。"""

    def test_key_absent(self):
        from bacmap.agent.llm.gateway import _extract_reply_prefix

        found, prefix = _extract_reply_prefix('{"other": "x", "tasks": []}')
        assert found is False and prefix == ""

    def test_partial_value(self):
        from bacmap.agent.llm.gateway import _extract_reply_prefix

        found, prefix = _extract_reply_prefix('{"reply": "沙门菌监')
        assert found is True and prefix == "沙门菌监"

    def test_complete_value(self):
        from bacmap.agent.llm.gateway import _extract_reply_prefix

        found, prefix = _extract_reply_prefix(
            '{"reply": "line1\\nline2", "needs_clarification": false, "tasks": []}'
        )
        assert found is True and prefix == "line1\nline2"

    def test_truncated_escape_waits(self):
        from bacmap.agent.llm.gateway import _extract_reply_prefix

        # 转义序列被增量截断：只显示已确定安全的前缀
        found, prefix = _extract_reply_prefix('{"reply": "ab\\')
        assert found is True and prefix == "ab"

    def test_unicode_escape_incomplete(self):
        from bacmap.agent.llm.gateway import _extract_reply_prefix

        found, prefix = _extract_reply_prefix('{"reply": "ab\\u4e2')
        assert found is True and prefix == "ab"

    def test_unicode_escape_complete(self):
        from bacmap.agent.llm.gateway import _extract_reply_prefix

        found, prefix = _extract_reply_prefix('{"reply": "\\u6c99"')
        assert found is True and prefix == "沙"


class TestRespondStream:
    """respond_stream：事件回调接线 + 降级语义 + 历史续接。"""

    def test_events_forwarded_and_reply_returned(self):
        import asyncio

        from bacmap.agent.llm.gateway import LlmGateway

        class _IterAgent:
            """支持 iter() 的罐头 agent：模拟一次成功的流式运行。"""

            def iter(self, prompt, message_history=None):
                import contextlib

                @contextlib.asynccontextmanager
                async def _cm():
                    class _Run:
                        result = type(
                            "R",
                            (),
                            {
                                "output": AnalysisPlan(reply="ok"),
                                "all_messages": staticmethod(lambda: []),
                            },
                        )()

                        def __aiter__(self):
                            return self

                        async def __anext__(self):
                            raise StopAsyncIteration

                    yield _Run()

                return _cm()

        events: list[tuple[str, str]] = []
        gw = LlmGateway(
            _cfg(),
            tool_agent_factory=lambda ep, ot, instructions, tools: _IterAgent(),
        )
        session = AgentSession(gw)

        async def go():
            async def on_event(kind, payload):
                events.append((kind, payload))

            return await session.respond_stream("hi", on_event)

        reply = asyncio.run(go())
        assert reply.message == "ok"
        # 罐头节点流为空：无事件但正常完成（接线不炸）
        assert events == []
        assert reply.degraded is False

    def test_degraded_when_stream_exhausted(self):
        import asyncio

        from bacmap.agent.llm.gateway import LlmGateway

        class _BrokenAgent:
            def iter(self, prompt, message_history=None):
                raise AttributeError("no iter support")

        gw = LlmGateway(
            _cfg(),
            tool_agent_factory=lambda ep, ot, instructions, tools: _BrokenAgent(),
        )
        session = AgentSession(gw)
        reply = asyncio.run(session.respond_stream("hi"))
        assert reply.degraded is True

    def test_respond_async_delegates_to_stream(self, monkeypatch):
        """respond_async 与 respond_stream 同路径（TUI 取消语义依赖同一入口）。"""
        import asyncio

        from bacmap.agent.llm.gateway import LlmGateway

        class _OkAgent:
            def iter(self, prompt, message_history=None):
                import contextlib

                @contextlib.asynccontextmanager
                async def _cm():
                    class _Run:
                        result = type(
                            "R",
                            (),
                            {
                                "output": AnalysisPlan(reply="via-async"),
                                "all_messages": staticmethod(lambda: []),
                            },
                        )()

                        def __aiter__(self):
                            return self

                        async def __anext__(self):
                            raise StopAsyncIteration

                    yield _Run()

                return _cm()

        gw = LlmGateway(
            _cfg(),
            tool_agent_factory=lambda ep, ot, instructions, tools: _OkAgent(),
        )
        session = AgentSession(gw)
        assert asyncio.run(session.respond_async("hi")).message == "via-async"
