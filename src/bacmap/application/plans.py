"""版本化分析计划（v1.5.1，ADR-06/ADR-21）。

外部 Harness（或任何 MCP 客户端）只能**创建/修订**计划；确认只发生在 bacmap 自有的
可信界面（CLI / Web），并且必须给出被确认的 ``(plan_id, version, plan_hash)``：

- ``plan_hash`` = SHA-256(规范 JSON)，规范 JSON 只含影响执行的内容（类型化任务参数 +
  输入目录指纹），键排序、紧凑分隔、ASCII 转义；参数模型不含浮点，序列化确定；
- 修订产生新版本，旧版本 ``superseded``——确认 v1 不能执行 v2；
- 目录输入在建计划时记录指纹（相对路径 + 大小 + mtime），确认时复核，变化即冲突；
- 确认后以确定性 task_id（由 plan_id/version/序号派生）提交：重复确认、双端并发确认、
  崩溃后重试都只产生同一组任务（引擎对显式 task_id 幂等）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from bacmap.application.errors import Conflict, NotFound, ValidationFailed
from bacmap.store.migrations import migrate
from bacmap.tasks.events import EventLog, EventType
from bacmap.tasks.params import (
    AnalyzeParams,
    CurateParams,
    MineParams,
    PlannableTask,
    WriteParams,
    engine_params,
    task_type_of,
)
from bacmap.tasks.spec import TASKS_MIGRATIONS, TaskEngine, TaskId

MAX_TASKS_PER_PLAN = 10
_MIN_HASH_PREFIX = 12
PlanTask = AnalyzeParams | CurateParams | MineParams | WriteParams
_TASKS_ADAPTER: TypeAdapter[list[PlanTask]] = TypeAdapter(list[PlannableTask])


class PlanState(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"  # 已确认、提交进行中（崩溃后再次确认即续提交）
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class PlanRecord(BaseModel):
    plan_id: str
    version: int
    state: PlanState
    tasks: list[PlanTask]
    inputs: dict[str, str]
    plan_hash: str
    rationale: str
    created_by: str
    created_at: str
    updated_at: str
    confirmed_by: str
    confirmed_at: str
    task_ids: list[str]
    message: str

    @property
    def short_hash(self) -> str:
        return self.plan_hash[:_MIN_HASH_PREFIX]


def parse_tasks(raw: Any) -> list[PlanTask]:
    """不可信输入 → 类型化任务列表（MCP/HTTP 边界使用）。"""
    try:
        return _TASKS_ADAPTER.validate_python(raw)
    except PydanticValidationError as exc:
        raise ValidationFailed(_brief(exc)) from exc


def _brief(exc: PydanticValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', '')}")
    return "; ".join(parts)


def directory_fingerprint(path: Path) -> str:
    """目录内容指纹（相对路径 + 大小 + mtime_ns）：确认前复核输入未被替换。"""
    if not path.is_dir():
        raise ValidationFailed(f"directory not found: {path}")
    digest = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        st = f.stat()
        rel = f.relative_to(path).as_posix()
        digest.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return f"files-v1:sha256:{digest.hexdigest()}"


def path_fingerprint(path: Path) -> str:
    """文件或目录指纹：确认前复核输入未被替换（目录递归；单文件取大小+mtime）。"""
    if path.is_dir():
        return directory_fingerprint(path)
    if path.is_file():
        st = path.stat()
        return f"file-v1:{st.st_size}:{st.st_mtime_ns}"
    raise ValidationFailed(f"input not found: {path}")


def _input_paths(tasks: Sequence[PlanTask]) -> list[str]:
    paths: list[str] = []
    for t in tasks:
        if isinstance(t, AnalyzeParams):
            paths.extend(d for d in (t.fasta_dir, t.fastq_dir) if d)
        elif isinstance(t, MineParams):
            paths.extend(t.input_paths)
    return sorted(set(paths))


def canonical_json(tasks: Sequence[PlanTask], inputs: dict[str, str]) -> str:
    payload = {
        "schema": 1,
        "tasks": [t.model_dump(mode="json") for t in tasks],
        "inputs": inputs,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def plan_hash(tasks: Sequence[PlanTask], inputs: dict[str, str]) -> str:
    return hashlib.sha256(canonical_json(tasks, inputs).encode("ascii")).hexdigest()


def plan_task_id(plan_id: str, version: int, index: int) -> TaskId:
    return TaskId(hashlib.sha256(f"plan:{plan_id}:{version}:{index}".encode()).hexdigest()[:32])


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PlanService:
    """计划的创建、修订、查询、拒绝与确认提交（CLI/Web/MCP 共用）。"""

    def __init__(self, engine: TaskEngine, db_path: Path) -> None:
        self._engine = engine
        self._db = Path(db_path)
        migrate(self._db, TASKS_MIGRATIONS)
        self._events = EventLog(self._db)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """自动提交连接（单语句原子），用后关闭。"""
        conn = sqlite3.connect(self._db, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        """IMMEDIATE 写事务：成功提交、异常回滚，用后关闭。"""
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # ---- 写：创建 / 修订 / 拒绝 -------------------------------------------------

    def create(
        self, tasks: Sequence[PlanTask], rationale: str, actor: str
    ) -> PlanRecord:
        plan_id = uuid.uuid4().hex[:16]
        with self._txn() as conn:
            self._insert(conn, plan_id, 1, tasks, rationale, actor)
        record = self.get(plan_id, 1)
        self._emit(EventType.PLAN_CREATED, record, actor)
        return record

    def revise(
        self,
        plan_id: str,
        tasks: Sequence[PlanTask],
        rationale: str,
        actor: str,
    ) -> PlanRecord:
        with self._txn() as conn:
            latest = self._latest_row(conn, plan_id)
            state = PlanState(latest["state"])
            if state not in (PlanState.AWAITING_CONFIRMATION, PlanState.REJECTED):
                raise Conflict(
                    f"plan {plan_id} v{latest['version']} is {state.value}; cannot revise"
                )
            version = int(latest["version"]) + 1
            if state is PlanState.AWAITING_CONFIRMATION:
                self._set_state(conn, plan_id, version - 1, PlanState.SUPERSEDED, "")
            self._insert(conn, plan_id, version, tasks, rationale, actor)
        record = self.get(plan_id, version)
        self._emit(EventType.PLAN_REVISED, record, actor)
        return record

    def reject(self, plan_id: str, version: int, reason: str, actor: str) -> PlanRecord:
        with self._conn() as conn:
            changed = conn.execute(
                "UPDATE plans SET state = ?, message = ?, confirmed_by = ?, updated_at = ?"
                " WHERE plan_id = ? AND version = ? AND state = ?",
                (
                    PlanState.REJECTED.value,
                    f"rejected: {reason}".strip(),
                    actor,
                    _now(),
                    plan_id,
                    version,
                    PlanState.AWAITING_CONFIRMATION.value,
                ),
            ).rowcount
        record = self.get(plan_id, version)
        if not changed:
            raise Conflict(f"plan {plan_id} v{version} is {record.state.value}; cannot reject")
        self._emit(EventType.PLAN_REJECTED, record, actor)
        return record

    # ---- 确认并提交（仅可信界面调用） ----------------------------------------------

    def confirm(self, plan_id: str, version: int, hash_or_prefix: str, actor: str) -> PlanRecord:
        record = self.get(plan_id, version)
        if len(hash_or_prefix) < _MIN_HASH_PREFIX or not record.plan_hash.startswith(
            hash_or_prefix.lower()
        ):
            raise Conflict(
                f"plan hash mismatch for {plan_id} v{version}: the plan you confirmed is not "
                f"the stored one (expected prefix {record.short_hash})"
            )
        if record.state is PlanState.SUBMITTED:
            return record
        if record.state is PlanState.AWAITING_CONFIRMATION:
            try:
                current = {p: path_fingerprint(Path(p)) for p in record.inputs}
            except ValidationFailed as exc:
                raise Conflict(
                    f"input of plan {plan_id} v{version} is gone: {exc.message}"
                ) from exc
            if current != record.inputs:
                raise Conflict(
                    f"input directories of plan {plan_id} v{version} changed since the plan was "
                    "created; revise the plan and confirm again"
                )
            with self._conn() as conn:
                claimed = conn.execute(
                    "UPDATE plans SET state = ?, confirmed_by = ?, confirmed_at = ?, updated_at = ?"
                    " WHERE plan_id = ? AND version = ? AND state = ?",
                    (
                        PlanState.CONFIRMED.value,
                        actor,
                        _now(),
                        _now(),
                        plan_id,
                        version,
                        PlanState.AWAITING_CONFIRMATION.value,
                    ),
                ).rowcount
            record = self.get(plan_id, version)
            if claimed:
                self._emit(EventType.PLAN_CONFIRMED, record, actor)
        if record.state is PlanState.SUBMITTED:
            return record
        if record.state is not PlanState.CONFIRMED:
            raise Conflict(f"plan {plan_id} v{version} is {record.state.value}; cannot confirm")
        return self._submit(record)

    def _submit(self, record: PlanRecord) -> PlanRecord:
        submitted: list[str] = []
        by = f"{record.confirmed_by} via plan {record.plan_id}@v{record.version}"
        for index, task in enumerate(record.tasks):
            tid = plan_task_id(record.plan_id, record.version, index)
            try:
                self._engine.submit(task_type_of(task), engine_params(task), by, task_id=tid)
            except (ValueError, NotImplementedError) as exc:
                self._finish(record, PlanState.FAILED, submitted, f"task {index} rejected: {exc}")
                failed = self.get(record.plan_id, record.version)
                self._emit(EventType.PLAN_FAILED, failed, record.confirmed_by)
                return failed
            submitted.append(str(tid))
        self._finish(record, PlanState.SUBMITTED, submitted, "")
        done = self.get(record.plan_id, record.version)
        self._emit(EventType.PLAN_SUBMITTED, done, record.confirmed_by)
        return done

    def _emit(self, type_: EventType, record: PlanRecord, actor: str) -> None:
        self._events.append(
            type_,
            plan_id=record.plan_id,
            actor=actor,
            payload={
                "version": record.version,
                "state": record.state.value,
                "plan_hash": record.plan_hash,
                "task_ids": list(record.task_ids),
            },
        )

    def _finish(
        self, record: PlanRecord, state: PlanState, task_ids: list[str], message: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE plans SET state = ?, task_ids_json = ?, message = ?, updated_at = ?"
                " WHERE plan_id = ? AND version = ?",
                (
                    state.value,
                    json.dumps(task_ids),
                    message,
                    _now(),
                    record.plan_id,
                    record.version,
                ),
            )

    # ---- 读 ---------------------------------------------------------------------

    def get(self, plan_id: str, version: int | None = None) -> PlanRecord:
        with self._conn() as conn:
            if version is None:
                row = self._latest_row(conn, plan_id)
            else:
                row = conn.execute(
                    "SELECT * FROM plans WHERE plan_id = ? AND version = ?", (plan_id, version)
                ).fetchone()
        if row is None:
            raise NotFound(f"no such plan: {plan_id}" + (f" v{version}" if version else ""))
        return _record(row)

    def list_plans(self, limit: int = 20) -> list[PlanRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT p.* FROM plans p JOIN (SELECT plan_id, MAX(version) AS v FROM plans"
                " GROUP BY plan_id) m ON p.plan_id = m.plan_id AND p.version = m.v"
                " ORDER BY p.updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_record(r) for r in rows]

    # ---- 内部 -------------------------------------------------------------------

    def _insert(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        version: int,
        tasks: Sequence[PlanTask],
        rationale: str,
        actor: str,
    ) -> None:
        if not tasks:
            raise ValidationFailed("a plan needs at least one task")
        if len(tasks) > MAX_TASKS_PER_PLAN:
            raise ValidationFailed(f"a plan holds at most {MAX_TASKS_PER_PLAN} tasks")
        inputs = {p: path_fingerprint(Path(p)) for p in _input_paths(tasks)}
        now = _now()
        conn.execute(
            "INSERT INTO plans (plan_id, version, state, tasks_json, canonical_json, plan_hash,"
            " rationale, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                plan_id,
                version,
                PlanState.AWAITING_CONFIRMATION.value,
                json.dumps([t.model_dump(mode="json") for t in tasks], ensure_ascii=False),
                canonical_json(tasks, inputs),
                plan_hash(tasks, inputs),
                rationale[:2000],
                actor,
                now,
                now,
            ),
        )

    @staticmethod
    def _latest_row(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM plans WHERE plan_id = ? ORDER BY version DESC LIMIT 1", (plan_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no such plan: {plan_id}")
        return row

    @staticmethod
    def _set_state(
        conn: sqlite3.Connection, plan_id: str, version: int, state: PlanState, message: str
    ) -> None:
        conn.execute(
            "UPDATE plans SET state = ?, message = ?, updated_at = ?"
            " WHERE plan_id = ? AND version = ?",
            (state.value, message, _now(), plan_id, version),
        )


def _record(row: sqlite3.Row) -> PlanRecord:
    canonical = json.loads(row["canonical_json"])
    return PlanRecord(
        plan_id=row["plan_id"],
        version=int(row["version"]),
        state=PlanState(row["state"]),
        tasks=_TASKS_ADAPTER.validate_python(json.loads(row["tasks_json"])),
        inputs=dict(canonical.get("inputs", {})),
        plan_hash=row["plan_hash"],
        rationale=row["rationale"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        confirmed_by=row["confirmed_by"],
        confirmed_at=row["confirmed_at"],
        task_ids=list(json.loads(row["task_ids_json"])),
        message=row["message"],
    )
