"""中断任务恢复（v1.10.22）：跨版本收养 + 卡死任务对账。

背景：DBOS 恢复线程按 application_version 过滤 PENDING——断电重启叠加
代码升级后，旧版本工作流成为永久孤儿（任务行 running、进程不存在，
实测）。recovery 在 DBOS 启动后收养旧 PENDING 并对账卡死任务行。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bacmap.tasks.engine.recovery import (
    adopt_stale_pending_workflows,
    reconcile_stuck_tasks,
)


def _seed_dbos(db: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (workflow_uuid, status, application_version)"""
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE workflow_status (workflow_uuid TEXT, status TEXT,"
            " executor_id TEXT DEFAULT 'local', application_version TEXT)"
        )
        conn.executemany("INSERT INTO workflow_status VALUES (?, ?, 'local', ?)", rows)


def _seed_tasks(db: Path, rows: list[tuple[str, str]]) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE tasks (task_id TEXT, state TEXT, message TEXT DEFAULT '', updated_at TEXT DEFAULT '', workflow_id TEXT DEFAULT '')")
        conn.executemany("INSERT INTO tasks (task_id, state) VALUES (?, ?)", rows)


class TestAdopt:
    def test_adopts_stale_pending_all_versions(self, tmp_path, monkeypatch):
        db = tmp_path / "dbos.sqlite"
        _seed_dbos(db, [("w-old", "PENDING", "v111"), ("w-cur", "PENDING", "v222"), ("w-done", "SUCCESS", "v111")])
        triggered = []
        monkeypatch.setattr(
            "dbos.DBOS._recover_pending_workflows",
            lambda ids: triggered.extend(ids),
        )
        monkeypatch.setattr(
            "bacmap.tasks.engine.recovery._current_app_version", lambda: "v222"
        )
        adopted = adopt_stale_pending_workflows(db)
        assert adopted == 1  # 只收养旧版本 PENDING；当前版本不动、SUCCESS 不动
        assert triggered == ["local"]  # 收养后主动触发恢复
        with sqlite3.connect(db) as conn:
            ver = conn.execute(
                "SELECT application_version FROM workflow_status WHERE workflow_uuid='w-old'"
            ).fetchone()[0]
        assert ver == "v222"

    def test_no_pending_noop(self, tmp_path, monkeypatch):
        db = tmp_path / "dbos.sqlite"
        _seed_dbos(db, [("w", "SUCCESS", "v1")])
        monkeypatch.setattr(
            "bacmap.tasks.engine.recovery._current_app_version", lambda: "v2"
        )
        assert adopt_stale_pending_workflows(db) == 0


class TestReconcile:
    def test_running_task_with_terminal_workflow_marked_failed(self, tmp_path):
        _seed_tasks(tmp_path / "tasks.sqlite", [("t1", "running"), ("t2", "running")])
        _seed_dbos(
            tmp_path / "dbos.sqlite",
            [("t1", "ERROR", "v1"), ("t2", "PENDING", "v1")],
        )
        reconciled = reconcile_stuck_tasks(tmp_path)
        assert reconciled == ["t1"]  # ERROR → failed；PENDING 保留（可收养）
        with sqlite3.connect(tmp_path / "tasks.sqlite") as conn:
            states = dict(conn.execute("SELECT task_id, state FROM tasks").fetchall())
        assert states == {"t1": "failed", "t2": "running"}

    def test_success_workflow_is_not_stuck(self, tmp_path):
        # SUCCESS 工作流对应的 running 任务行是"完成但尚未对账"的正常中间态：
        # 标成 failed 会绕过审批门并篡改已成功任务的终态。
        _seed_tasks(tmp_path / "tasks.sqlite", [("t4", "running")])
        _seed_dbos(tmp_path / "dbos.sqlite", [("t4", "SUCCESS", "v1")])
        assert reconcile_stuck_tasks(tmp_path) == []
        with sqlite3.connect(tmp_path / "tasks.sqlite") as conn:
            state = conn.execute(
                "SELECT state FROM tasks WHERE task_id = 't4'"
            ).fetchone()[0]
        assert state == "running"

    def test_absent_workflow_also_stuck(self, tmp_path):
        _seed_tasks(tmp_path / "tasks.sqlite", [("t3", "running")])
        # dbos.sqlite 不存在 → 工作流缺失 → 卡死
        assert reconcile_stuck_tasks(tmp_path) == ["t3"]

    def test_no_tasks_noop(self, tmp_path):
        assert reconcile_stuck_tasks(tmp_path) == []
