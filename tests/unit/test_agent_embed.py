"""智能体对话嵌入（v1.10.24）：配置解析 + capabilities 暴露 + CSP frame-src。"""

from __future__ import annotations

from pathlib import Path

from bacmap.interfaces.web.agent_embed import AgentEmbed, load_agent_embeds


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


class TestLoadAgentEmbeds:
    def test_reads_embeds(self, tmp_path: Path):
        cfg = _write_config(
            tmp_path,
            '[[web.agent_embed]]\nname = "DSH"\nurl = "http://127.0.0.1:3080"\n'
            '[[web.agent_embed]]\nname = "Hermes"\nurl = "http://localhost:56791"\n',
        )
        embeds = load_agent_embeds(cfg)
        assert [e.name for e in embeds] == ["DSH", "Hermes"]
        assert embeds[0].origin == "127.0.0.1:3080"

    def test_no_config_returns_empty(self, tmp_path: Path):
        assert load_agent_embeds(tmp_path / "nope.toml") == []

    def test_non_loopback_entries_skipped(self, tmp_path: Path):
        """ADR-16：云托管智能体前端不可嵌入——单条非法不阻断其余。"""
        cfg = _write_config(
            tmp_path,
            '[[web.agent_embed]]\nname = "Cloud"\nurl = "https://chat.example.com"\n'
            '[[web.agent_embed]]\nname = "local"\nurl = "http://127.0.0.1:1"\n',
        )
        embeds = load_agent_embeds(cfg)
        assert [e.name for e in embeds] == ["local"]

    def test_validator_rejects_non_loopback(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AgentEmbed(name="x", url="https://evil.example.com")


class TestCspFrameSources:
    def test_csp_with_sources(self):
        from bacmap.interfaces._security import _csp_with_frame_sources

        csp = _csp_with_frame_sources(["127.0.0.1:3080"])
        assert "frame-src 'self' 127.0.0.1:3080" in csp
        assert csp.startswith("default-src 'self'")

    def test_csp_unchanged_without_sources(self):
        from bacmap.interfaces._security import CSP, _csp_with_frame_sources

        assert _csp_with_frame_sources([]) == CSP


class TestCapabilitiesExpose:
    def test_capabilities_lists_embeds(self, tmp_path, monkeypatch):
        """配置了嵌入时 capabilities 返回清单（前端侧边栏数据源）。"""
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web.app import create_app
        from bacmap.tasks.engine.task_engine import DbosTaskEngine

        engine = DbosTaskEngine(tmp_path)

        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[web.agent_embed]]\nname = "opencode"\nurl = "http://127.0.0.1:49374"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)
        app = create_app(engine)
        app.state.agent_embeds = load_agent_embeds(cfg)
        client = TestClient(app)
        caps = client.get("/api/v1/capabilities").json()
        assert caps["agent_embeds"] == [
            {"name": "opencode", "url": "http://127.0.0.1:49374"}
        ]
