"""领域事件日志（v1.5.2）：计划/任务关键转换的追加式记录。

- 存于 bacmap 自有的 ``tasks.sqlite``（``events`` 表，迁移 3），单调递增 ``seq``
  作为续传游标（SSE ``Last-Event-ID`` / ``GET /api/v1/events?after=``）；
- 事件**不是**任务真相：丢事件后客户端以任务/计划查询恢复状态（规则：状态只认任务表）；
- 只记录可验证的操作事实（谁、对什么、何时、结果），不记录提示词、模型输出或原始数据；
  ``data_class`` 标注载荷级别，供对外接口按级别过滤。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, JsonValue

from bacmap.store.migrations import migrate
from bacmap.tasks.spec import TASKS_MIGRATIONS
from bacmap.tools.spec import DataClass

MAX_PAGE = 500


class EventType(StrEnum):
    PLAN_CREATED = "plan.created"
    PLAN_REVISED = "plan.revised"
    PLAN_REJECTED = "plan.rejected"
    PLAN_CONFIRMED = "plan.confirmed"
    PLAN_SUBMITTED = "plan.submitted"
    PLAN_FAILED = "plan.failed"
    TASK_SUBMITTED = "task.submitted"
    TASK_STEP = "task.step"
    TASK_STATE = "task.state"
    TASK_APPROVAL = "task.approval"


class Event(BaseModel):
    seq: int
    event_id: str
    type: EventType
    occurred_at: str
    actor: str
    task_id: str | None
    plan_id: str | None
    data_class: DataClass
    payload: dict[str, JsonValue]


class EventLog:
    def __init__(self, db_path: Path) -> None:
        self._db = Path(db_path)
        migrate(self._db, TASKS_MIGRATIONS)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def append(
        self,
        type_: EventType,
        *,
        task_id: str | None = None,
        plan_id: str | None = None,
        actor: str = "",
        payload: dict[str, JsonValue] | None = None,
        data_class: DataClass = DataClass.D0,
    ) -> int:
        event_type = EventType(type_)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO events (event_id, type, occurred_at, actor, task_id, plan_id,"
                " data_class, payload_json) VALUES (?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    event_type.value,
                    datetime.now(UTC).isoformat(),
                    actor,
                    task_id,
                    plan_id,
                    int(data_class),
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            seq = cur.lastrowid
        if seq is None:
            raise RuntimeError("event insert returned no rowid")
        return int(seq)

    def list(
        self,
        *,
        after: int = 0,
        limit: int = 100,
        task_id: str | None = None,
        plan_id: str | None = None,
        max_data_class: DataClass = DataClass.D4,
    ) -> list[Event]:
        clauses = ["seq > ?", "data_class <= ?"]
        args: list[object] = [after, int(max_data_class)]
        if task_id is not None:
            clauses.append("task_id = ?")
            args.append(task_id)
        if plan_id is not None:
            clauses.append("plan_id = ?")
            args.append(plan_id)
        args.append(max(1, min(limit, MAX_PAGE)))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT ?",  # noqa: S608
                args,
            ).fetchall()
        return [_event(r) for r in rows]

    def prune(self, older_than_days: int) -> int:
        """按保留期删除事件，返回删除条数（审计保留策略由管理员决定；见文档）。"""
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM events WHERE occurred_at < ?", (cutoff,))
            return int(cur.rowcount)

    def last_seq(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
        return int(row[0])


def _event(row: sqlite3.Row) -> Event:
    return Event(
        seq=int(row["seq"]),
        event_id=row["event_id"],
        type=EventType(row["type"]),
        occurred_at=row["occurred_at"],
        actor=row["actor"],
        task_id=row["task_id"],
        plan_id=row["plan_id"],
        data_class=DataClass(int(row["data_class"])),
        payload=json.loads(row["payload_json"]),
    )
