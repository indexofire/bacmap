"""开发调试模式：明确的放宽面与仍然保留的数据红线。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.config import debug_mode
from bacmap.research.models import Claim, ClaimType, EvidenceLevel


@pytest.fixture
def debug(monkeypatch):
    monkeypatch.setenv("BACMAP_DEBUG", "1")
    return monkeypatch


class TestDebugFlag:
    def test_debug_mode_values(self, monkeypatch):
        for value in ("1", "true", "yes", "on", "TRUE"):
            monkeypatch.setenv("BACMAP_DEBUG", value)
            assert debug_mode() is True
        for value in ("0", "false", "off"):
            monkeypatch.setenv("BACMAP_DEBUG", value)
            assert debug_mode() is False
        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        assert debug_mode() is False

    def test_debug_mode_from_config(self, monkeypatch, tmp_path: Path):
        import bacmap.config as config

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        (tmp_path / "config.toml").write_text(
            "[debug]\nenabled = true\n", encoding="utf-8"
        )
        assert debug_mode() is True

    def test_env_can_disable_config_debug(self, monkeypatch, tmp_path: Path):
        import bacmap.config as config

        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        (tmp_path / "config.toml").write_text(
            "[debug]\nenabled = true\n", encoding="utf-8"
        )
        monkeypatch.setenv("BACMAP_DEBUG", "0")
        assert debug_mode() is False

    def test_malformed_debug_config_means_off(self, monkeypatch, tmp_path: Path):
        import bacmap.config as config

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        (tmp_path / "config.toml").write_text("not valid ==", encoding="utf-8")
        assert debug_mode() is False


class TestWebDebug:
    def test_web_auth_disabled(self, debug):
        from bacmap.interfaces.web.auth import WebAuthConfig

        cfg = WebAuthConfig.from_env("secret")
        assert cfg.enabled is False

    def test_exposed_bind_allowed(self, debug):
        from bacmap.interfaces.web.auth import require_auth_when_exposed

        require_auth_when_exposed("192.0.2.1", None)  # must not raise

    def test_exposed_bind_still_rejected_without_debug(self, monkeypatch):
        from bacmap.interfaces.web.auth import require_auth_when_exposed

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        with pytest.raises(SystemExit):
            require_auth_when_exposed("192.0.2.1", None)


class TestMcpDebug:
    def test_debug_does_not_raise_cloud_ceiling(self, debug, tmp_path: Path):
        from bacmap.interfaces.mcp.profiles import resolve_profile
        from bacmap.tools.spec import DataClass

        profile = resolve_profile("cloud", tmp_path, "stdio")
        assert profile.max_data_class is DataClass.D1

    def test_debug_does_not_enable_local_trusted(self, debug, tmp_path: Path):
        from bacmap.interfaces.mcp.profiles import ProfileNotAllowedError, resolve_profile

        with pytest.raises(ProfileNotAllowedError):
            resolve_profile("local-trusted", tmp_path, "stdio")

    def test_local_trusted_still_requires_config_without_debug(self, monkeypatch, tmp_path):
        from bacmap.interfaces.mcp.profiles import ProfileNotAllowedError, resolve_profile

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        with pytest.raises(ProfileNotAllowedError):
            resolve_profile("local-trusted", tmp_path, "stdio")

    def test_default_profile_stays_d1_in_debug(self, debug):
        from bacmap.interfaces.mcp.server import _default_profile
        from bacmap.tools.spec import DataClass

        assert _default_profile().max_data_class is DataClass.D1

    def test_mcp_http_requires_token_in_debug(self, debug):
        from bacmap.interfaces.mcp.http import build_http_app
        from bacmap.interfaces.mcp.server import build_server

        with pytest.raises(ValueError, match="Bearer token"):
            build_http_app(build_server(), token="")


class TestGatesAndResearchDebug:
    def test_gates_pass_in_debug(self, debug):
        from bacmap.tasks import gates

        assert gates.evaluate_mining({"artifacts": [], "signed_by": None}).verdict.value == "pass"
        assert gates.evaluate_citation({"draft": "PMID:99999999"}).verdict.value == "pass"
        assert gates.evaluate_analysis_claims("contradiction", {}, "S1").verdict.value == "pass"

    def test_claim_gate_bypassed(self, debug):
        from bacmap.research.claims import validate_claim

        claim = Claim(
            claim_id="c1", study_id="s1", claim_type=ClaimType.MECHANISM,
            wording="gene causes resistance", evidence_level=EvidenceLevel.E0,
        )
        validate_claim(claim, "approve")  # must not raise

    def test_publication_gate_bypassed(self, debug, tmp_path: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(tmp_path)
        study = svc.create_study("q", "", 2, "t")
        out = svc.publication_readiness(study.study_id)
        assert out["ready"] is True and out["debug_bypass"] is True


class TestDoctorDebug:
    def test_doctor_warns_in_debug(self, debug, tmp_path: Path):
        from bacmap.interfaces.cli.ops import collect_checks

        checks = collect_checks(tmp_path)
        assert any(c["name"] == "debug" and c["status"] == "warn" for c in checks)

    def test_doctor_warns_for_config_debug(self, monkeypatch, tmp_path: Path):
        import bacmap.config as config
        from bacmap.interfaces.cli.ops import collect_checks

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        (tmp_path / "config.toml").write_text(
            "[debug]\nenabled = true\n", encoding="utf-8"
        )
        checks = collect_checks(tmp_path)
        assert any(c["name"] == "debug" and c["status"] == "warn" for c in checks)

    def test_doctor_silent_without_debug(self, monkeypatch, tmp_path: Path):
        from bacmap.interfaces.cli.ops import collect_checks

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        assert all(c["name"] != "debug" for c in collect_checks(tmp_path))


class TestSandboxDebug:
    def test_debug_implies_unsandboxed(self, debug):
        from bacmap.agent.sandbox import SandboxExecutor

        assert SandboxExecutor(runners=[]).backend_name() == "direct"

    def test_no_debug_stays_unavailable(self, monkeypatch):
        from bacmap.agent.sandbox import SandboxExecutor

        monkeypatch.delenv("BACMAP_DEBUG", raising=False)
        monkeypatch.delenv("BACMAP_ALLOW_UNSANDBOXED", raising=False)
        assert SandboxExecutor(runners=[]).backend_name() == "unavailable"


class TestPlanAutoConfirm:
    def test_debug_auto_confirms_and_submits(self, debug, tmp_path: Path):
        from bacmap.application.plans import PlanService, PlanState
        from bacmap.tasks.params import AnalyzeParams

        class FakeEngine:
            def __init__(self):
                self.calls = []

            def submit(self, task_type, params, submitted_by, task_id=None):
                self.calls.append((task_type, params, submitted_by, task_id))

        from typing import cast

        from bacmap.tasks.spec import TaskEngine

        engine = FakeEngine()
        service = PlanService(cast(TaskEngine, engine), tmp_path / "tasks.sqlite")
        rec = service.create([AnalyzeParams(samples=["S1"])], "debug", "tester")
        assert rec.state is PlanState.SUBMITTED
        assert rec.confirmed_by == "policy:debug-auto-confirm"
        assert engine.calls and engine.calls[0][1]["samples"] == ["S1"]
