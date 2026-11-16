"""研究编排层 P1：DAG 执行器、产物库与内置算子链路。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import BaseModel

from bacmap.research import dagstore
from bacmap.research.dag import ResearchDag
from bacmap.research.dagstore import DagStore
from bacmap.research.operators import unregister
from bacmap.research.operators.spec import PortType, operator
from bacmap.tasks.engine import dag_engine


class _EmitParams(BaseModel):
    value: int = 1


class _DoubleParams(BaseModel):
    factor: int = 2


class _BoomParams(BaseModel):
    message: str = "boom"


@pytest.fixture(scope="module", autouse=True)
def _test_operators():
    @operator(
        name="test.emit",
        version="1.0",
        doc="emit a table",
        inputs={},
        outputs={"out": PortType.TABLE},
        params=_EmitParams,
    )
    def _emit(ctx):  # type: ignore[no-untyped-def]
        return {"out": {"value": ctx.params["value"]}}

    @operator(
        name="test.double",
        version="1.0",
        doc="double a table value",
        inputs={"in": PortType.TABLE},
        outputs={"out": PortType.TABLE},
        params=_DoubleParams,
    )
    def _double(ctx):  # type: ignore[no-untyped-def]
        return {"out": {"value": int(ctx.inputs["in"]["value"]) * ctx.params["factor"]}}

    @operator(
        name="test.boom",
        version="1.0",
        doc="always fails",
        inputs={"in": PortType.TABLE},
        outputs={"out": PortType.TABLE},
        params=_BoomParams,
    )
    def _boom(ctx):  # type: ignore[no-untyped-def]
        raise RuntimeError(ctx.params["message"])

    yield
    for ref in ("test.emit@1.0", "test.double@1.0", "test.boom@1.0"):
        unregister(ref)


def _dag(nodes, checkpoints=None) -> dict:
    return {
        "schema": "bacmap.research.dag/1",
        "nodes": nodes,
        "checkpoints": checkpoints or [],
    }


def _patch_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dag_engine, "_step_dag_operator", lambda payload: dag_engine.execute_node(payload)
    )


# ---------------------------------------------------------------------------
# 产物库
# ---------------------------------------------------------------------------


def test_artifact_store_is_content_addressed(tmp_path: Path) -> None:
    with DagStore(tmp_path) as store:
        first = store.put_artifact(
            type_="Table", value={"a": 1}, task_id="t1", node_id="n1"
        )
        second = store.put_artifact(
            type_="Table", value={"a": 1}, task_id="t2", node_id="n2"
        )
        assert first == second
        assert first.startswith("sha256:")
        assert store.load_artifact(first)["value"] == {"a": 1}
        assert len(store.list_artifacts("t1")) == 1
        assert store.list_artifacts("t2") == []  # 幂等写入不产生第二条索引


def test_node_lifecycle(tmp_path: Path) -> None:
    with DagStore(tmp_path) as store:
        store.ensure_run("t1", "hash", 2)
        store.mark_running("t1", "n1", "test.emit@1.0")
        assert store.node_rows("t1")[0]["state"] == "running"
        store.mark_succeeded("t1", "n1", {"out": "sha256:abc"})
        assert store.completed_nodes("t1") == {"n1"}
        assert store.node_outputs("t1", "n1") == {"out": "sha256:abc"}
        store.mark_failed("t1", "n2", "bad")
        assert store.completed_nodes("t1") == {"n1"}
        rows = {row["node_id"]: row for row in store.node_rows("t1")}
        assert rows["n2"]["state"] == "failed"


def test_load_missing_artifact_raises(tmp_path: Path) -> None:
    with DagStore(tmp_path) as store, pytest.raises(KeyError):
        store.load_artifact("sha256:deadbeef")


# ---------------------------------------------------------------------------
# 执行器：线性 / 检查点 / 失败
# ---------------------------------------------------------------------------


def test_run_dag_executes_linear_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_step(monkeypatch)
    dag = _dag(
        [
            {"id": "a", "op": "test.emit@1.0", "params": {"value": 3}},
            {"id": "b", "op": "test.double@1.0", "params": {}, "inputs": {"in": "a.out"}},
        ]
    )
    result = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert result["status"] == "SUCCEEDED"
    assert [row["node_id"] for row in result["nodes"]] == ["a", "b"]
    with DagStore(tmp_path) as store:
        out_id = store.node_outputs("t1", "b")["out"]
        assert store.load_artifact(out_id)["value"] == {"value": 6}


def test_run_dag_checkpoint_pauses_then_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = dag_engine.execute_node

    def _counting(payload):  # type: ignore[no-untyped-def]
        calls.append(payload["node_id"])
        return real(payload)

    monkeypatch.setattr(dag_engine, "_step_dag_operator", _counting)
    dag = _dag(
        [
            {"id": "a", "op": "test.emit@1.0", "params": {"value": 1}},
            {"id": "b", "op": "test.double@1.0", "params": {}, "inputs": {"in": "a.out"}},
        ],
        checkpoints=["a"],
    )
    first = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert first["status"] == "PAUSED"
    assert first["message"] == "checkpoint:a"
    assert calls == ["a"]

    second = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert second["status"] == "SUCCEEDED"
    assert calls == ["a", "b"]  # 已完成节点不重复执行


def test_run_dag_failure_stops_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_step(monkeypatch)
    dag = _dag(
        [
            {"id": "a", "op": "test.emit@1.0", "params": {"value": 1}},
            {"id": "b", "op": "test.boom@1.0", "params": {"message": "kaboom"}, "inputs": {"in": "a.out"}},
            {"id": "c", "op": "test.double@1.0", "params": {}, "inputs": {"in": "a.out"}},
        ]
    )
    result = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert result["status"] == "FAILED"
    assert "kaboom" in result["message"]
    with DagStore(tmp_path) as store:
        states = {row["node_id"]: row["state"] for row in store.node_rows("t1")}
        assert states == {"a": "succeeded", "b": "failed"}


def test_run_dag_rejects_invalid_dag(tmp_path: Path) -> None:
    dag = _dag([{"id": "a", "op": "cohort.from_run@1.0", "params": {}}])
    result = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert result["status"] == "FAILED"
    assert "invalid dag" in result["message"]


def test_execute_node_rejects_unknown_operator(tmp_path: Path) -> None:
    result = dag_engine.execute_node(
        {
            "home": str(tmp_path),
            "task_id": "t1",
            "node_id": "n1",
            "op": "ghost.op@1.0",
            "params": {},
            "inputs": {},
        }
    )
    assert result["status"] == "failed"
    assert "no such operator" in result["error"]


def test_execute_node_enforces_data_class(tmp_path: Path) -> None:
    result = dag_engine.execute_node(
        {
            "home": str(tmp_path),
            "task_id": "t1",
            "node_id": "n1",
            "op": "test.emit@1.0",
            "params": {},
            "inputs": {},
            "data_class": 0,
        }
    )
    assert result["status"] == "failed"
    assert "data class" in result["error"]


# ---------------------------------------------------------------------------
# 内置算子端到端（最小 run/GOM/药敏夹具）
# ---------------------------------------------------------------------------


def _workflow_dir(home: Path) -> Path:
    wf = home / "workflows" / "bacmap" / "config"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "config.yaml").write_text("threads: 1\n")
    return home / "workflows" / "bacmap"


def _fixture_run(home: Path, strains: list[str]) -> str:
    from bacmap.store import runs as runs_store

    run = runs_store.create_run(
        "bacmap",
        _workflow_dir(home),
        strains,
        db_path=home / "runs.sqlite",
        task_id="fixture-task",
    )
    with sqlite3.connect(home / "gom.sqlite") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS strain_amr_genes (strain_id TEXT, gene_name TEXT)")
        for sid in ("S1", "S2", "S3"):
            conn.execute(
                "INSERT INTO strain_amr_genes (strain_id, gene_name) VALUES (?,?)",
                (sid, "blaCTX-M-15"),
            )
    (home / "data").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(home / "data" / "bacmap.sqlite") as conn:
        conn.execute(
            "CREATE TABLE lab_results (strain_id TEXT, test_name TEXT, interpretation TEXT,"
            " result TEXT, created_at TEXT)"
        )
        rows = [("S1", "R"), ("S2", "R"), ("S3", "R"), ("S4", "S"), ("S5", "S")]
        for sid, interp in rows:
            conn.execute(
                "INSERT INTO lab_results VALUES (?,?,?,?,?)",
                (sid, "meropenem", interp, "", "2026-01-01T00:00:00+00:00"),
            )
    return run.run_id


def test_builtin_chain_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_step(monkeypatch)
    run_id = _fixture_run(tmp_path, ["S1", "S2", "S3", "S4", "S5"])
    dag = _dag(
        [
            {"id": "cohort", "op": "cohort.from_run@1.0", "params": {"run_id": run_id}},
            {
                "id": "assoc",
                "op": "stats.assoc@1.0",
                "params": {"gene": "blaCTX-M-15", "test_name": "meropenem"},
                "inputs": {"cohort": "cohort.cohort"},
            },
            {
                "id": "forest",
                "op": "figure.forest@1.0",
                "params": {},
                "inputs": {"table": "assoc.table"},
            },
            {
                "id": "report",
                "op": "text.report@1.0",
                "params": {},
                "inputs": {"table": "assoc.table", "figure": "forest.figure"},
            },
        ]
    )
    result = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert result["status"] == "SUCCEEDED", result
    with DagStore(tmp_path) as store:
        text_id = store.node_outputs("t1", "report")["text"]
        text = store.load_artifact(text_id)["value"]
        figure_id = store.node_outputs("t1", "forest")["figure"]
        figure = store.load_artifact(figure_id)["value"]
    assert text["format"] == "markdown"
    assert "blaCTX-M-15" in text["markdown"]
    assert "比值比" in text["markdown"]
    assert text["slots"]["n"] == 5
    assert text["slots"]["gene_pos"] == 3
    assert text["slots"]["resistant"] == 3
    assert "阳性 3 株" in text["markdown"]
    assert text["claims"][1]["evidence"]
    assert figure["format"] == "svg"
    assert "<svg" in figure["data"]
    assert text["audit"]["ok"] is True


def test_export_writes_report_figure_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import json

    from bacmap.interfaces.cli import research_dag as cli

    _patch_step(monkeypatch)
    run_id = _fixture_run(tmp_path, ["S1", "S2", "S3", "S4", "S5"])
    dag = _dag(
        [
            {"id": "cohort", "op": "cohort.from_run@1.0", "params": {"run_id": run_id}},
            {
                "id": "assoc",
                "op": "stats.assoc@1.0",
                "params": {"gene": "blaCTX-M-15", "test_name": "meropenem"},
                "inputs": {"cohort": "cohort.cohort"},
            },
            {
                "id": "forest",
                "op": "figure.forest@1.0",
                "params": {},
                "inputs": {"table": "assoc.table"},
            },
            {
                "id": "report",
                "op": "text.report@1.0",
                "params": {},
                "inputs": {"table": "assoc.table", "figure": "forest.figure"},
            },
        ]
    )
    assert dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})[
        "status"
    ] == "SUCCEEDED"

    out = tmp_path / "export"
    cli.run_export(
        argparse.Namespace(home=str(tmp_path), task_id="t1", out=str(out), json=True)
    )
    assert (out / "report.md").is_file()
    assert (out / "figure.svg").is_file()
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["task_id"] == "t1"
    assert provenance["audit"]["ok"] is True
    assert len(provenance["artifacts"]) == 4
    assert "blaCTX-M-15" in (out / "report.md").read_text(encoding="utf-8")


def test_builtin_chain_missing_run_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_step(monkeypatch)
    dag = _dag(
        [
            {"id": "cohort", "op": "cohort.from_run@1.0", "params": {"run_id": "nope"}},
        ]
    )
    result = dag_engine.run_dag({"home": str(tmp_path), "task_id": "t1", "dag": dag})
    assert result["status"] == "FAILED"
    assert "no such run" in result["message"]


def test_linear_order_is_stable_for_independent_nodes() -> None:
    dag = ResearchDag.model_validate(
        _dag(
            [
                {"id": "b", "op": "test.emit@1.0", "params": {}},
                {"id": "a", "op": "test.emit@1.0", "params": {}},
            ]
        )
    )
    assert [n.id for n in dag.linear_order()] == ["b", "a"]


def test_dagstore_module_has_no_tasks_import() -> None:
    """research 层不得依赖 tasks（ADR-02 契约的模块级兜底断言）。"""
    source = Path(dagstore.__file__).read_text(encoding="utf-8")
    assert "bacmap.tasks" not in source
