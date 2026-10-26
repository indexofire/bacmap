"""v1.6（ADR-21）：内置会话助手彻底移除——模块、命令、页面、技能均不再存在。"""

from __future__ import annotations

import importlib

import pytest


def test_agent_session_module_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bacmap.agent.session")


def test_interface_assistant_module_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bacmap.interfaces.assistant")


def test_assistant_role_and_skill_gone(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "agent"
    assert not (root / "skills" / "assistant").exists()
    assert not (root / "roles" / "assistant.role.yaml").exists()


def test_role_list_has_no_assistant():
    from bacmap.agent import roledef

    roles = roledef.list_roles()
    assert "assistant" not in roles
    assert {"analyst", "curator", "miner", "writer"} <= set(roles)


def test_cli_has_no_ask_chat():
    from bacmap.interfaces.cli.main import build_parser

    parser = build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    assert actions and "ask" not in actions[0].choices and "chat" not in actions[0].choices


def test_web_has_no_assistant_template():
    from pathlib import Path

    tpl = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "interfaces" / "web"
    assert not (tpl / "templates" / "assistant.html").exists()


def test_llm_gateway_stays_in_agent_llm_only_for_in_task_agents():
    """任务内智能体（解读/沙箱）保留：agent.llm 仍是唯一 pydantic-ai 入口。"""
    from bacmap.agent import interpret

    assert interpret is not None


class TestV17Cleanup:
    """v1.6.1：仅被内置助手使用的代码清理（不可达的 pydantic-ai 工具层）。"""

    def test_assistant_only_modules_gone(self):
        for mod in (
            "bacmap.agent.intent",
            "bacmap.agent.sandbox.tool",
            "bacmap.agent.llm.tools",
        ):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(mod)

    def test_gateway_only_keeps_structured_output(self):
        from bacmap.agent.llm.gateway import LlmGateway

        assert hasattr(LlmGateway, "structured")
        for gone in ("run_agent", "run_agent_async", "run_agent_events_async", "structured_async"):
            assert not hasattr(LlmGateway, gone), gone

    def test_cli_has_no_stream_helper(self):
        from bacmap.interfaces import cli

        assert not hasattr(cli.main, "_stream_respond")
