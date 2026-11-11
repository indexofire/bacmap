"""中断任务恢复（v1.10.22）。

DBOS 的启动恢复线程按 ``application_version`` 过滤 PENDING 工作流——代码
变更后版本哈希漂移，旧版本的中断工作流成为**永久孤儿**（任务行 running
但永远无人执行，实测发生于断电重启 + 代码升级之后）。本模块在 DBOS
启动后做两件事：

- **adopt**：把旧版本的 PENDING 工作流的 ``application_version`` 更新为
  当前版本并主动触发恢复——工作流步骤输入均为 JSON 标量，跨版本安全；
  snakemake 以 ``--rerun-incomplete`` 在同一 run 目录续跑，已完成规则不重算。
- **reconcile**：任务行 running 而工作流已终态（ERROR/CANCELLED）或不存在
  → 任务行改标 failed（interrupted），用户可 ``bacmap task resume <id>``
  恢复；PENDING 的保留 running（adopt 后会被接续执行）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_STOP_STATUSES = {"SUCCESS", "ERROR", "CANCELLED"}


def _current_app_version() -> str:
    from dbos._core import GlobalParams

    return str(GlobalParams.app_version)


def adopt_stale_pending_workflows(dbos_db: Path) -> int:
    """把旧版本的本地 PENDING 工作流"收养"为当前版本并触发恢复。

    返回收养数。只动 ``status='PENDING' AND executor_id='local'`` 的行；
    终态工作流（SUCCESS/ERROR/CANCELLED）永不触碰。
    """
    if not dbos_db.is_file():
        return 0
    version = _current_app_version()
    try:
        with sqlite3.connect(dbos_db) as conn:
            cur = conn.execute(
                "UPDATE workflow_status SET application_version = ? "
                "WHERE status = 'PENDING' AND executor_id = 'local' "
                "AND application_version != ?",
                (version, version),
            )
            adopted = cur.rowcount or 0
    except sqlite3.Error:
        logger.warning("adopt_stale_pending_workflows failed", exc_info=True)
        return 0
    if adopted:
        logger.info("adopted %d stale pending workflow(s) to version %s", adopted, version)
        from dbos import DBOS

        # 主动触发恢复（launch 线程启动时的查询早于我们的收养，不会重查）
        try:
            DBOS._recover_pending_workflows(["local"])
        except Exception:  # 恢复失败留给 reconcile 对账兜底
            logger.warning("post-adopt recovery trigger failed", exc_info=True)
    return adopted


def reconcile_stuck_tasks(home: Path) -> list[str]:
    """running 任务 × 工作流终态/缺失 → 改标 failed（可 resume）。

    返回被对账的 task_id 列表。PENDING/RUNNING 工作流对应的任务不动。
    """
    tasks_db = home / "tasks.sqlite"
    dbos_db = home / "dbos.sqlite"
    if not tasks_db.is_file():
        return []
    try:
        with sqlite3.connect(tasks_db) as conn:
            rows = conn.execute(
                "SELECT task_id FROM tasks WHERE state = 'running'"
            ).fetchall()
    except sqlite3.Error:
        return []
    stuck: list[tuple[str, str]] = []
    for (task_id,) in rows:
        status = _workflow_status(dbos_db, str(task_id))
        if status is None or status in _STOP_STATUSES:
            stuck.append((str(task_id), status or "absent"))
    if not stuck:
        return []
    try:
        with sqlite3.connect(tasks_db) as conn:
            for task_id, ws in stuck:
                conn.execute(
                    "UPDATE tasks SET state = 'failed', message = ?, updated_at = ? "
                    "WHERE task_id = ? AND state = 'running'",
                    (
                        f"interrupted (workflow {ws}); 恢复：bacmap task resume {task_id}",
                        _now(),
                        task_id,
                    ),
                )
    except sqlite3.Error:
        logger.warning("reconcile_stuck_tasks update failed", exc_info=True)
        return []
    return [t for t, _ in stuck]


def _workflow_status(dbos_db: Path, workflow_uuid: str) -> str | None:
    if not dbos_db.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{dbos_db}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT status FROM workflow_status WHERE workflow_uuid = ?",
                (workflow_uuid,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def recover_interrupted(home: Path, dbos_db: Path | None = None) -> dict:
    """DBOS 启动后的组合入口：收养跨版本 PENDING → 对账卡死任务行 → 别名自愈。"""
    from bacmap.store.results_layout import repair_flat_aliases

    dbos_db = dbos_db or (home / "dbos.sqlite")
    adopted = adopt_stale_pending_workflows(dbos_db)
    reconciled = reconcile_stuck_tasks(home)
    alias = repair_flat_aliases(home)
    return {"adopted": adopted, "reconciled": reconciled, **alias}
