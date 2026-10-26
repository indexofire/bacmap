"""DbosTaskEngine：tasks.sqlite 的 CRUD + 状态对账 + 审批落库。

从 dbos_engine 拆出（dbos_engine 保留 DBOS step/workflow——恢复语义与测试
monkeypatch 契约要求 step/workflow 与其可注入辅助同模块）。workflow 经
模块属性访问（``_wf.analyze_workflow``，submit 内延迟导入）以保持
``monkeypatch.setattr(dbos_engine, ...)`` 的可替换性并避免顶层循环导入。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel

from bacmap.store.migrations import migrate
from bacmap.tasks.engine._outcomes import _APPROVE_FINALIZERS, _map_workflow_outcome
from bacmap.tasks.engine._runtime import init_dbos
from bacmap.tasks.events import EventLog, EventType
from bacmap.tasks.spec import (
    TASKS_MIGRATIONS,
    Approval,
    TaskId,
    TaskState,
    TaskStatus,
    TaskType,
)
from bacmap.tools.spec import DataClass

logger = logging.getLogger(__name__)


class DbosTaskEngine:
    """analyze 任务的 DBOS 实现（curate/mine/write 随迁移第 7/10 步接入）。"""

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.db = self.home / "tasks.sqlite"
        self.home.mkdir(parents=True, exist_ok=True)
        migrate(self.db, TASKS_MIGRATIONS)
        self.events = EventLog(self.db)
        init_dbos(self.home / "dbos.sqlite")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn

    def submit(
        self,
        task_type: TaskType,
        params: BaseModel | dict[str, Any],
        submitted_by: str,
        *,
        task_id: TaskId | None = None,
    ) -> TaskId:
        """提交任务。``task_id`` 显式给定时提交是幂等的：同 ID 已存在即直接返回
        （计划确认以确定性 ID 提交，重复确认/崩溃后重试不会产生第二个任务）。"""
        # 延迟导入 + 模块属性访问：workflow 函数解析发生在调用期，测试对
        # dbos_engine 模块的 monkeypatch 仍然生效，且无顶层循环导入。
        import bacmap.tasks.engine.dbos_engine as _wf

        workflows = {
            TaskType.ANALYZE: _wf.analyze_workflow,
            TaskType.CURATE: _wf.curate_workflow,
            TaskType.MINE: _wf.mine_workflow,
            TaskType.WRITE: _wf.write_workflow,
            TaskType.RECORD: _wf.record_workflow,
        }
        if task_type not in workflows:
            raise NotImplementedError(f"unsupported task type: {task_type}")
        p = params.model_dump() if isinstance(params, BaseModel) else dict(params)
        p.setdefault("home", str(self.home))
        p.setdefault("cores", 8)
        p.setdefault("submitted_by", submitted_by)

        if task_type == TaskType.RECORD:
            # 记录类参数在提交入口即校验（记录类型判别 + 字段白名单）。
            from bacmap.tasks.records import parse_record

            parse_record(p)

        # analyze 必须有样本输入：samples 列表或目录直入（fasta_dir/fastq_dir，
        # 工作流首步自动登记，v1.4.38/39）——否则工作流会以 KeyError 落成静默 FAILED。
        if (
            task_type == TaskType.ANALYZE
            and not p.get("samples")
            and not (p.get("fasta_dir") or p.get("fastq_dir"))
        ):
            raise ValueError("analyze requires samples or fasta_dir/fastq_dir")

        # 防御纵深：样本 ID 白名单（MCP/Web 已校验；引擎是最终写入口）。
        samples = p.get("samples")
        if samples:
            from bacmap.tools._common import _validate_sample_id

            bad = [s for s in samples if not _validate_sample_id(str(s))]
            if bad:
                raise ValueError(f"invalid sample id(s): {bad!r}")

        if task_id is None:
            new_id = uuid.uuid4().hex
        else:
            if not (len(task_id) == 32 and all(c in "0123456789abcdef" for c in task_id)):
                raise ValueError(f"task_id must be 32 lowercase hex chars: {task_id!r}")
            new_id = str(task_id)
        p["task_id"] = new_id
        now = datetime.now(UTC).isoformat()

        # 先落任务行（可见性）：workflow_id 用确定性的 SetWorkflowID(task_id)，
        # 因此可在启动前就写死映射；启动失败回滚为 FAILED，不留孤儿工作流。
        with self._conn() as conn:
            inserted = conn.execute(
                "INSERT OR IGNORE INTO tasks (task_id, task_type, state, params_json,"
                " submitted_by, created_at, updated_at, workflow_id, current_step)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    task_type.value,
                    "running",
                    json.dumps(p, ensure_ascii=False),
                    submitted_by,
                    now,
                    now,
                    new_id,
                    task_type.value,
                ),
            ).rowcount
        if not inserted:
            # 显式 ID 已存在：幂等返回，不重复启动工作流（uuid4 碰撞不在考虑范围）。
            logger.info("submit: task %s already exists; idempotent return", new_id)
            return TaskId(new_id)
        self.events.append(
            EventType.TASK_SUBMITTED,
            task_id=new_id,
            actor=submitted_by,
            payload={"task_type": task_type.value},
        )
        try:
            with SetWorkflowID(new_id):
                DBOS.start_workflow(workflows[task_type], p)
        except Exception:
            self._update_state(TaskId(new_id), TaskState.FAILED, "workflow start failed")
            raise
        return TaskId(new_id)

    def status(self, task_id: TaskId) -> TaskStatus:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, workflow_id, current_step, message FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        state = TaskState(row["state"])
        message: str | None = row["message"]

        if state == TaskState.RUNNING and row["workflow_id"]:
            try:
                handle: Any = DBOS.retrieve_workflow(row["workflow_id"])
            except Exception:  # 工作流尚未注册/已清理：保持 RUNNING，不炸查询
                logger.warning("retrieve_workflow failed for %s", row["workflow_id"], exc_info=True)
                handle = None
            if handle is not None:
                raw_status = handle.get_status()
                ws = str(getattr(raw_status, "status", raw_status)).upper()
                if ws == "SUCCESS":
                    raw_result = handle.get_result()
                    result = raw_result if isinstance(raw_result, dict) else {}
                else:
                    result = {}
                outcome = _map_workflow_outcome(ws, result, message)
                if outcome is not None:
                    state, message = outcome
                    self._transition_from_running(task_id, state.value, message)

        return TaskStatus(
            task_id=task_id, state=state, current_step=row["current_step"], message=message
        )

    def get_task(self, task_id: TaskId) -> dict[str, Any]:
        """任务行（含提交者）；不存在抛 KeyError。读取前对账该任务状态。"""
        self.status(task_id)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT task_id, task_type, state, submitted_by, created_at, updated_at,"
                " current_step, message FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return dict(row)

    def workflow_result(self, task_id: TaskId) -> dict[str, Any] | None:
        """工作流已结束时的返回值（门评估、run_id 等）；未结束或不可得返回 None。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT workflow_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        if not row["workflow_id"]:
            return None
        try:
            handle: Any = DBOS.retrieve_workflow(row["workflow_id"])
            raw_status = handle.get_status()
        except Exception:  # 工作流不可检索（已清理/未注册）：如实返回"不可得"
            logger.warning("retrieve_workflow failed for %s", row["workflow_id"], exc_info=True)
            return None
        if str(getattr(raw_status, "status", raw_status)).upper() != "SUCCESS":
            return None
        result = handle.get_result()
        return result if isinstance(result, dict) else None

    def resolve_task_id(self, prefix: str) -> TaskId:
        """短前缀 → 完整任务 ID（git 短 SHA 式）：精确命中优先，唯一前缀放行，
        多义报错。``task ls``（12 位）/TUI（10 位）显示的都是截断 ID——直接
        粘贴给 task show/approve/cancel 由本方法兜住。"""
        with self._conn() as conn:
            exact = conn.execute(
                "SELECT task_id FROM tasks WHERE task_id = ?", (prefix,)
            ).fetchone()
            if exact is not None:
                return TaskId(str(exact["task_id"]))
            rows = conn.execute(
                "SELECT task_id FROM tasks WHERE task_id LIKE ? ORDER BY created_at DESC",
                (prefix + "%",),
            ).fetchall()
        if not rows:
            raise KeyError(f"no such task: {prefix}")
        if len(rows) > 1:
            shown = ", ".join(str(r["task_id"])[:12] for r in rows[:5])
            raise ValueError(f"task id prefix {prefix!r} matches {len(rows)} tasks: {shown}")
        return TaskId(str(rows[0]["task_id"]))

    def _transition_from_running(
        self, task_id: TaskId, new_state: str, message: str | None
    ) -> bool:
        """条件状态更新：仅当当前为 running 才写入（防与 approve() 的写竞态把终态降级）。"""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET state = ?, message = ?, updated_at = ?"
                " WHERE task_id = ? AND state = ?",
                (new_state, message, now, task_id, "running"),
            )
            changed = cur.rowcount > 0
        if changed:
            self._emit_state(task_id, new_state, message)
        return changed

    def _emit_state(self, task_id: TaskId, state: str, message: str | None) -> None:
        # 消息可能含样本 ID 等单株信息：按 D2 标注，供对外接口按级别过滤。
        self.events.append(
            EventType.TASK_STATE,
            task_id=task_id,
            actor="engine",
            payload={"state": state, "message": message or ""},
            data_class=DataClass.D2,
        )

    def cancel(self, task_id: TaskId) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, workflow_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        # 终态任务不得被"取消"改写（否则会篡改已完成/已失败的历史状态）。
        if row["state"] in (
            TaskState.SUCCEEDED.value,
            TaskState.FAILED.value,
            TaskState.CANCELLED.value,
        ):
            raise ValueError(
                f"task {task_id} is already {row['state']!r}; "
                "only non-terminal tasks can be cancelled"
            )
        if row["workflow_id"]:
            DBOS.cancel_workflow(row["workflow_id"])
        self._update_state(task_id, TaskState.CANCELLED)

    def approve(self, task_id: TaskId, approval: Approval) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, task_type, workflow_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        if row["state"] != TaskState.AWAITING_APPROVAL.value:
            raise ValueError(
                f"task {task_id} state is {row['state']!r}; "
                "only awaiting_approval tasks can be approved"
            )
        decision = getattr(approval.decision, "value", approval.decision)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO approvals (task_id, approver, decision, signature, comment, at)"
                " VALUES (?,?,?,?,?,?)",
                (task_id, approval.approver, decision, approval.signature, approval.comment, now),
            )
        self.events.append(
            EventType.TASK_APPROVAL,
            task_id=task_id,
            actor=approval.approver,
            payload={"decision": str(decision)},
        )
        if decision != "approve":
            self._update_state(task_id, TaskState.FAILED, f"rejected by {approval.approver}")
            return
        finalizer = _APPROVE_FINALIZERS.get(row["task_type"])
        new_state, message = (
            finalizer(self.home, task_id, approval)
            if finalizer is not None
            else (TaskState.SUCCEEDED, f"approved by {approval.approver}")
        )
        self._update_state(task_id, new_state, message)

    def _reconcile_running(self) -> None:
        """把仍在 running 的任务按工作流实际终态落库（列表/概览读取时惰性对账）。

        原来只有显式 ``status(task_id)`` 才迁移状态，于是 TUI/Web 的**列表视图**
        （走 ``list_tasks``/``count_states``）会永远显示 running——即便工作流早已
        以 FAILED/AWAITING_APPROVAL/SUCCEEDED 结束。
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT task_id FROM tasks WHERE state = ?"
                " AND workflow_id IS NOT NULL AND workflow_id != ''",
                (TaskState.RUNNING.value,),
            ).fetchall()
        for row in rows:
            try:
                self.status(TaskId(str(row["task_id"])))
            except Exception:  # 对账失败不得影响列表读取
                logger.warning("reconcile failed for %s", row["task_id"], exc_info=True)

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """最近任务列表（Web 列表页消费）。读取前先对账 running 的终态。"""
        self._reconcile_running()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT task_id, task_type, state, submitted_by, created_at, updated_at,"
                " current_step, message FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_states(self) -> dict[str, int]:
        """按状态统计全部任务（概览页用；不受 list_tasks 的 limit 截断）。"""
        self._reconcile_running()
        with self._conn() as conn:
            rows = conn.execute("SELECT state, COUNT(*) AS n FROM tasks GROUP BY state").fetchall()
        return {str(r["state"]): int(r["n"]) for r in rows}

    def _update_state(self, task_id: TaskId, state: TaskState, message: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE tasks SET state = ?, updated_at = ?, message = COALESCE(?, message)"
                " WHERE task_id = ?",
                (state.value, now, message, task_id),
            )
        self._emit_state(task_id, state.value, message)
