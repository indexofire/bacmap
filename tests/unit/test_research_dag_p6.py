"""P6：节点缓存、并行执行、单节点重放与产物 GC。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import BaseModel

from bacmap.research.dag import ResearchDag, parallel_waves
from bacmap.research.dagstore import DagStore
from bacmap.research.operators import unregister
from bacmap.research.operators.spec import PortType, operator
from bacmap.store.migrations import migrate
from bacmap.tasks.engine import dag_engine
from bacmap.tasks.spec import TASKS_MIGRATIONS

CALLS = {"n": 0}


class _Params(BaseModel):
    value: int = 1


@pytest.fixture(scope="module", autouse=True)
def _operators():
    @operator(
        name="test.cached",
        version="1.0",
        doc="deterministic emit",
        inputs={"in": PortType.TABLE},
        optional_inputs=("in",),
        outputs={"out": PortType.TABLE},
        params=_Params,
    )
    def _cached(ctx):  # type: ignore[no-untyped-def]
        CALLS["n"] += 1
        return {"out": {"value": ctx.params["value"]}}

    yield
    unregister("test.cached@1.0")


def _dag(nodes: list[dict], **overrides: object) -> dict:
    base = {"schema": "bacmap.research.dag/1", "nodes": nodes}
    base.update(overrides)
    return base


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dag_engine, "_step_dag_operator", lambda payload: dag_engine.execute_node(payload)
    )


def test_cache_hits_across_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    CALLS["n"] = 0
    dag = _dag([{"id": "a", "op": "test.cached@1.0", "params": {"value": 7}}])
    first = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert first["status"] == "SUCCEEDED"
    assert CALLS["n"] == 1

    second = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t2", "dag": dag})
    assert second["status"] == "SUCCEEDED"
    assert CALLS["n"] == 1  # 跨任务缓存命中，未再次执行
    with DagStore(tmp_path) as store:
        rows = store.node_rows("t2")
        assert rows[0]["cache_hit"] == 1
        outputs = json.loads(rows[0]["outputs_json"])
        assert store.load_artifact(outputs["out"])["value"] == {"value": 7}
        # 缓存复用后，第二个任务仍能列出（并导出）上游产物
        assert [row["artifact_id"] for row in store.list_artifacts("t2")] == [outputs["out"]]


def test_different_params_miss_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存键包含参数：参数不同必须重新执行。"""
    _patch(monkeypatch)
    CALLS["n"] = 0
    # 通过 params 不同来避开缓存，确认计数器仍然递增（基线行为）
    dag = _dag([{"id": "a", "op": "test.cached@1.0", "params": {"value": 8}}])
    dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    dag2 = _dag([{"id": "a", "op": "test.cached@1.0", "params": {"value": 9}}])
    dag_engine.run_dag({"home": str(tmp_path), "task_id": "t2", "dag": dag2})
    assert CALLS["n"] == 2


def test_parallel_waves_and_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    dag = _dag(
        [
            {"id": "a", "op": "test.cached@1.0", "params": {"value": 1}},
            {"id": "b", "op": "test.cached@1.0", "params": {"value": 2}},
            {
                "id": "c",
                "op": "test.cached@1.0",
                "params": {"value": 3},
                "inputs": {"in": "a.out"},
            },
        ],
        execution={"mode": "parallel", "on_failure": "fail_fast"},
    )
    model = ResearchDag.model_validate(dag)
    model.validate_dag()
    assert [[n.id for n in wave] for wave in parallel_waves(model)] == [["a", "b"], ["c"]]

    result = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert result["status"] == "SUCCEEDED"
    assert {row["node_id"] for row in result["nodes"]} == {"a", "b", "c"}


def test_gc_keeps_referenced_artifacts(tmp_path: Path) -> None:
    with DagStore(tmp_path) as store:
        store.ensure_run("t1", "hash", 2)
        keep = store.put_artifact(
            type_="Table", value={"keep": 1}, task_id="t1", node_id="n1"
        )
        drop = store.put_artifact(
            type_="Table", value={"drop": 1}, task_id="t1", node_id="n1"
        )
        store.mark_running("t1", "n1", "test.cached@1.0")
        store.mark_succeeded("t1", "n1", {"out": keep})

        dry = store.gc(keep_days=0, dry_run=True)
        assert dry["artifacts"] == 1
        assert dry["ids"] == [drop]

        applied = store.gc(keep_days=0, dry_run=False)
        assert applied["artifacts"] == 1
        assert store.list_artifacts("t1")[0]["artifact_id"] == keep
        assert store.load_artifact(keep)["value"] == {"keep": 1}
        with pytest.raises(KeyError):
            store.load_artifact(drop)


def test_replay_matches_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bacmap.interfaces.cli import research_dag as cli

    _patch(monkeypatch)
    dag = _dag([{"id": "a", "op": "test.cached@1.0", "params": {"value": 5}}])
    assert dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})[
        "status"
    ] == "SUCCEEDED"

    migrate(tmp_path / "tasks.sqlite", TASKS_MIGRATIONS)
    with sqlite3.connect(tmp_path / "tasks.sqlite") as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("t1", "research", "succeeded", json.dumps({"analysis": "dag", "dag": dag}), "t", "now", "now"),
        )
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        cli.run_replay(
            argparse.Namespace(home=str(tmp_path), task_id="t1", node="a", json=True)
        )
    payload = json.loads(buffer.getvalue())
    assert payload["status"] == "succeeded"
    assert payload["match"] is True
