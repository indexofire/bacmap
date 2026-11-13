"""运行记录时间与任务终态落库（v1.10.25）。

两个回归点：
1. ``runs.create_run`` 必须接受并落库真实执行区间——历史实现里 started_at
   由 default_factory 在"管线跑完、登记运行记录"那一刻生成，finished_at
   紧接着写入，导致每轮运行耗时恒为几十毫秒；
2. 任务终态必须在工作流结束时写回 tasks.sqlite，而不是等下一次
   ``DbosTaskEngine.status()`` 读取（曾出现 00:26 跑完、06:21 才变 succeeded）。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from bacmap.store import runs
from bacmap.store.migrations import migrate
from bacmap.tasks.engine.dbos_engine import _run_times, mark_task_terminal
from bacmap.tasks.spec import TASKS_MIGRATIONS


def _workflow_dir(tmp_path):
    wf = tmp_path / "wf"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 2\n")
    return wf


def test_create_run_records_real_execution_window(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
    monkeypatch.setattr(runs, "load_ref_databases", lambda refs_dir: [])
    started = datetime(2026, 11, 12, 22, 22, 56, tzinfo=UTC)
    ended = datetime(2026, 11, 13, 0, 26, 34, tzinfo=UTC)
    db_path = tmp_path / "runs.sqlite"

    run = runs.create_run(
        workflow="bacmap",
        workflow_dir=_workflow_dir(tmp_path),
        strain_ids=["26SAL0501"],
        db_path=db_path,
        started_at=started,
        finished_at=ended,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT started_at, finished_at FROM analysis_runs WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()
    assert row[0] == started.isoformat()
    assert row[1] == ended.isoformat()
    assert (ended - started).total_seconds() == 2 * 3600 + 3 * 60 + 38


def test_create_run_keeps_defaults_when_times_omitted(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "probe_tool_versions", lambda tools: {})
    monkeypatch.setattr(runs, "load_ref_databases", lambda refs_dir: [])
    db_path = tmp_path / "runs.sqlite"
    before = datetime.now(UTC)
    run = runs.create_run(
        workflow="bacmap",
        workflow_dir=_workflow_dir(tmp_path),
        strain_ids=[],
        db_path=db_path,
    )
    assert run.started_at >= before
    assert run.finished_at is None


def test_run_times_prefer_pipeline_window():
    started, ended = _run_times(
        {"started_at": "2026-11-12T22:22:56+00:00", "ended_at": "2026-11-13T00:26:34+00:00"},
        {"submitted_at": "2026-11-12T22:22:50+00:00"},
    )
    assert started == datetime(2026, 11, 12, 22, 22, 56, tzinfo=UTC)
    assert ended == datetime(2026, 11, 13, 0, 26, 34, tzinfo=UTC)


def test_run_times_fall_back_to_submitted_at():
    started, ended = _run_times({}, {"submitted_at": "2026-11-12T13:19:12+00:00"})
    assert started == datetime(2026, 11, 12, 13, 19, 12, tzinfo=UTC)
    assert ended is None


def _seed_task(tmp_path, task_id: str, state: str = "running") -> sqlite3.Connection:
    db = tmp_path / "tasks.sqlite"
    migrate(db, TASKS_MIGRATIONS)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at, workflow_id, current_step)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                "analyze",
                state,
                "{}",
                "test",
                "2026-11-12T00:00:00+00:00",
                "2026-11-12T00:00:00+00:00",
                task_id,
                "analyze",
            ),
        )
    return sqlite3.connect(db)


def test_mark_task_terminal_writes_succeeded(tmp_path):
    conn = _seed_task(tmp_path, "t1")
    assert mark_task_terminal(tmp_path, "t1", {"status": "SUCCEEDED", "gates": {}}) is True
    state = conn.execute("SELECT state FROM tasks WHERE task_id='t1'").fetchone()[0]
    assert state == "succeeded"
    # 终态不可被再次迁移/降级
    assert mark_task_terminal(tmp_path, "t1", {"status": "FAILED", "message": "x"}) is False
    assert conn.execute("SELECT state FROM tasks WHERE task_id='t1'").fetchone()[0] == "succeeded"


def test_mark_task_terminal_maps_failure_message(tmp_path):
    conn = _seed_task(tmp_path, "t2")
    assert mark_task_terminal(tmp_path, "t2", {"status": "FAILED", "message": "snakemake 退出码 2"})
    state, message = conn.execute("SELECT state, message FROM tasks WHERE task_id='t2'").fetchone()
    assert state == "failed"
    assert "退出码 2" in message


def test_mark_task_terminal_ignores_missing_task(tmp_path):
    _seed_task(tmp_path, "t3")
    assert mark_task_terminal(tmp_path, "", {"status": "SUCCEEDED"}) is False
    assert mark_task_terminal(tmp_path, "no-such", {"status": "SUCCEEDED"}) is False
