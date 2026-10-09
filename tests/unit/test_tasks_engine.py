"""DbosTaskEngine 回环测试（monkeypatch 管线执行，不跑真实 snakemake）。"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.tasks.spec import Approval, TaskState, TaskType


class _Proc:
    def __init__(self, rc: int) -> None:
        self.returncode = rc


def _sal_summary() -> dict:
    return {
        "sample": "SAM-001",
        "steps": {
            "species": {"verdict": "Salmonella"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
            "dec": {},
        },
    }


@pytest.fixture
def engine(tmp_path, monkeypatch):
    rep = tmp_path / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
    monkeypatch.setattr(eng, "_run_snakemake", lambda params: _Proc(0))
    monkeypatch.setattr(eng, "_step_create_run", lambda params: {"run_id": "test-run-1"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, params: None)
    e = eng.DbosTaskEngine(tmp_path)
    yield e
    eng.shutdown_dbos()


def _wait(e: eng.DbosTaskEngine, tid: str, timeout_s: float = 30.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = e.status(tid)
        if st.state != TaskState.RUNNING:
            return st
        time.sleep(0.2)
    return e.status(tid)


class TestDbosTaskEngine:
    def test_analyze_roundtrip_succeeded(self, engine):
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "tester")
        st = _wait(engine, tid)
        assert st.state == TaskState.SUCCEEDED
        assert st.current_step == "analyze"

    def test_analyze_failed_run(self, engine, monkeypatch):
        monkeypatch.setattr(eng, "_run_snakemake", lambda p: _Proc(1))
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "tester")
        st = _wait(engine, tid)
        assert st.state == TaskState.FAILED

    def test_gate_review_awaits_approval_then_approves(self, engine):
        tid = engine.submit(
            TaskType.ANALYZE,
            {
                "samples": ["SAM-001"],
                "interpretation_text": "该菌株为 E. coli，未检出 blaCTX-M-15。",
            },
            "tester",
        )
        st = _wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        engine.approve(
            tid,
            Approval(
                approver="reviewer", decision="approve", signature="sig", at=datetime.now(UTC)
            ),
        )
        assert engine.status(tid).state == TaskState.SUCCEEDED

    def test_unsupported_task_type_rejected(self, engine):
        with pytest.raises(NotImplementedError):
            engine.submit("bogus", {}, "tester")  # type: ignore[arg-type]

    def test_status_unknown_task_raises(self, engine):
        with pytest.raises(KeyError):
            engine.status("no-such-task")
