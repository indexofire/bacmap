"""沙箱执行器（ADR-11：开放路径 L2，智能体代码只在此运行）。

默认 Apptainer：``--containall --cleanenv --network none``；任务工作区
可读写、GOM 导出只读；宿主机无 Apptainer 时回退 rootless Podman
（``--network none``）。回退链：Apptainer → Podman → 直接执行（仅当
BACMAP_ALLOW_UNSANDBOXED=1 显式开启——默认拒绝，防静默降级）。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class SandboxUnavailableError(RuntimeError):
    """无可用沙箱后端且未显式允许非沙箱执行。"""


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    backend: str


@dataclass
class SandboxSpec:
    image: str
    command: list[str]
    workspace: Path                    # 任务工作区（可读写）
    readonly_mounts: dict[str, str] = field(default_factory=dict)  # 宿主路径 → 容器内挂载点

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.image or not self.command:
            raise ValueError("SandboxSpec 需要 image 与 command")
        if not self.workspace.is_dir():
            raise ValueError(f"workspace 不存在: {self.workspace}")


def _which(binary: str) -> str | None:
    return shutil.which(binary, path=os.environ.get("PATH", ""))


class ApptainerRunner:
    """Apptainer 后端（生信/HPC 标准，SIF 镜像离线分发）。"""

    backend_name = "apptainer"

    def build_cmd(self, spec: SandboxSpec) -> list[str]:
        cmd = ["apptainer", "exec", "--containall", "--cleanenv", "--network", "none"]
        cmd += ["--bind", f"{spec.workspace}:/workspace"]
        for host, guest in spec.readonly_mounts.items():
            cmd += ["--bind", f"{host}:{guest}:ro"]
        cmd += [spec.image, *spec.command]
        return cmd


class PodmanRunner:
    """rootless Podman 回退后端。"""

    backend_name = "podman"

    def build_cmd(self, spec: SandboxSpec) -> list[str]:
        cmd = ["podman", "run", "--rm", "--network=none"]
        cmd += ["-v", f"{spec.workspace}:/workspace:Z"]
        for host, guest in spec.readonly_mounts.items():
            cmd += ["-v", f"{host}:{guest}:ro,Z"]
        cmd += [spec.image, *spec.command]
        return cmd


def _run(cmd: list[str], timeout: int, cwd: Path | None = None) -> SandboxResult:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return SandboxResult(
            returncode=-1,
            stdout=out,
            stderr=f"[sandbox] timeout after {timeout}s",
            backend="direct",
        )
    return SandboxResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        backend="direct",
    )


class SandboxExecutor:
    """回退链：Apptainer → Podman →（显式开启时）直接执行。"""

    def __init__(
        self,
        allow_unsandboxed: bool | None = None,
        runners: list[ApptainerRunner | PodmanRunner] | None = None,
        timeout: int = 3600,
    ) -> None:
        if allow_unsandboxed is None:
            allow_unsandboxed = os.environ.get("BACMAP_ALLOW_UNSANDBOXED") == "1"
        self._allow_unsandboxed = allow_unsandboxed
        if runners is None:
            runners = [ApptainerRunner(), PodmanRunner()]  # type: ignore[list-item]
        self._runners = runners
        self.timeout = timeout

    def _pick_runner(self) -> tuple[ApptainerRunner | PodmanRunner, None] | tuple[None, str]:
        for runner in self._runners:
            binary = runner.backend_name
            if _which(binary):
                return runner, None
            logger.info("sandbox backend %s not found on PATH", binary)
        return None, "no apptainer/podman on PATH"

    def run(self, spec: SandboxSpec) -> SandboxResult:
        """在工作区内以 container 内路径执行 command（cwd=/workspace）。"""
        spec.validate()
        runner, reason = self._pick_runner()
        if runner is None:
            if self._allow_unsandboxed:
                logger.warning("SANDBOX BYPASSED (BACMAP_ALLOW_UNSANDBOXED=1)——仅限受控开发环境")
                return _run(list(spec.command), self.timeout, cwd=spec.workspace)
            raise SandboxUnavailableError(
                f"{reason}; 安装 Apptainer 或设置 BACMAP_ALLOW_UNSANDBOXED=1（不推荐）"
            )
        host_cmd = runner.build_cmd(spec)
        result = _run(host_cmd, self.timeout)
        return SandboxResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            backend=runner.backend_name,
        )


def run_in_sandbox(spec: SandboxSpec, **executor_kwargs: object) -> SandboxResult:
    """便捷入口。"""
    return SandboxExecutor(**executor_kwargs).run(spec)  # type: ignore[arg-type]
