"""沙箱执行器测试（ADR-11：回退链、命令构建、非沙箱拒绝）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.agent.sandbox import (
    ApptainerRunner,
    PodmanRunner,
    SandboxExecutor,
    SandboxSpec,
    SandboxUnavailableError,
)


def _spec(tmp_path: Path) -> SandboxSpec:
    ws = tmp_path / "ws"
    ws.mkdir()
    return SandboxSpec(
        image="docker://alpine:3",
        command=["python", "script.py"],
        workspace=ws,
        readonly_mounts={"/data/gom-export": "/gom"},
    )


class TestCommandBuilding:
    def test_apptainer_cmd(self, tmp_path: Path):
        cmd = ApptainerRunner().build_cmd(_spec(tmp_path))
        assert cmd[:6] == [
            "apptainer", "exec", "--containall", "--cleanenv", "--network", "none",
        ]
        assert f"{tmp_path}/ws:/workspace" in cmd
        assert "/data/gom-export:/gom:ro" in cmd
        assert cmd[-2:] == ["python", "script.py"]

    def test_podman_cmd(self, tmp_path: Path):
        cmd = PodmanRunner().build_cmd(_spec(tmp_path))
        assert cmd[:3] == ["podman", "run", "--rm"]
        assert "--network=none" in cmd
        assert f"{tmp_path}/ws:/workspace:Z" in cmd
        assert "/data/gom-export:/gom:ro,Z" in cmd

    def test_spec_validation(self, tmp_path: Path):
        with pytest.raises(ValueError, match="image"):
            SandboxSpec(image="", command=["x"], workspace=tmp_path)
        with pytest.raises(ValueError, match="workspace"):
            SandboxSpec(image="i", command=["x"], workspace=tmp_path / "nope")


class TestFallbackChain:
    def test_no_backend_refuses_by_default(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("BACMAP_ALLOW_UNSANDBOXED", raising=False)
        monkeypatch.setattr("bacmap.agent.sandbox._which", lambda b: None)
        ex = SandboxExecutor()
        with pytest.raises(SandboxUnavailableError, match="BACMAP_ALLOW_UNSANDBOXED"):
            ex.run(_spec(tmp_path))

    def test_explicit_bypass_when_allowed(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("bacmap.agent.sandbox._which", lambda b: None)
        monkeypatch.setenv("BACMAP_ALLOW_UNSANDBOXED", "1")
        ex = SandboxExecutor(allow_unsandboxed=True)
        result = ex.run(SandboxSpec(image="i", command=["echo", "hi"], workspace=tmp_path))
        assert result.returncode == 0
        assert result.backend == "direct"

    def test_backend_selection(self, tmp_path: Path, monkeypatch):
        calls = []

        class _FakeRunner:
            backend_name = "fake"
            def build_cmd(self, spec: SandboxSpec) -> list[str]:
                calls.append("fake")
                return ["echo", "ok"]

        monkeypatch.setattr("bacmap.agent.sandbox._which", lambda b: "fake" == b or None)
        ex = SandboxExecutor(runners=[_FakeRunner()])  # type: ignore[list-item]
        result = ex.run(SandboxSpec(image="i", command=["x"], workspace=tmp_path))
        assert result.backend == "fake"
        assert calls == ["fake"]

    def test_timeout_propagates(self, tmp_path: Path):
        import subprocess

        with pytest.raises(subprocess.TimeoutExpired):
            SandboxExecutor(allow_unsandboxed=True, timeout=1).run(
                SandboxSpec(image="i", command=["sleep", "5"], workspace=tmp_path)
            )
