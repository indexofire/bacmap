"""防唤醒守卫（v1.10.21）：已取消/失败的任务在 DBOS 重放时立即终态收场。

DBOS 在进程重启时恢复一切非终态工作流——若只看工作流状态，被人工取消的
任务会在重启后被"唤醒"继续占用管线锁（实测发生过）。守卫在任务行
（tasks.sqlite）与工作流之间建立双终态一致性。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bacmap.tasks.engine.dbos_engine import _cancelled_envelope, _task_state_cancelled


def _seed_tasks_db(db: Path, task_id: str, state: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, state TEXT)"
        )
        conn.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?)", (task_id, state))


class TestTaskStateCancelled:
    def test_cancelled_task_detected(self, tmp_path: Path):
        _seed_tasks_db(tmp_path / "tasks.sqlite", "t1", "cancelled")
        assert _task_state_cancelled("t1", str(tmp_path)) is True

    def test_failed_task_counts_as_terminal(self, tmp_path: Path):
        """failed 也是终态：历史失败工作流的重放同样不该继续跑。"""
        _seed_tasks_db(tmp_path / "tasks.sqlite", "t2", "failed")
        assert _task_state_cancelled("t2", str(tmp_path)) is True

    def test_running_task_not_cancelled(self, tmp_path: Path):
        _seed_tasks_db(tmp_path / "tasks.sqlite", "t3", "running")
        assert _task_state_cancelled("t3", str(tmp_path)) is False

    def test_missing_db_or_task(self, tmp_path: Path):
        assert _task_state_cancelled("t4", str(tmp_path)) is False
        _seed_tasks_db(tmp_path / "tasks.sqlite", "t5", "succeeded")
        assert _task_state_cancelled("missing", str(tmp_path)) is False

    def test_empty_task_id(self, tmp_path: Path):
        _seed_tasks_db(tmp_path / "tasks.sqlite", "t6", "cancelled")
        assert _task_state_cancelled("", str(tmp_path)) is False


class TestCancelledEnvelope:
    def test_envelope_is_terminal_and_self_describing(self):
        env = _cancelled_envelope("abc123")
        assert env["status"] == "CANCELLED"
        assert "abc123" in env["message"]
        assert env["gates"] == {}
