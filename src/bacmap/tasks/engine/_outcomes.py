"""任务终态化：审批副作用 + 工作流状态映射。

从 dbos_engine 拆出的纯编排逻辑——不依赖 DBOS step/workflow 的模块级
身份（恢复语义与测试 monkeypatch 契约要求那些留在 dbos_engine 同模块），
故可自由移动：

- mine/curate 审批通过后的类型专属副作用（``_APPROVE_FINALIZERS`` 分发表）；
- DBOS 工作流原始状态 → 任务终态的映射（``_map_workflow_outcome`` 纯函数）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bacmap.tasks.spec import Approval, TaskState, TaskType

# mine 工作区中不属于产物的内部文件（脚本本身与访问面清单）
_MINE_INTERNAL_FILES = {"analysis.py", "context.json"}


def _mine_artifacts(workspace: Path) -> list[dict[str, Any]]:
    """mine 产物清单：工作区内非内部文件（``gates.evaluate_mining`` 依赖此结构）。

    ``_step_mine_run`` 与 ``DbosTaskEngine.approve`` 共用——清单口径必须一致，
    否则审批复检与门评估会对不上。
    """
    return [
        {"name": f.name, "reproducible": True}
        for f in sorted(workspace.iterdir())
        if f.is_file() and f.name not in _MINE_INTERNAL_FILES
    ]


def _finalize_mine_approval(
    home: Path, task_id: str, approval: Approval
) -> tuple[TaskState, str]:
    """mine 审批通过后的复检：重枚举产物并过挖掘门（门不过 → 任务失败）。"""
    from bacmap.tasks import gates as _gates

    workspace = home / "workspaces" / task_id
    artifacts = _mine_artifacts(workspace) if workspace.is_dir() else []
    gate = _gates.evaluate_mining({"artifacts": artifacts, "signed_by": approval.approver})
    if gate.verdict != _gates.GateVerdict.PASS:
        return TaskState.FAILED, f"mining gate rejected: {gate.details.get('problems')}"
    return TaskState.SUCCEEDED, f"approved by {approval.approver}"


def _finalize_curate_approval(
    home: Path, task_id: str, approval: Approval
) -> tuple[TaskState, str]:
    """curate 审批通过后的副作用：加载候选清单并发布 baseline（签名归档）。"""
    from bacmap.store import baseline

    cand = baseline.load_candidate(home / "baseline.sqlite", task_id)
    if cand is None:
        return TaskState.FAILED, "candidate manifest missing; cannot publish"
    version = baseline.publish(
        home / "baseline.sqlite",
        cand["manifest"],
        created_by=approval.approver,
        signature=approval.signature,
    )
    return TaskState.SUCCEEDED, f"published baseline v{version} (signed by {approval.approver})"


# 审批副作用分发表：新增任务类型在此注册终态化函数，不再往 approve() 塞 if 链。
_APPROVE_FINALIZERS: dict[
    str, Callable[[Path, str, Approval], tuple[TaskState, str]]
] = {
    TaskType.MINE.value: _finalize_mine_approval,
    TaskType.CURATE.value: _finalize_curate_approval,
}


def _map_workflow_outcome(
    ws: str, result: dict[str, Any], fallback_message: str | None
) -> tuple[TaskState, str | None] | None:
    """DBOS 工作流原始状态 → ``(任务状态, 消息)``；未结束返回 ``None``。

    ``message=None`` 表示保持库中原值（SQL 侧 ``COALESCE``）。纯函数便于单测：
    SUCCESS 优先取工作流给出的具体原因（snakemake stderr / 沙箱脚本报错），
    没有时退回门结果 JSON；ERROR 结束（无 result 可读）时给可读提示，
    否则列表里 message 为空、用户不知道发生了什么。
    """
    if ws in ("PENDING", "RUNNING"):
        return None
    if ws == "SUCCESS":
        status_val = str(result.get("status", "SUCCEEDED"))
        state = {
            "AWAITING_APPROVAL": TaskState.AWAITING_APPROVAL,
            "FAILED": TaskState.FAILED,
        }.get(status_val, TaskState.SUCCEEDED)
        message = str(result.get("message") or "") or json.dumps(
            result.get("gates", {}), ensure_ascii=False
        )
        return state, message
    if ws == "CANCELLED":
        return TaskState.CANCELLED, None
    # ERROR / 其他：无 result 可读——用原 message，为空则至少说明工作流状态。
    return TaskState.FAILED, fallback_message or f"workflow {ws}"
