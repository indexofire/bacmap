"""LLM 接入层与意图分类测试（ADR-08/09/10：分级拦截、重试降级、封闭集）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bacmap.agent.intent import IntentResult, IntentTask, classify_intent
from bacmap.agent.llm.endpoints import (
    DataPolicy,
    LlmConfig,
    LlmEndpoint,
    default_config,
    load_llm_config,
)
from bacmap.agent.llm.gateway import (
    DataClassViolationError,
    LlmGateway,
    LlmUnavailableError,
)
from bacmap.tools.spec import DataClass


class _FakeResult:
    def __init__(self, output):
        self.output = output


class _FakeAgent:
    def __init__(self, output=None, fail_times=0, exc=None):
        self.calls = 0
        self._output = output
        self._fail_times = fail_times
        self._exc = exc

    def run_sync(self, prompt):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc or RuntimeError("boom")
        return _FakeResult(self._output)


def _make_config(location: str = "local", cloud_max: int = 1) -> LlmConfig:
    return LlmConfig(
        endpoints={
            "e": LlmEndpoint(name="e", base_url="http://x/v1", model="m", location=location)
        },
        routing={"p": "e"},
        policy=DataPolicy(cloud_max_data_class=DataClass(cloud_max)),
    )


class TestEndpoints:
    def test_default_config_has_strata(self):
        cfg = default_config()
        assert "strata" in cfg.endpoints
        assert cfg.endpoints["strata"].location == "local"
        assert cfg.endpoints["strata"].max_concurrency == 1

    def test_load_toml_config(self, tmp_path: Path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            """
[llm.endpoints.glm_api]
kind = "openai_compatible"
location = "cloud"
base_url = "https://api.example.com/v1"
model = "glm-5.x"
api_key_env = "GLM_API_KEY"
enabled = false

[llm.endpoints.strata]
location = "local"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash"

[llm.routing]
intent_classifier = "strata"

[llm.data_policy]
cloud_max_data_class = "D1"
""",
            encoding="utf-8",
        )
        cfg = load_llm_config(cfg_file)
        assert set(cfg.endpoints) == {"glm_api", "strata"}
        assert cfg.endpoints["glm_api"].location == "cloud"
        assert cfg.endpoints["glm_api"].enabled is False
        assert cfg.routing["intent_classifier"] == "strata"

    def test_missing_file_returns_default(self, tmp_path: Path):
        cfg = load_llm_config(tmp_path / "nope.toml")
        assert "strata" in cfg.endpoints

    def test_resolve_by_purpose_prefers_routing(self):
        cfg = _make_config()
        assert cfg.resolve("p").name == "e"
        assert cfg.resolve("unknown") is not None  # 回退到首个可用端点


class TestGateway:
    def test_success_returns_output(self):
        want = IntentResult(tasks=[IntentTask(task_type="analyze", summary="跑样本")])
        agent = _FakeAgent(output=want)
        gw = LlmGateway(_make_config(), agent_factory=lambda ep, ot, _i=None: agent)
        out = gw.structured("p", "prompt", IntentResult)
        assert out is want
        assert agent.calls == 1

    def test_cloud_over_limit_refused_without_call(self):
        agent = _FakeAgent(output=IntentResult())
        gw = LlmGateway(
            _make_config(location="cloud", cloud_max=1), agent_factory=lambda ep, ot, _i=None: agent
        )
        with pytest.raises(DataClassViolationError):
            gw.structured("p", "prompt", IntentResult, data_class=DataClass.D3)
        assert agent.calls == 0  # 拒绝发生在发送之前（V9）

    def test_cloud_at_limit_allowed(self):
        want = IntentResult(tasks=[])
        agent = _FakeAgent(output=want)
        gw = LlmGateway(
            _make_config(location="cloud", cloud_max=1), agent_factory=lambda ep, ot, _i=None: agent
        )
        out = gw.structured("p", "prompt", IntentResult, data_class=DataClass.D1)
        assert out is want

    def test_local_endpoint_accepts_all_classes(self):
        want = IntentResult(tasks=[])
        agent = _FakeAgent(output=want)
        gw = LlmGateway(_make_config(location="local"), agent_factory=lambda ep, ot, _i=None: agent)
        out = gw.structured("p", "prompt", IntentResult, data_class=DataClass.D4)
        assert out is want

    def test_retry_then_success(self):
        want = IntentResult(tasks=[])
        agent = _FakeAgent(output=want, fail_times=1)
        gw = LlmGateway(_make_config(), agent_factory=lambda ep, ot, _i=None: agent)
        out = gw.structured("p", "prompt", IntentResult)
        assert out is want
        assert agent.calls == 2

    def test_retry_exhaustion_raises_unavailable(self):
        agent = _FakeAgent(output=None, fail_times=99)
        gw = LlmGateway(_make_config(), agent_factory=lambda ep, ot, _i=None: agent)
        with pytest.raises(LlmUnavailableError):
            gw.structured("p", "prompt", IntentResult)
        assert agent.calls == 3  # 首次 + 2 次重试（ADR-08）

    def test_no_endpoint_raises_unavailable(self):
        gw = LlmGateway(LlmConfig(), agent_factory=lambda ep, ot, _i=None: None)
        with pytest.raises(LlmUnavailableError, match="no enabled endpoint"):
            gw.structured("p", "prompt", IntentResult)


class TestIntent:
    def test_classify_returns_tasks(self):
        want = IntentResult(
            tasks=[
                IntentTask(task_type="analyze", summary="跑一遍"),
                IntentTask(task_type="write", summary="写简报"),
            ]
        )
        gw = LlmGateway(
            _make_config(), agent_factory=lambda ep, ot, _i=None: _FakeAgent(output=want)
        )
        result = classify_intent("把这批沙门菌跑一遍分析，然后写个简报", gw)
        assert result is not None
        assert [t.task_type for t in result.tasks] == ["analyze", "write"]

    def test_classify_degrades_to_none(self):
        gw = LlmGateway(
            _make_config(),
            agent_factory=lambda ep, ot, _i=None: _FakeAgent(output=None, fail_times=99),
        )
        assert classify_intent("随便什么", gw) is None  # C3：无 LLM 降级

    def test_task_type_closed_set(self):
        with pytest.raises(ValidationError):
            IntentTask(task_type="deploy")


class TestInterpretation:
    def test_generate_returns_output(self):
        from bacmap.agent.interpret import InterpretationOutput, generate_interpretation

        want = InterpretationOutput(
            interpretation_text="该株为沙门菌……", key_findings=["血清型 Typhimurium"]
        )
        gw = LlmGateway(
            _make_config(), agent_factory=lambda ep, ot, _i=None: _FakeAgent(output=want)
        )
        summary = {"sample": "SAM-001", "steps": {"species": {"verdict": "Salmonella"}}}
        out = generate_interpretation(summary, "SAM-001", gw)
        assert out is not None
        assert "沙门菌" in out.interpretation_text

    def test_generate_degrades_to_none(self):
        from bacmap.agent.interpret import generate_interpretation

        gw = LlmGateway(
            _make_config(),
            agent_factory=lambda ep, ot, _i=None: _FakeAgent(output=None, fail_times=99),
        )
        assert generate_interpretation({}, "SAM-1", gw) is None

    def test_cloud_d2_blocked_by_default_policy(self):
        from bacmap.agent.interpret import generate_interpretation
        from bacmap.agent.llm.gateway import DataClassViolationError

        gw = LlmGateway(
            _make_config(location="cloud", cloud_max=1),
            agent_factory=lambda ep, ot, _i=None: _FakeAgent(),
        )
        with pytest.raises(DataClassViolationError):
            generate_interpretation({"steps": {}}, "SAM-1", gw)  # D2 payload → cloud 拒绝


class TestArbitration:
    def test_memory_parsing(self):
        from bacmap.agent.llm.arbitration import available_memory_gb

        assert available_memory_gb() > 0  # 本机真实 /proc/meminfo

    def test_disabled_passthrough(self, monkeypatch):
        from bacmap.agent.llm.arbitration import StrataArbiter

        calls = []
        arb = StrataArbiter(enabled=False)
        monkeypatch.setattr(
            "bacmap.agent.llm.arbitration.available_memory_gb", lambda: 1.0
        )
        with arb.heavy_step():
            calls.append("step")
        assert calls == ["step"]

    def test_sufficient_memory_no_unload(self, monkeypatch):
        from bacmap.agent.llm.arbitration import StrataArbiter

        unloaded = []
        arb = StrataArbiter(enabled=True, min_free_gb=24.0)
        monkeypatch.setattr(arb, "_post", lambda path, timeout=60: unloaded.append(path))
        monkeypatch.setattr(
            "bacmap.agent.llm.arbitration.available_memory_gb", lambda: 50.0
        )
        with arb.heavy_step():
            pass
        assert unloaded == []

    def test_low_memory_unload_then_load(self, monkeypatch):
        from bacmap.agent.llm.arbitration import StrataArbiter

        calls = []
        arb = StrataArbiter(enabled=True, min_free_gb=24.0)
        monkeypatch.setattr(arb, "_post", lambda path, timeout=60: calls.append(path))
        monkeypatch.setattr(
            "bacmap.agent.llm.arbitration.available_memory_gb", lambda: 5.0
        )
        with arb.heavy_step():
            calls.append("step")
        assert calls == ["/unload", "step", "/load"]  # ADR-17 闭环


class TestEndpointValidation:
    """深度审计循环 6：location 自由字符串会让 ADR-16 云端门失效（"Cloud" 绕过）；
    未知键静默忽略掩盖拼写错误。"""

    def test_location_must_be_literal(self):
        from pydantic import ValidationError

        from bacmap.agent.llm.endpoints import LlmEndpoint

        for bad in ("Cloud", "cloud ", "CLOUD", "mars"):
            with pytest.raises(ValidationError):
                LlmEndpoint(name="x", base_url="http://u", model="m", location=bad)

    def test_unknown_config_keys_rejected(self):
        from pydantic import ValidationError

        from bacmap.agent.llm.endpoints import LlmEndpoint

        with pytest.raises(ValidationError):
            LlmEndpoint(name="x", base_url="http://u", model="m", max_concurency=4)
