"""沙箱执行工具（ADR-11 开放路径，L2）——让内置助手执行脚本、产出图表。

把智能体编写的 Python 脚本交给 ``SandboxExecutor`` 运行：
- 有 Apptainer/Podman → 容器内隔离执行，数据只读挂载到 ``/data``、``/input/<id>``；
- 无后端且 ``BACMAP_ALLOW_UNSANDBOXED=1`` → 受控直通（开发环境，context 用宿主路径）；
- 否则返回显式错误（不静默降级）。

脚本工作区写入 ``context.json``（backend / results_dir / gom_db / 数据集挂载点），
脚本据此定位数据；产物（PNG/CSV 等）落在工作区并在返回值中列出。
要访问用户给定的外部数据，先经 ``mine`` 任务登记（``input_paths``），再把 ``dataset_id``
传给本工具的 ``datasets``。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DESCRIPTION = (
    "在沙箱中执行一段 Python 脚本（无网络），用于深度数据挖掘与绘图。"
    "脚本从工作区 context.json 读取 backend / results_dir / gom_db / datasets 定位数据"
    "（容器内为挂载点 /data/*、/input/<id>；直通时为宿主路径）；"
    "把图表（PNG）或表格（CSV）写到当前工作目录；返回 stdout/stderr 与产物清单。"
    "可反复调用以迭代（看图/看结果再改脚本）。"
    "要访问用户给定的外部数据，先在 datasets 传入已登记的 dataset_id（见 bio_inspect_dataset）。"
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "script": {"type": "string", "description": "要执行的 Python 源码"},
        "description": {"type": "string", "description": "一句话说明脚本做什么（可选）"},
        "datasets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要只读挂载的已登记 dataset_id 列表（可选，见 bio_inspect_dataset）",
        },
    },
    "required": ["script"],
}


def _sandbox_image() -> str:
    import os

    return os.environ.get("BACMAP_SANDBOX_IMAGE", "docker://python:3.12-slim")


def _load_datasets(dataset_ids: list[str]) -> tuple[list[Any], str | None]:
    """按 id 取回已登记数据集；未知 id / 无 GOM 库 → (空, 错误信息)。"""
    from bacmap import config
    from bacmap.store.datasets import DatasetRegistry

    if not dataset_ids:
        return [], None
    if not config.GOM_DB.is_file():
        return [], "GOM 库不存在：无法解析 dataset_id（先经 mine 任务登记数据）"
    reg = DatasetRegistry(config.GOM_DB)
    try:
        out: list[Any] = []
        for did in dataset_ids:
            ds = reg.get(did)
            if ds is None:
                return [], f"未知 dataset_id：{did}（用 bio_inspect_dataset 查看已登记数据集）"
            out.append(ds)
        return out, None
    finally:
        reg.close()


def run_script(
    workspace_root: Path,
    script: str,
    description: str = "",
    datasets: list[str] | None = None,
) -> str:
    """同步执行（工具在线程中调用）。返回 JSON 字符串信封。"""
    from bacmap import config
    from bacmap.agent.sandbox import SandboxExecutor, SandboxSpec, SandboxUnavailableError
    from bacmap.agent.sandbox.access import allowed_roots, build_access

    registry_datasets, err = _load_datasets(datasets or [])
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    workdir = Path(workspace_root) / f"run-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "script.py").write_text(script, encoding="utf-8")

    executor = SandboxExecutor()
    backend = executor.backend_name()
    if backend == "unavailable":
        return json.dumps(
            {
                "error": "沙箱不可用：无 apptainer/podman 且未设置 "
                "BACMAP_ALLOW_UNSANDBOXED=1（不推荐）"
            },
            ensure_ascii=False,
        )

    mounts, context = build_access(
        backend,
        results_dir=config.RESULTS_DIR,
        gom_db=config.GOM_DB,
        datasets=registry_datasets,
    )
    (workdir / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    spec = SandboxSpec(
        image=_sandbox_image(),
        command=["python", "script.py"],
        workspace=workdir,
        readonly_mounts=mounts,
        allowed_readonly_roots=allowed_roots(
            results_dir=config.RESULTS_DIR, gom_db=config.GOM_DB, datasets=registry_datasets
        ),
    )
    try:
        result = executor.run(spec)
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
            "datasets": context["datasets"],
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "artifacts": artifacts,
        },
        ensure_ascii=False,
    )


def build_sandbox_tool(workspace_root: Path) -> Any:
    """构建 pydantic-ai 工具（异步包装，在线程中执行避免阻塞事件循环）。"""
    from pydantic_ai import Tool

    async def _sandbox_run(
        script: str, description: str = "", datasets: list[str] | None = None
    ) -> str:
        import anyio

        return await anyio.to_thread.run_sync(
            lambda: run_script(workspace_root, script, description, datasets)
        )

    return Tool.from_schema(
        _sandbox_run, name="sandbox_run", description=_DESCRIPTION, json_schema=_SCHEMA
    )


# ---------------------------------------------------------------------------
# sandbox_shell（方案 C，收窄形态）——通用 shell，但只在容器后端、只读/分析白名单内
# ---------------------------------------------------------------------------

_SHELL_DESCRIPTION = (
    "在沙箱内执行一条 shell 命令（无网络），用于在已挂载的数据上运行标准工具"
    "（ls/cat/grep/zcat/samtools/bcftools/seqkit/python 等）。"
    "命令的每个管道/命令段（含换行分隔）的命令词都必须命中只读/分析白名单，"
    "且不得含命令替换/反引号/-exec 等隐藏执行语法，否则会被拒绝——"
    "需要更高自由度时改为规划 mine 任务（经挖掘门 + 人工签字）。"
    "要访问用户给定的外部数据,先在 datasets 传已登记的 dataset_id。"
    "注意：白名单是**意图分类**而非安全边界（python 等图灵完备命令天然可做任意计算）；"
    "真正的边界是容器后端的 --network none 与只读挂载——直通模式仅限受控开发环境。"
)

_SHELL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要在沙箱内执行的 shell 命令"},
        "description": {"type": "string", "description": "一句话说明命令做什么（可选）"},
        "datasets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要只读挂载的已登记 dataset_id 列表（可选）",
        },
    },
    "required": ["command"],
}

# 只读/分析命令白名单（每个管道/连接段的命令词都必须命中）
_SHELL_ALLOWLIST = frozenset(
    {
        "ls", "cat", "head", "tail", "wc", "find", "grep", "zgrep", "egrep", "fgrep",
        "zcat", "zless", "gzip", "gunzip", "bzip2", "bzcat", "xz", "unxz",
        "awk", "sed", "cut", "sort", "uniq", "tr", "column", "paste", "join", "comm",
        "file", "stat", "du", "df", "tree", "basename", "dirname", "realpath",
        "md5sum", "sha256sum", "cksum", "cmp", "diff",
        "samtools", "bcftools", "bgzip", "tabix", "seqkit", "fastp", "jq", "datamash",
        "python", "python3", "pwd", "which", "echo", "printf", "true", "false", "test",
    }
)

# 禁用模式（纵深防御：容器内本就无网络，主要防直通模式与误操作）。
# 结构性隐藏执行语法（命令替换/反引号/进程替换/-exec/awk-python 的 system()）
# 一律硬拒：它们能让白名单外的命令词绕过首词检查（v1.4.13 巡检后收紧）。
_SHELL_DENY_PATTERNS = (
    r"\bpodman\b", r"\bdocker\b", r"\bapptainer\b", r"\bsingularity\b", r"\bnsenter\b",
    r"\bmount\b", r"\bumount\b", r"\bsudo\b", r"\bsu\b", r"\bchown\b",
    r"\bcurl\b", r"\bwget\b", r"\bssh\b", r"\bscp\b", r"\brsync\b",
    r"\bdd\b", r"\bmkfs\b", r"\bshutdown\b", r"\breboot\b", r"\bkill\b",
    r"/proc/1\b", r"/dev/(sd|nvme|disk)", r":\(\)\s*\{",
    r"\$\(", r"`", r"<\(", r"\s-exec(?:dir)?\s", r"\bsystem\s*\(",
)
_SHELL_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def classify_shell(command: str) -> str:
    """命令风险分类：``deny`` | ``allow`` | ``confirm``。

    拒绝：命中禁用模式（含命令替换/反引号/-exec 等隐藏执行语法）。
    放行：每个 ``|``/``;``/``&``/**换行** 段的命令词都在白名单内（允许前置
    ``VAR=`` 与重定向）——换行与管道一样是命令段边界，不检查即存在
    "首段白名单、后续段任意命令"的绕过。
    其余：需要确认——接口层据此引导改用 ``mine`` 任务（过挖掘门+签字）。
    """
    text = command.strip()
    if not text:
        return "deny"
    low = text.lower()
    for pattern in _SHELL_DENY_PATTERNS:
        if re.search(pattern, low):
            return "deny"
    for segment in re.split(r"[|;&\n]+", text):
        tokens = segment.strip().split()
        while tokens and _SHELL_ASSIGN_RE.match(tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue
        word = tokens[0].rsplit("/", 1)[-1]
        if word not in _SHELL_ALLOWLIST:
            return "confirm"
    return "allow"


def _audit_shell(home: Path, command: str, verdict: str, result: Any) -> None:
    """把 shell 调用写入审计 JSONL（可复现/可追责；命令是瞬时串,必须留痕）。"""
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "command": command,
        "verdict": verdict,
        "backend": getattr(result, "backend", ""),
        "returncode": getattr(result, "returncode", None),
        "stdout_sha256": (
            hashlib.sha256(result.stdout.encode()).hexdigest() if result is not None else None
        ),
    }
    path = Path(home) / "audits" / "sandbox_shell.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        import logging

        logging.getLogger(__name__).exception("sandbox_shell audit write failed")


def run_shell(
    workspace_root: Path,
    command: str,
    description: str = "",
    datasets: list[str] | None = None,
) -> str:
    """在沙箱内执行一条白名单内的 shell 命令（收窄形态：仅容器后端）。"""
    import os

    from bacmap import config
    from bacmap.agent.sandbox import SandboxExecutor, SandboxSpec, SandboxUnavailableError
    from bacmap.agent.sandbox.access import allowed_roots, build_access

    verdict = classify_shell(command)
    if verdict == "deny":
        _audit_shell(config.BACMAP_HOME, command, verdict, None)
        return json.dumps(
            {"error": "命令被安全策略拒绝（命中禁用清单）", "verdict": verdict},
            ensure_ascii=False,
        )
    if verdict == "confirm":
        _audit_shell(config.BACMAP_HOME, command, verdict, None)
        return json.dumps(
            {
                "error": "该命令不在只读/分析白名单内；请改为规划 mine 任务"
                "（经挖掘门 + 人工签字）",
                "verdict": "requires_confirmation",
            },
            ensure_ascii=False,
        )

    registry_datasets, err = _load_datasets(datasets or [])
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    executor = SandboxExecutor()
    backend = executor.backend_name()
    if backend == "unavailable":
        return json.dumps(
            {"error": "沙箱不可用：无 apptainer/podman 且未设置 BACMAP_ALLOW_UNSANDBOXED=1"},
            ensure_ascii=False,
        )
    if backend == "direct" and os.environ.get("BACMAP_SANDBOX_ALLOW_SHELL_PASSTHROUGH") != "1":
        # 直通模式下 shell 等价于宿主 shell——默认拒绝（收窄形态的核心约束）。
        _audit_shell(config.BACMAP_HOME, command, "deny_passthrough", None)
        return json.dumps(
            {
                "error": "直通模式拒绝 shell（等价宿主 shell）；"
                "仅 BACMAP_SANDBOX_ALLOW_SHELL_PASSTHROUGH=1 可在受控开发环境启用"
            },
            ensure_ascii=False,
        )

    workdir = Path(workspace_root) / f"sh-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    mounts, context = build_access(
        backend,
        results_dir=config.RESULTS_DIR,
        gom_db=config.GOM_DB,
        datasets=registry_datasets,
    )
    (workdir / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    spec = SandboxSpec(
        image=_sandbox_image(),
        command=["bash", "-lc", command],
        workspace=workdir,
        readonly_mounts=mounts,
        allowed_readonly_roots=allowed_roots(
            results_dir=config.RESULTS_DIR, gom_db=config.GOM_DB, datasets=registry_datasets
        ),
    )
    try:
        result = executor.run(spec)
    except SandboxUnavailableError as exc:
        return json.dumps({"error": f"沙箱不可用：{exc}"}, ensure_ascii=False)

    _audit_shell(config.BACMAP_HOME, command, "allow", result)
    artifacts = [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(workdir.iterdir())
        if f.is_file() and f.name != "context.json"
    ]
    return json.dumps(
        {
            "returncode": result.returncode,
            "backend": result.backend,
            "description": description,
            "workspace": str(workdir),
            "datasets": context["datasets"],
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "artifacts": artifacts,
        },
        ensure_ascii=False,
    )


def build_shell_tool(workspace_root: Path) -> Any:
    """构建 pydantic-ai 的 sandbox_shell 工具（异步包装，线程中执行）。"""
    from pydantic_ai import Tool

    async def _sandbox_shell(
        command: str, description: str = "", datasets: list[str] | None = None
    ) -> str:
        import anyio

        return await anyio.to_thread.run_sync(
            lambda: run_shell(workspace_root, command, description, datasets)
        )

    return Tool.from_schema(
        _sandbox_shell,
        name="sandbox_shell",
        description=_SHELL_DESCRIPTION,
        json_schema=_SHELL_SCHEMA,
    )

