"""Web/API 共用的表单载荷解析（v0.2.0 SPA）。

页面表单（``app.py``）与 ``/api/v1``（``api.py``）共用同一套校验：
任务提交、审批签名与记录字段。放在独立模块避免 API 反向导入 app。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException

from bacmap.tasks.spec import Approval, TaskType
from bacmap.tools._common import _validate_sample_id

_WEB_TASK_TYPES = (TaskType.ANALYZE, TaskType.CURATE)


def _samples_from(value: str | list[str]) -> list[str]:
    raw = value.replace("\n", ",").split(",") if isinstance(value, str) else list(value)
    samples = [str(s).strip() for s in raw if str(s).strip()]
    bad = [s for s in samples if not _validate_sample_id(s)]
    if bad:
        raise HTTPException(400, f"非法样本 ID: {bad!r}")
    return samples


def _scope_from(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, "scope 不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(400, "scope 必须是 JSON 对象")
    return parsed


def submit_task_payload(
    task_type: str, samples: str | list[str] = "", scope: str | dict[str, Any] | None = None
) -> tuple[TaskType, dict[str, Any]]:
    """提交表单/JSON → (任务类型, 引擎参数)；非法值抛 HTTPException。"""
    try:
        tt = TaskType(task_type)
    except ValueError as exc:
        raise HTTPException(400, f"未知任务类型: {task_type}") from exc
    # Web 只提交封闭的 analyze|curate；mine/write 属开放路径，需 script/draft
    # 参数，不经此入口（防止伪造 POST 产生空任务）。
    if tt not in _WEB_TASK_TYPES:
        raise HTTPException(400, f"任务类型 {tt.value!r} 不支持 Web 提交")
    params: dict[str, Any] = {}
    sample_list = _samples_from(samples)
    if sample_list:
        params["samples"] = sample_list
    parsed_scope = _scope_from(scope)
    if parsed_scope is not None:
        params["scope"] = parsed_scope
    return tt, params


def approval_payload(
    approver: str, decision: str, signature: str, comment: str | None = None
) -> Approval:
    """审批表单/JSON → Approval；非法 decision 抛 HTTPException。"""
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision 必须是 approve|reject")
    typed_decision: Literal["approve", "reject"] = (
        "approve" if decision == "approve" else "reject"
    )
    return Approval(
        approver=approver,
        decision=typed_decision,
        signature=signature,
        comment=comment,
        at=datetime.now(UTC),
    )


def fields_from_text(raw: str | dict[str, str]) -> dict[str, str]:
    """记录字段：``k=v`` 文本（逗号/换行分隔）或 JSON 对象 → dict。"""
    if isinstance(raw, dict):
        return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip()}
    out: dict[str, str] = {}
    for line in raw.replace(",", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            raise HTTPException(400, f"字段行需要 k=v 形式：{line!r}")
        key, _, value = line.partition("=")
        if not key.strip():
            raise HTTPException(400, f"字段键为空：{line!r}")
        out[key.strip()] = value.strip()
    return out
