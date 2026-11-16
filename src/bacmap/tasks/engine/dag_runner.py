"""DAG 沙箱 runner（P4）：算子层只描述请求，容器/构建细节留在 tasks.engine。

为什么不在 research 层直接调用：ADR-02 契约禁止 research 导入 agent，
而沙箱执行器（Apptainer/Podman）属于 agent 层。executor 通过
``OperatorContext.runner`` 注入，测试可替换为假实现。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from bacmap.research.operators.spec import SandboxRequest, SandboxResult


def run_sandbox(request: SandboxRequest) -> SandboxResult:
    if request.kind == "build":
        return _build(request)
    return _run(request)


def _run(request: SandboxRequest) -> SandboxResult:
    from bacmap.agent.sandbox import SandboxExecutor, SandboxSpec

    spec = SandboxSpec(
        image=request.image,
        command=list(request.command),
        workspace=Path(request.workspace),
        readonly_mounts={},
        allowed_readonly_roots=(),
    )
    result = SandboxExecutor(timeout=request.timeout_s).run(spec)
    return SandboxResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        backend=result.backend,
    )


def _build(request: SandboxRequest) -> SandboxResult:
    """Podman 镜像构建（P4）：唯一允许联网的执行路径，白名单由配置决定。

    构建容器不挂载任何业务数据（context 只有 Dockerfile/脚本），分析节点仍
    以 ``--network none`` 运行。
    """
    if not shutil.which("podman"):
        return SandboxResult(
            returncode=127,
            stderr="podman not found; image build requires a container backend",
            backend="build",
        )
    workspace = Path(request.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    dockerfile = workspace / "Dockerfile"
    dockerfile.write_text(request.dockerfile, encoding="utf-8")

    network = "bridge" if request.network else "none"
    tag = request.tag or "bacmap-env:latest"
    cmd = [
        "podman",
        "build",
        f"--network={network}",
        "-t",
        tag,
        "-f",
        str(dockerfile),
        str(workspace),
    ]
    env = {**os.environ, **request.env}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=request.timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(
            returncode=-1,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=f"image build timed out after {request.timeout_s}s",
            backend="build",
        )
    image_id = ""
    if proc.returncode == 0:
        inspect = subprocess.run(
            ["podman", "image", "inspect", "--format", "{{.Id}}", tag],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if inspect.returncode == 0:
            image_id = inspect.stdout.strip()
    return SandboxResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        backend="build",
        image_id=image_id,
    )
