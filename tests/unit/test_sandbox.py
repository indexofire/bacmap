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

    def test_timeout_returns_result(self, tmp_path: Path):
        """深度审计修订：超时转为 SandboxResult(returncode=-1)而非裸抛——
        保留 stdout/stderr 诊断且不破坏调用方契约（sleep 5s 超 1s 真实触发）。"""
        result = SandboxExecutor(allow_unsandboxed=True, timeout=1).run(
            SandboxSpec(image="i", command=["sleep", "5"], workspace=tmp_path)
        )
        assert result.returncode != 0
        assert "timeout" in result.stderr.lower()


class TestSandboxHardening:
    """深度审计循环 6：超时不得抛 TimeoutExpired 破坏 SandboxResult 契约；
    工作区路径含空格时直通模式必须仍能正确 cd。"""

    def test_timeout_yields_result_not_exception(self, tmp_path, monkeypatch):
        import subprocess as sp

        monkeypatch.setenv("BACMAP_ALLOW_UNSANDBOXED", "1")
        from bacmap.agent.sandbox import SandboxExecutor, SandboxSpec

        spec = SandboxSpec(
            image="docker://python:3.12-slim",
            command=["sleep", "3"],
            workspace=tmp_path,
        )
        monkeypatch.setattr(
            sp, "run",
            lambda *a, **k: (_ for _ in ()).throw(
                sp.TimeoutExpired(cmd="sleep", timeout=1)
            ),
        )
        res = SandboxExecutor(timeout=1).run(spec)
        assert res.returncode != 0
        assert "timeout" in (res.stderr or "").lower()

    def test_workspace_with_space_unsandboxed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BACMAP_ALLOW_UNSANDBOXED", "1")
        from bacmap.agent.sandbox import SandboxExecutor, SandboxSpec

        ws = tmp_path / "my workspace"
        ws.mkdir()
        spec = SandboxSpec(
            image="docker://python:3.12-slim",
            command=["sh", "-c", "echo ok > marker.txt"],
            workspace=ws,
        )
        res = SandboxExecutor().run(spec)
        assert res.returncode == 0
        assert (ws / "marker.txt").is_file()
