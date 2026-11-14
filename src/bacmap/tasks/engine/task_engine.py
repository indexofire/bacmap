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
from collections.abc import Iterator
from contextlib import contextmanager, suppress
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


def _plan_task_kill(
    ps_out: str, task_id: str, own_pid: int, own_pgid: int
) -> tuple[set[int], set[int]]:
    """解析 ``ps -eo pid,ppid,pgid,cmd`` 输出，返回 ``(进程组, 定点PID)``。

    只匹配命令行同时含 ``runs/<task_id>`` 与 ``snakemake`` 的行。独立进程组
    （WorkflowRunner ``start_new_session``）→ killpg 整组终止；与调用方同组的
    老版本遗留进程 → 退化为该 PID + 进程后代的定点杀，绝不按进程名全局匹配
    （并发 analyze 任务与终端手跑的同名生信进程不能误伤）。
    """
    marker = f"runs/{task_id}"
    procs: dict[int, int] = {}          # pid -> ppid
    targets: list[tuple[int, int]] = []  # (pid, pgid) of matching snakemake
    for line in ps_out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid, ppid, pgid = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        procs[pid] = ppid
        if marker in parts[3] and "snakemake" in parts[3]:
            targets.append((pid, pgid))
    kill_pgids: set[int] = set()
    kill_pids: set[int] = set()
    for pid, pgid in targets:
        if pid == own_pid:
            continue
        if pgid != own_pgid:
            kill_pgids.add(pgid)
            continue
        queue, seen = [pid], {pid}
        while queue:
            cur = queue.pop()
            kill_pids.add(cur)
            for child, ppid in procs.items():
                if ppid == cur and child not in seen:
                    seen.add(child)
                    queue.append(child)
    return kill_pgids, kill_pids


def _kill_task_pipeline_processes(task_id: str) -> int:
    """杀掉该任务关联的生信进程树（v1.10.24：cancel 即时终止 CPU 占用）。

    DBOS 的 cancel 是协作式的——只标记工作流状态，不会终止正在执行的
    subprocess。不杀的话 diamond 会持续吃满 CPU 直到自然结束（实测
    取消后 >10 分钟仍在跑）。按 run 目录路径匹配 snakemake 命令行后对
    **其进程组**发信号：TERM 宽限（让 snakemake 转发终止并解锁）→
    KILL 兜底；选组与退化策略见 :func:`_plan_task_kill`。
    """
    import os
    import signal
    import subprocess as _sp
    import time

    try:
        out = _sp.run(
            ["ps", "-eo", "pid,ppid,pgid,cmd"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, _sp.TimeoutExpired):
        return 0
    kill_pgids, kill_pids = _plan_task_kill(
        out, task_id, os.getpid(), os.getpgid(0)
    )
    terminated = 0
    for pgid in sorted(kill_pgids):
        try:
            os.killpg(pgid, signal.SIGTERM)
            terminated += 1
        except (ProcessLookupError, PermissionError):
            continue
    for pid in sorted(kill_pids):
        try:
            os.kill(pid, signal.SIGKILL)
            terminated += 1
        except (ProcessLookupError, PermissionError):
            continue
    if kill_pgids:
        time.sleep(0.5)
        for pgid in sorted(kill_pgids):
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(pgid, signal.SIGKILL)
    return terminated


class DbosTaskEngine:
    """analyze 任务的 DBOS 实现（curate/mine/write 随迁移第 7/10 步接入）。"""

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.db = self.home / "tasks.sqlite"
        self.home.mkdir(parents=True, exist_ok=True)
        migrate(self.db, TASKS_MIGRATIONS)
        self.events = EventLog(self.db)
        init_dbos(self.home / "dbos.sqlite")

    @staticmethod
    def _workflows() -> dict[TaskType, Any]:
        """任务类型 → DBOS 工作流函数分发表（submit/resume 共用）。

        延迟导入 + 模块属性访问：workflow 函数解析发生在调用期，测试对
        dbos_engine 模块的 monkeypatch 仍然生效，且无顶层循环导入。
        """
        import bacmap.tasks.engine.dbos_engine as _wf

        return {
            TaskType.ANALYZE: _wf.analyze_workflow,
            TaskType.CURATE: _wf.curate_workflow,
            TaskType.MINE: _wf.mine_workflow,
            TaskType.WRITE: _wf.write_workflow,
            TaskType.RECORD: _wf.record_workflow,
            TaskType.RESEARCH: _wf.research_workflow,
        }

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """sqlite3 的 with 块只提交事务不关闭连接——必须显式 close，
        否则 SSE 轮询（count_states 每秒一次）会持续泄漏文件句柄。"""
        conn = sqlite3.connect(self.db, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

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
        workflows = self._workflows()
        if task_type not in workflows:
            raise NotImplementedError(f"unsupported task type: {task_type}")
        p = params.model_dump() if isinstance(params, BaseModel) else dict(params)
        p.setdefault("home", str(self.home))
        # cores 不在此处给默认值（v1.10.19）：显式传入才生效，
        # 缺省由引擎读部署 config.yaml 的 threads（多核机器不再被写死的 8 截断）。
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
        if task_type == TaskType.ANALYZE:
            # v1.10.25：运行记录 started_at 优先取管线真实开始时间（_step_run），
            # 缺失时退回提交时间——不再是"登记运行记录那一刻"。仅 analyze 需要：
            # 其它任务把 params 交给严格校验（extra="forbid"），不能夹带字段。
            p.setdefault("submitted_at", now)

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

        from bacmap.config import debug_mode

        if debug_mode() and state == TaskState.AWAITING_APPROVAL:
            # 开发模式：审批门自动通过（签名仅用于审计，不是生产批准）。
            self.approve(
                task_id,
                Approval(
                    approver="debug:auto-approve",
                    decision="approve",
                    signature="DEBUG_MODE",
                    comment="auto-approved by debug mode",
                    at=datetime.now(UTC),
                ),
            )
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT state, message, current_step FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            if row is not None:
                state, message = TaskState(row["state"]), row["message"]

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
        # 任务 ID 一律为小写 hex（uuid4().hex / sha256 hex）；未过滤的
        # % 或 _ 前缀会被 LIKE 当通配符解析，把"非法输入"变成"前缀命中"。
        norm = prefix.lower()
        if not norm or any(c not in "0123456789abcdef" for c in norm):
            raise KeyError(f"no such task: {prefix}")
        with self._conn() as conn:
            exact = conn.execute(
                "SELECT task_id FROM tasks WHERE task_id = ?", (norm,)
            ).fetchone()
            if exact is not None:
                return TaskId(str(exact["task_id"]))
            rows = conn.execute(
                "SELECT task_id FROM tasks WHERE task_id LIKE ? ORDER BY created_at DESC",
                (norm + "%",),
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
        # v1.10.24：杀掉该任务遗留的生信进程树（snakemake 及其子进程
        # diamond/bakta/emapper 等）。DBOS 的 cancel 是协作式的——只标记
        # 工作流状态，不会终止正在执行的 subprocess。不杀的话 diamond
        # 会持续吃满 CPU 直到自然结束（实测取消后 >10 分钟仍在跑）。
        _kill_task_pipeline_processes(str(task_id))

    def pause(self, task_id: TaskId) -> None:
        """用户暂停（v1.10.22）：工作流在下一个边界（管线结束/步骤间）收场。

        正在执行的 snakemake 不会被强杀——长管线跑完当前规则后，守卫在
        步骤边界检测 paused 即终态返回。恢复用 :meth:`resume`。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, workflow_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        if row["state"] not in (TaskState.RUNNING.value, TaskState.PENDING.value):
            raise ValueError(
                f"task {task_id} state is {row['state']!r}; only running tasks can pause"
            )
        if row["workflow_id"]:
            try:
                DBOS.cancel_workflow(row["workflow_id"])
            except Exception:  # 工作流可能已终态：以任务行为准
                logger.warning("pause: cancel_workflow %s failed", task_id, exc_info=True)
        self._update_state(task_id, TaskState.PAUSED, "paused by user")

    def resume(self, task_id: TaskId) -> None:
        """恢复 paused/failed(interrupted) 任务（v1.10.22）。

        清掉旧工作流行后以**同一 task_id** 重建工作流：snakemake
        ``--rerun-incomplete`` 在同一 run 目录续跑，已完成规则不重算。
        """
        from dbos import DBOS as _DBOS

        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, task_type, params_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        if row["state"] not in (
            TaskState.PAUSED.value,
            TaskState.FAILED.value,
            TaskState.CANCELLED.value,
        ):
            raise ValueError(
                f"task {task_id} state is {row['state']!r}; "
                "only paused/failed/cancelled tasks can resume"
            )
        task_type = TaskType(row["task_type"])
        workflow = self._workflows().get(task_type)
        if workflow is None:
            raise ValueError(f"task type {task_type.value!r} cannot be resumed")
        try:
            _DBOS.delete_workflow(str(task_id))  # 旧工作流行（含孤儿 PENDING）
        except Exception:
            logger.warning("resume: delete_workflow %s failed", task_id, exc_info=True)
        params = json.loads(row["params_json"])
        params.setdefault("home", str(self.home))
        params["task_id"] = str(task_id)
        params["resumed"] = True

        with self._conn() as conn:
            conn.execute(
                "UPDATE tasks SET state = ?, message = '', current_step = ?, "
                "updated_at = ? WHERE task_id = ?",
                (
                    TaskState.RUNNING.value,
                    task_type.value,
                    datetime.now(UTC).isoformat(),
                    str(task_id),
                ),
            )
        from dbos import SetWorkflowID

        with SetWorkflowID(str(task_id)):
            _DBOS.start_workflow(workflow, params)
        self.events.append(
            EventType.TASK_SUBMITTED,
            task_id=str(task_id),
            actor="resume",
            payload={"task_type": row["task_type"], "resumed": True},
        )

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
