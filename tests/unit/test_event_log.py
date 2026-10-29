"""领域事件日志（v1.5.2）：追加式、单调序号、可按游标续读；计划/任务关键转换写事件。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.store.migrations import schema_version
from bacmap.tasks.events import EventLog, EventType
from bacmap.tasks.spec import TASKS_MIGRATIONS
from bacmap.tools.spec import DataClass


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "tasks.sqlite")


class TestEventLog:
    def test_append_returns_monotonic_seq(self, log: EventLog):
        a = log.append(EventType.TASK_SUBMITTED, task_id="t1", actor="cli", payload={"k": 1})
        b = log.append(EventType.TASK_STEP, task_id="t1", payload={"step": "pipeline"})
        assert b > a > 0
        assert log.last_seq() == b

    def test_list_after_cursor_and_limit(self, log: EventLog):
        seqs = [log.append(EventType.TASK_STEP, task_id="t", payload={"i": i}) for i in range(5)]
        got = log.list(after=seqs[1], limit=2)
        assert [e.seq for e in got] == seqs[2:4]
        assert [e.payload["i"] for e in got] == [2, 3]

    def test_filters(self, log: EventLog):
        log.append(EventType.TASK_STEP, task_id="t1")
        log.append(EventType.PLAN_CREATED, plan_id="p1")
        log.append(EventType.TASK_STEP, task_id="t2")
        assert [e.task_id for e in log.list(task_id="t2")] == ["t2"]
        assert [e.type for e in log.list(plan_id="p1")] == [EventType.PLAN_CREATED]

    def test_event_fields_roundtrip(self, log: EventLog):
        log.append(
            EventType.TASK_STATE,
            task_id="t1",
            actor="engine",
            payload={"state": "failed", "message": "x"},
            data_class=DataClass.D2,
        )
        (e,) = log.list()
        assert e.type is EventType.TASK_STATE and e.actor == "engine"
        assert e.data_class is DataClass.D2 and e.payload == {"state": "failed", "message": "x"}
        assert len(e.event_id) == 32 and e.occurred_at.endswith("+00:00")

    def test_persistent_across_instances(self, tmp_path: Path):
        EventLog(tmp_path / "tasks.sqlite").append(EventType.PLAN_CREATED, plan_id="p")
        assert len(EventLog(tmp_path / "tasks.sqlite").list()) == 1

    def test_unknown_type_rejected(self, log: EventLog):
        with pytest.raises(ValueError):
            log.append(EventType("task.exploded"))

    def test_schema_is_migrated(self, tmp_path: Path, log: EventLog):
        assert schema_version(tmp_path / "tasks.sqlite") == len(TASKS_MIGRATIONS) >= 3

    def test_limit_is_bounded(self, log: EventLog):
        for _ in range(3):
            log.append(EventType.TASK_STEP, task_id="t")
        assert len(log.list(limit=0)) == 1
        assert len(log.list(limit=10_000)) == 3


class TestRecordStep:
    def _db(self, tmp_path: Path) -> Path:
        from bacmap.store.migrations import migrate

        db = tmp_path / "tasks.sqlite"
        migrate(db, TASKS_MIGRATIONS)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, task_type, state, created_at, updated_at)"
                " VALUES ('t1', 'analyze', 'running', 'x', 'x')"
            )
        return db

    def test_updates_current_step_and_emits(self, tmp_path: Path):
        from bacmap.tasks.engine._progress import record_step

        db = self._db(tmp_path)
        record_step(tmp_path, "t1", "pipeline")
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT current_step FROM tasks").fetchone()[0] == "pipeline"
        (e,) = EventLog(db).list(task_id="t1")
        assert e.type is EventType.TASK_STEP and e.payload == {"step": "pipeline"}

    def test_unknown_task_or_missing_db_is_noop(self, tmp_path: Path):
        from bacmap.tasks.engine._progress import record_step

        record_step(tmp_path, "t1", "pipeline")  # 库不存在：不创建、不报错
        assert not (tmp_path / "tasks.sqlite").exists()
        db = self._db(tmp_path)
        record_step(tmp_path, "nope", "pipeline")
        assert EventLog(db).list() == []


class TestEngineEmits:
    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        import bacmap.tasks.engine.dbos_engine as eng
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def test_submit_and_cancel(self, engine):
        from bacmap.tasks.spec import TaskType

        tid = engine.submit(TaskType.ANALYZE, {"samples": ["A"]}, "cli:me")
        engine.cancel(tid)
        events = EventLog(engine.db).list(task_id=tid)
        assert [e.type for e in events] == [EventType.TASK_SUBMITTED, EventType.TASK_STATE]
        assert events[0].actor == "cli:me" and events[0].payload["task_type"] == "analyze"
        assert events[1].payload["state"] == "cancelled"

    def test_idempotent_resubmit_emits_once(self, engine):
        from bacmap.tasks.spec import TaskId, TaskType

        tid = TaskId("b" * 32)
        engine.submit(TaskType.ANALYZE, {"samples": ["A"]}, "x", task_id=tid)
        engine.submit(TaskType.ANALYZE, {"samples": ["A"]}, "x", task_id=tid)
        assert len(EventLog(engine.db).list(task_id=tid)) == 1

    def test_approval_emits_decision_and_state(self, engine):
        from datetime import UTC, datetime

        from bacmap.tasks.spec import Approval, TaskState, TaskType

        tid = engine.submit(TaskType.WRITE, {"draft": "x"}, "cli")
        engine._update_state(tid, TaskState.AWAITING_APPROVAL)
        engine.approve(
            tid, Approval(approver="ann", decision="reject", signature="s", at=datetime.now(UTC))
        )
        types = [e.type for e in EventLog(engine.db).list(task_id=tid)]
        assert EventType.TASK_APPROVAL in types
        assert types[-1] is EventType.TASK_STATE


class TestPlanEmits:
    def test_plan_lifecycle_events(self, tmp_path: Path):
        from bacmap.application.plans import PlanService
        from bacmap.tasks.params import AnalyzeParams

        class _Engine:
            def submit(self, task_type, params, by, *, task_id=None):
                return task_id

        svc = PlanService(_Engine(), tmp_path / "tasks.sqlite")
        rec = svc.create([AnalyzeParams(samples=["A"])], "", "mcp-x")
        v2 = svc.revise(rec.plan_id, [AnalyzeParams(samples=["B"])], "", "mcp-x")
        svc.confirm(rec.plan_id, 2, v2.plan_hash, "cli:me")
        types = [e.type for e in EventLog(tmp_path / "tasks.sqlite").list(plan_id=rec.plan_id)]
        assert types == [
            EventType.PLAN_CREATED,
            EventType.PLAN_REVISED,
            EventType.PLAN_CONFIRMED,
            EventType.PLAN_SUBMITTED,
        ]
        rec2 = svc.create([AnalyzeParams(samples=["C"])], "", "mcp-x")
        svc.reject(rec2.plan_id, 1, "no", "cli:me")
        assert EventLog(tmp_path / "tasks.sqlite").list(plan_id=rec2.plan_id)[-1].type is (
            EventType.PLAN_REJECTED
        )


class TestWorkflowProgress:
    def test_analyze_records_steps(self, tmp_path: Path, monkeypatch):
        import contextlib
        import json
        import time

        import bacmap.tasks.engine.dbos_engine as eng
        from bacmap.tasks.spec import TaskType

        rep = tmp_path / "results" / "S1" / "report"
        rep.mkdir(parents=True)
        (rep / "S1_summary.json").write_text(json.dumps({"sample": "S1", "steps": {}}))

        class _Proc:
            returncode = 0

        class _Arb:
            @contextlib.contextmanager
            def heavy_step(self):
                yield

        monkeypatch.setattr(eng, "_run_snakemake", lambda p: _Proc())
        monkeypatch.setattr(eng, "_memory_arbiter", lambda: _Arb())
        monkeypatch.setattr(eng, "_fastqs", lambda home, samples: [])
        from bacmap.store import runs

        class _Run:
            run_id = "run-1"

        monkeypatch.setattr(runs, "create_run", lambda **kw: _Run())
        monkeypatch.setattr(runs, "finalize_run", lambda *a, **kw: None)
        monkeypatch.setattr(eng, "_generate_report_for", lambda s, *a: {"sample_id": s})
        engine = eng.DbosTaskEngine(tmp_path)
        try:
            tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
            deadline = time.time() + 30
            while time.time() < deadline and engine.status(tid).state.value == "running":
                time.sleep(0.2)
            steps = [
                e.payload["step"]
                for e in EventLog(engine.db).list(task_id=tid)
                if e.type is EventType.TASK_STEP
            ]
            assert steps[:3] == ["pipeline", "run_record", "ingest_and_gates"]
            assert engine.status(tid).current_step == steps[-1]
            assert EventLog(engine.db).list(task_id=tid)[-1].type is EventType.TASK_STATE
        finally:
            eng.shutdown_dbos()
