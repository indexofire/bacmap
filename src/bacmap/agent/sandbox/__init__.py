"""沙箱执行器（ADR-11：开放路径 L2，智能体代码只在此运行）。

默认 Apptainer：``--containall --cleanenv --network none``；任务工作区
可读写、GOM 导出只读；宿主机无 Apptainer 时回退 rootless Podman
（``--network none``）。回退链：Apptainer → Podman。都不可用时拒绝执行，除非显式设置
BACMAP_ALLOW_UNSANDBOXED=1 才允许直接执行（仅受控开发，防静默降级）。
Docker 刻意不在链内（root 守护进程权限面，安装指南 §6）。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    allowed_readonly_roots: tuple[Path, ...] = ()  # fs_scope 白名单（D）

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.image or not self.command:
            raise ValueError("SandboxSpec 需要 image 与 command")
        if not self.workspace.is_dir():
            raise ValueError(f"workspace 不存在: {self.workspace}")
        if self.readonly_mounts:
            # D：只读挂载必须显式声明允许根，且宿主路径落在允许根内——否则越权。
            if not self.allowed_readonly_roots:
                raise ValueError("readonly_mounts 需要 allowed_readonly_roots（fs_scope 白名单）")
            roots = [Path(r).resolve() for r in self.allowed_readonly_roots]
            for host in self.readonly_mounts:
                host_p = Path(host).resolve()
                if not any(host_p == r or r in host_p.parents for r in roots):
                    raise ValueError(f"只读挂载越权（越出 fs_scope 允许根）: {host}")


def _which(binary: str) -> str | None:
    return shutil.which(binary, path=os.environ.get("PATH", ""))


def _normalize_image(image: str) -> str:
    """OCI 镜像引用归一化：``docker://x`` → ``x``（podman 用 registry:tag 形式）。"""
    return image[len("docker://") :] if image.startswith("docker://") else image


class ContainerRunner:
    """容器后端公共基类（build_cmd 由各后端实现；沙箱技术属冻结文档"可替换"列）。"""

    backend_name = "container"

    def build_cmd(self, spec: SandboxSpec) -> list[str]:  # pragma: no cover - 接口
        raise NotImplementedError


class ApptainerRunner(ContainerRunner):
    """Apptainer 后端（生信/HPC 标准，SIF 镜像离线分发）。"""

    backend_name = "apptainer"

    def build_cmd(self, spec: SandboxSpec) -> list[str]:
        cmd = ["apptainer", "exec", "--containall", "--cleanenv", "--network", "none"]
        cmd += ["--pwd", "/workspace"]
        cmd += ["--bind", f"{spec.workspace}:/workspace"]
        for host, guest in spec.readonly_mounts.items():
            cmd += ["--bind", f"{host}:{guest}:ro"]
        cmd += [spec.image, *spec.command]
        return cmd


class PodmanRunner(ContainerRunner):
    """rootless Podman 回退后端。"""

    backend_name = "podman"

    def build_cmd(self, spec: SandboxSpec) -> list[str]:
        cmd = ["podman", "run", "--rm", "--network=none"]
        cmd += ["-w", "/workspace"]
        cmd += ["-v", f"{spec.workspace}:/workspace:Z"]
        for host, guest in spec.readonly_mounts.items():
            cmd += ["-v", f"{host}:{guest}:ro,Z"]
        cmd += [_normalize_image(spec.image), *spec.command]
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
    """回退链：Apptainer → Podman →（显式开启时）直接执行（Docker 刻意不在链内）。"""

    def __init__(
        self,
        allow_unsandboxed: bool | None = None,
        runners: list[ContainerRunner] | None = None,
        timeout: int = 3600,
    ) -> None:
        if allow_unsandboxed is None:
            allow_unsandboxed = os.environ.get("BACMAP_ALLOW_UNSANDBOXED") == "1"
        self._allow_unsandboxed = allow_unsandboxed
        if runners is None:
            runners = [ApptainerRunner(), PodmanRunner()]
        self._runners = runners
        self.timeout = timeout

    def _pick_runner(self) -> tuple[ContainerRunner, None] | tuple[None, str]:
        for runner in self._runners:
            binary = runner.backend_name
            if _which(binary):
                return runner, None
            logger.info("sandbox backend %s not found on PATH", binary)
        return None, "no apptainer/podman on PATH"

    def backend_name(self) -> str:
        """会在实际执行时使用的后端名（不执行）：apptainer/podman/direct/unavailable。

        用于在写 ``context.json`` 前决定用 guest 路径还是宿主路径。
        """
        runner, _ = self._pick_runner()
        if runner is not None:
            return runner.backend_name
        return "direct" if self._allow_unsandboxed else "unavailable"

    def run(self, spec: SandboxSpec) -> SandboxResult:
        """在工作区内以 container 内路径执行 command（cwd=/workspace）。"""
        spec.validate()
        runner, reason = self._pick_runner()
        if runner is None:
            if self._allow_unsandboxed:
                logger.warning("SANDBOX BYPASSED (BACMAP_ALLOW_UNSANDBOXED=1)——仅限受控开发环境")
                # 容器命令用镜像内的 `python`；直通时映射为本机解释器。
                cmd = list(spec.command)
                if cmd and cmd[0] in ("python", "python3"):
                    cmd[0] = sys.executable
                return _run(cmd, self.timeout, cwd=spec.workspace)
            raise SandboxUnavailableError(
                f"{reason}; 安装 Apptainer/Podman（见安装指南 §6），或设置 "
                "BACMAP_ALLOW_UNSANDBOXED=1（不推荐）"
            )
        host_cmd = runner.build_cmd(spec)
        result = _run(host_cmd, self.timeout)
        return SandboxResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            backend=runner.backend_name,
        )


def run_in_sandbox(spec: SandboxSpec, **executor_kwargs: Any) -> SandboxResult:
    """便捷入口。"""
    return SandboxExecutor(**executor_kwargs).run(spec)
