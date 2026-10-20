"""任务契约（冻结设计 §4.3/§4.7，ADR-06）。

TaskEngine 是任务层的对外接口；DBOS 实现位于 bacmap.tasks.engine
（唯一允许导入 dbos 的模块，ADR-02）。tasks / approvals 两张表由 bacmap
自有，是对外可见的唯一任务状态。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from bacmap.tools.spec import TaskId

__all__ = ["Approval", "TaskEngine", "TaskId", "TaskState", "TaskStatus", "TaskType"]

TASKS_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id          TEXT PRIMARY KEY,
    task_type        TEXT NOT NULL,
    state            TEXT NOT NULL,
    params_json      TEXT NOT NULL DEFAULT '{}',
    submitted_by     TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    workspace_path   TEXT NOT NULL DEFAULT '',
    result_object_ids TEXT NOT NULL DEFAULT '[]',
    workflow_id      TEXT NOT NULL DEFAULT '',
    current_step     TEXT NOT NULL DEFAULT '',
    message          TEXT NOT NULL DEFAULT ''
)
"""

APPROVALS_DDL = """
CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    approver    TEXT NOT NULL,
    decision    TEXT NOT NULL,
    signature   TEXT NOT NULL DEFAULT '',
    comment     TEXT,
    at          TEXT NOT NULL
)
"""


class TaskType(StrEnum):
    ANALYZE = "analyze"
    CURATE = "curate"  # 本地流行特征库构建（v1.2，原 build_db）
    MINE = "mine"
    WRITE = "write"


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(BaseModel):
    task_id: TaskId
    state: TaskState
    current_step: str | None = None
    message: str | None = None


class Approval(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    approver: str
    decision: Literal["approve", "reject"]
    signature: str
    comment: str | None = None
    at: datetime


class TaskEngine(Protocol):
    def submit(
        self, task_type: TaskType, params: BaseModel, submitted_by: str
    ) -> TaskId: ...
    def status(self, task_id: TaskId) -> TaskStatus: ...
    def resolve_task_id(self, prefix: str) -> TaskId: ...
    def cancel(self, task_id: TaskId) -> None: ...
    def approve(self, task_id: TaskId, approval: Approval) -> None: ...
