"""任务契约（冻结设计 §4.3/§4.7，ADR-06）。

TaskEngine 是任务层的对外接口；DBOS 实现位于 bacmap.tasks.engine
（唯一允许导入 dbos 的模块，ADR-02）。tasks / approvals 两张表由 bacmap
自有，是对外可见的唯一任务状态。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from bacmap.store.migrations import Migration
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

# tasks.sqlite 的 schema 迁移（ADR-13，v1.5）。只追加，不修改已发布的迁移。
# 版本 2（v1.5.1）：版本化分析计划（plans）——计划确认绑定 (plan_id, version, plan_hash)，
# 确认后以确定性 task_id 提交（重复确认幂等）。
PLANS_DDL = """
CREATE TABLE plans (
    plan_id          TEXT NOT NULL,
    version          INTEGER NOT NULL,
    state            TEXT NOT NULL,
    tasks_json       TEXT NOT NULL,
    canonical_json   TEXT NOT NULL,
    plan_hash        TEXT NOT NULL,
    rationale        TEXT NOT NULL DEFAULT '',
    created_by       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    confirmed_by     TEXT NOT NULL DEFAULT '',
    confirmed_at     TEXT NOT NULL DEFAULT '',
    task_ids_json    TEXT NOT NULL DEFAULT '[]',
    message          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (plan_id, version)
)
"""

# 版本 3（v1.5.2）：领域事件日志（追加式，seq 为续传游标；见 bacmap.tasks.events）。
EVENTS_DDL = """
CREATE TABLE events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,
    actor        TEXT NOT NULL DEFAULT '',
    task_id      TEXT,
    plan_id      TEXT,
    data_class   INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}'
)
"""

TASKS_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline: tasks + approvals", (TASKS_DDL, APPROVALS_DDL)),
    Migration(
        2,
        "plans: versioned analysis plans",
        (PLANS_DDL, "CREATE INDEX idx_plans_updated ON plans (updated_at)"),
    ),
    Migration(
        3,
        "events: domain event log",
        (
            EVENTS_DDL,
            "CREATE INDEX idx_events_task ON events (task_id, seq)",
            "CREATE INDEX idx_events_plan ON events (plan_id, seq)",
        ),
    ),
)


class TaskType(StrEnum):
    ANALYZE = "analyze"
    CURATE = "curate"  # 本地流行特征库构建（v1.2，原 build_db）
    MINE = "mine"
    WRITE = "write"
    RECORD = "record"  # v1.7：元数据/化验/知识库记录（写操作仍只经任务层）


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
        self,
        task_type: TaskType,
        params: BaseModel | dict[str, Any],
        submitted_by: str,
        *,
        task_id: TaskId | None = None,
    ) -> TaskId: ...
    def status(self, task_id: TaskId) -> TaskStatus: ...
    def resolve_task_id(self, prefix: str) -> TaskId: ...
    def cancel(self, task_id: TaskId) -> None: ...
    def approve(self, task_id: TaskId, approval: Approval) -> None: ...
