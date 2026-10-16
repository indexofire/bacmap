"""沙箱执行工具（ADR-11 开放路径，L2）——让内置助手执行脚本、产出图表。

把智能体编写的 Python 脚本交给 ``SandboxExecutor`` 运行：
- 有 Apptainer/Podman → 容器内隔离执行；
- 无后端且 ``BACMAP_ALLOW_UNSANDBOXED=1`` → 受控直通（开发环境）；
- 否则返回显式错误（不静默降级）。

脚本工作区写入 ``context.json``（BACMAP_HOME / results 目录 / GOM 库路径），
脚本可据此定位数据；产物（PNG/CSV 等）落在工作区并在返回值中列出。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

_DESCRIPTION = (
    "在沙箱中执行一段 Python 脚本（无网络），用于深度数据挖掘与绘图。"
    "脚本应读取工作区中的 context.json 定位数据（results 目录/GOM 库），"
    "把图表（PNG）或表格（CSV）写到当前工作目录；返回 stdout/stderr 与产物清单。"
    "可反复调用以迭代（看图/看结果再改脚本）。"
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "script": {"type": "string", "description": "要执行的 Python 源码"},
        "description": {"type": "string", "description": "一句话说明脚本做什么（可选）"},
    },
    "required": ["script"],
}


def _sandbox_image() -> str:
    import os

    return os.environ.get("BACMAP_SANDBOX_IMAGE", "docker://python:3.12-slim")


def _context(workspace_root: Path) -> dict[str, Any]:
    from bacmap import config

    return {
        "BACMAP_HOME": str(config.BACMAP_HOME),
        "results_dir": str(config.RESULTS_DIR),
        "gom_db": str(config.GOM_DB),
        "runs_db": str(config.RUNS_DB),
    }


def run_script(workspace_root: Path, script: str, description: str = "") -> str:
    """同步执行（工具在线程中调用）。返回 JSON 字符串信封。"""
    from bacmap.agent.sandbox import SandboxExecutor, SandboxSpec, SandboxUnavailableError

    workdir = Path(workspace_root) / f"run-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "script.py").write_text(script, encoding="utf-8")
    (workdir / "context.json").write_text(
        json.dumps(_context(Path(workspace_root)), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    spec = SandboxSpec(
        image=_sandbox_image(),
        command=["python", "script.py"],
        workspace=workdir,
    )
    try:
        result = SandboxExecutor().run(spec)
    except SandboxUnavailableError as exc:
        return json.dumps({"error": f"沙箱不可用：{exc}"}, ensure_ascii=False)

    artifacts = [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(workdir.iterdir())
        if f.is_file() and f.name not in ("script.py", "context.json")
    ]
    return json.dumps(
        {
            "returncode": result.returncode,
            "backend": result.backend,
            "description": description,
            "workspace": str(workdir),
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "artifacts": artifacts,
        },
        ensure_ascii=False,
    )


def build_sandbox_tool(workspace_root: Path) -> Any:
    """构建 pydantic-ai 工具（异步包装，在线程中执行避免阻塞事件循环）。"""
    from pydantic_ai import Tool

    async def _sandbox_run(script: str, description: str = "") -> str:
        import anyio

        return await anyio.to_thread.run_sync(
            lambda: run_script(workspace_root, script, description)
        )

    return Tool.from_schema(
        _sandbox_run, name="sandbox_run", description=_DESCRIPTION, json_schema=_SCHEMA
    )
