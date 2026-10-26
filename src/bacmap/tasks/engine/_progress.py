"""任务步骤进度（v1.5.2）：写 ``tasks.current_step`` 并追加 ``task.step`` 事件。

在既有 DBOS step 函数体内调用（不新增 step，避免改变在途工作流的回放序列）；
DBOS 不重放已完成的 step，故正常情况下每步只记一次（重试时至多重复记一次）。
进度是展示信息：记录失败只告警，不得影响分析本身。
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from bacmap.tasks.events import EventLog, EventType

logger = logging.getLogger(__name__)


def record_step(home: Path, task_id: str, step: str) -> None:
    db = Path(home) / "tasks.sqlite"
    if not task_id or not db.is_file():
        return
    try:
        with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
            changed = conn.execute(
                "UPDATE tasks SET current_step = ?, updated_at = ? WHERE task_id = ?",
                (step, datetime.now(UTC).isoformat(), task_id),
            ).rowcount
        if changed:
            EventLog(db).append(EventType.TASK_STEP, task_id=task_id, payload={"step": step})
    except sqlite3.Error:
        logger.warning("record_step failed for %s/%s", task_id, step, exc_info=True)
