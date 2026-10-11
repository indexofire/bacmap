"""角色三文件体系测试（ADR-10/ADR-12：加载、system prompt 组装、MCP prompts 暴露）。"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from bacmap.agent import roledef
from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.agent.llm.gateway import LlmGateway
from bacmap.interfaces.mcp.server import build_server


class _Out(BaseModel):
    ok: bool = True


class _FakeAgent:
    def __init__(self, output: _Out | None = None) -> None:
        self._output = output or _Out()

    def run_sync(self, prompt: str) -> object:
        class _Result:
            output = self._output

        return _Result()


def _gateway(factory) -> LlmGateway:
    cfg = LlmConfig(
        endpoints={
            "strata": LlmEndpoint(
                name="strata", base_url="http://127.0.0.1:8080/v1", model="m"
            )
        },
        routing={"intent_classifier": "strata", "interpretation": "strata"},
    )
    return LlmGateway(cfg, agent_factory=factory)


class TestRoleDef:
    def test_list_roles_contains_analyst(self):
        assert "analyst" in roledef.list_roles()

    def test_all_six_roles_delivered_with_consistent_files(self):
        roles = roledef.list_roles()
        assert set(roles) >= {
            "analyst", "curator", "miner", "literature", "writer", "epidemiologist"
        }
        for r in roles:
            rd = roledef.load_role_def(r)
            assert rd.name == r
            assert rd.task_types
            sp = roledef.build_system_prompt(r)
            assert "全局原则" in sp and "权限边界" in sp

    def test_literature_role_network_with_low_data_class(self):
        rd = roledef.load_role_def("literature")
        assert rd.network is True
        assert rd.max_data_class == "D1"

    def test_load_analyst_manifest_fields(self):
        rd = roledef.load_role_def("analyst")
        assert rd.task_types == ["analyze"]
        assert rd.min_model_tier == "T1"
        assert "bio_get_result" in rd.tools
        assert rd.network is False

    def test_build_system_prompt_composition(self):
        sp = roledef.build_system_prompt("analyst")
        assert "全局原则" in sp
        assert "生信分析师" in sp
        assert "bio_get_result" in sp

    def test_missing_role_raises(self):
        with pytest.raises(FileNotFoundError):
            roledef.load_role_def("nonexistent")
        with pytest.raises(FileNotFoundError):
            roledef.load_skill("nonexistent")


class TestGatewayRoleWiring:
    def test_role_injects_system_instructions(self):
        captured: dict[str, str | None] = {}

        def factory(ep, ot, instructions=None):
            captured["instructions"] = instructions
            return _FakeAgent()

        gw = _gateway(factory)
        out = gw.structured("interpretation", "写解读", _Out, role="analyst")
        assert out.ok
        assert captured["instructions"] is not None
        assert "全局原则" in captured["instructions"]
        assert "生信分析师" in captured["instructions"]

    def test_no_role_means_no_instructions(self):
        captured: dict[str, str | None] = {}

        def factory(ep, ot, instructions=None):
            captured["instructions"] = instructions
            return _FakeAgent()

        gw = _gateway(factory)
        gw.structured("intent_classifier", "分类", _Out)
        assert captured["instructions"] is None

    def test_role_agents_cached_separately(self):
        created: list[str | None] = []

        def factory(ep, ot, instructions=None):
            created.append(instructions)
            return _FakeAgent()

        gw = _gateway(factory)
        gw.structured("interpretation", "a", _Out, role="analyst")
        gw.structured("interpretation", "a", _Out, role="analyst")
        assert len(created) == 1  # 同角色同输出类型 → 单实例（ADR-10 临时实例缓存）
        gw.structured("intent_classifier", "a", _Out)
        assert len(created) == 2  # 无角色 → 独立实例


class TestMcpRolePrompts:
    def test_role_prompt_exposed(self):
        prompts = asyncio.run(build_server().list_prompts())
        names = {p.name for p in prompts}
        assert "bacmap_role_analyst" in names

    def test_role_prompt_content(self):
        result = asyncio.run(build_server().get_prompt("bacmap_role_analyst", {}))
        text = str(result)
        assert "生信分析师" in text
