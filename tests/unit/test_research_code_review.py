"""P4：代码审核三档（always/plan/off）与审批后重启。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.research.operators.spec import SandboxRequest, SandboxResult
from bacmap.store.migrations import migrate
from bacmap.tasks.engine import dag_engine
from bacmap.tasks.spec import TASKS_MIGRATIONS

DAG = {
    "schema": "bacmap.research.dag/1",
    "data_class": 3,
    "nodes": [
        {
            "id": "s",
            "op": "script.python@1.0",
            "params": {"code": "print('hi')", "objective": "", "image": "img"},
        }
    ],
}


def _home(tmp_path: Path, level: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text(
        f"[research.approval]\ncode_review = '{level}'\n", encoding="utf-8"
    )
    migrate(tmp_path / "tasks.sqlite", TASKS_MIGRATIONS)
    return tmp_path


def _fake_runner(request: SandboxRequest) -> SandboxResult:
    (request.workspace / "result.json").write_text('{"ok": true}', encoding="utf-8")
    return SandboxResult(returncode=0, backend="fake")


def _approve(home: Path, task_id: str) -> None:
    with sqlite3.connect(home / "tasks.sqlite") as conn:
        conn.execute(
            "INSERT INTO approvals (task_id, approver, decision, signature, comment, at)"
            " VALUES (?,?,?,?,?,?)",
            (task_id, "tester", "approve", "", "", "2026-01-01T00:00:00+00:00"),
        )


def test_always_pauses_before_code_and_runs_after_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path, "always")
    monkeypatch.setattr(dag_engine, "_step_dag_operator", dag_engine.execute_node)
    monkeypatch.setattr(dag_engine, "run_sandbox", _fake_runner)

    first = dag_engine.run_dag({"home": str(home), "task_id": "t1", "dag": DAG})
    assert first["status"] == "AWAITING_APPROVAL"
    assert first["message"] == "code_approval:s"
    assert first["nodes"] == []

    _approve(home, "t1")
    second = dag_engine.run_dag({"home": str(home), "task_id": "t1", "dag": DAG})
    assert second["status"] == "SUCCEEDED"
    assert [row["node_id"] for row in second["nodes"]] == ["s"]


def test_plan_tier_executes_without_extra_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path, "plan")
    monkeypatch.setattr(dag_engine, "_step_dag_operator", dag_engine.execute_node)
    monkeypatch.setattr(dag_engine, "run_sandbox", _fake_runner)
    result = dag_engine.run_dag({"home": str(home), "task_id": "t2", "dag": DAG})
    assert result["status"] == "SUCCEEDED"


def test_off_tier_executes_without_extra_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path, "off")
    monkeypatch.setattr(dag_engine, "_step_dag_operator", dag_engine.execute_node)
    monkeypatch.setattr(dag_engine, "run_sandbox", _fake_runner)
    result = dag_engine.run_dag({"home": str(home), "task_id": "t3", "dag": DAG})
    assert result["status"] == "SUCCEEDED"


def test_finalize_research_approval_restarts_dag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from datetime import UTC, datetime

    from bacmap.tasks.engine import task_engine as te
    from bacmap.tasks.engine._outcomes import _finalize_research_approval
    from bacmap.tasks.spec import Approval, TaskState

    home = _home(tmp_path, "always")
    engine = te.DbosTaskEngine(home)
    now = datetime.now(UTC).isoformat()
    with engine._conn() as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                "t1",
                "research",
                "awaiting_approval",
                json.dumps({"analysis": "dag", "task_id": "t1"}),
                "test",
                now,
                now,
            ),
        )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        te.DbosTaskEngine,
        "_restart_workflow",
        lambda self, tid, task_type, params, actor: calls.append((str(tid), actor)),
    )
    approval = Approval(
        approver="tester", decision="approve", signature="", at=datetime.now(UTC)
    )
    state, message = _finalize_research_approval(home, "t1", approval)
    assert state is TaskState.RUNNING
    assert "tester" in message
    assert calls == [("t1", "approval")]
