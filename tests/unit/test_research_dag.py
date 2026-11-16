"""研究编排层 P1：算子注册表与 DAG 校验。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from bacmap.research.dag import DagValidationError, ResearchDag, dag_problems
from bacmap.research.operators import catalog, get_operator, unregister
from bacmap.research.operators.spec import OperatorError, PortType, operator

DAG = {
    "schema": "bacmap.research.dag/1",
    "nodes": [
        {"id": "cohort", "op": "cohort.from_run@1.0", "params": {"run_id": "run-1"}},
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
    ],
    "checkpoints": ["assoc"],
}


def _dag(**overrides: object) -> ResearchDag:
    raw = {**DAG, **overrides}
    return ResearchDag.model_validate(raw)


def test_catalog_contains_builtin_operators() -> None:
    refs = {entry["ref"] for entry in catalog()}
    assert {
        "cohort.from_run@1.0",
        "stats.assoc@1.0",
        "figure.forest@1.0",
        "text.report@1.0",
    } <= refs


def test_get_operator_by_ref_and_by_name() -> None:
    assert get_operator("stats.assoc@1.0").spec.version == "1.0"
    assert get_operator("stats.assoc").spec.name == "stats.assoc"
    with pytest.raises(OperatorError):
        get_operator("nope.nothing@9.9")


def test_valid_dag_order_and_hash_are_deterministic() -> None:
    dag = _dag()
    dag.validate_dag()
    assert [node.id for node in dag.linear_order()] == ["cohort", "assoc", "forest", "report"]
    assert dag.plan_hash() == _dag().plan_hash()
    assert len(dag.plan_hash()) == 64


def test_duplicate_node_id_is_rejected() -> None:
    dag = _dag(nodes=[DAG["nodes"][0], DAG["nodes"][0]])  # type: ignore[index]
    assert any("duplicate node id" in p for p in dag_problems(dag))


def test_unknown_operator_is_rejected() -> None:
    dag = _dag(nodes=[{"id": "x", "op": "nope.nothing@1.0", "params": {}}])
    assert any("no such operator" in p for p in dag_problems(dag))


def test_unknown_input_port_is_rejected() -> None:
    dag = _dag(
        nodes=[
            {"id": "a", "op": "cohort.from_run@1.0", "params": {"run_id": "r"}},
            {
                "id": "b",
                "op": "stats.assoc@1.0",
                "params": {"gene": "g", "test_name": "t"},
                "inputs": {"wrong": "a.cohort"},
            },
        ],
        checkpoints=[],
    )
    problems = dag_problems(dag)
    assert any("unknown input port 'wrong'" in p for p in problems)
    assert any("missing input for port 'cohort'" in p for p in problems)


def test_missing_input_is_rejected() -> None:
    dag = _dag(
        nodes=[
            {"id": "a", "op": "cohort.from_run@1.0", "params": {"run_id": "r"}},
            {
                "id": "b",
                "op": "stats.assoc@1.0",
                "params": {"gene": "g", "test_name": "t"},
            },
        ],
        checkpoints=[],
    )
    assert any("missing input for port 'cohort'" in p for p in dag_problems(dag))


def test_port_type_mismatch_is_rejected() -> None:
    dag = _dag(
        nodes=[
            {"id": "a", "op": "cohort.from_run@1.0", "params": {"run_id": "r"}},
            {
                "id": "b",
                "op": "figure.forest@1.0",
                "params": {},
                "inputs": {"table": "a.cohort"},
            },
        ],
        checkpoints=[],
    )
    problems = dag_problems(dag)
    assert any("type mismatch" in p and "cohort" in p.lower() for p in problems)


def test_cycle_is_rejected() -> None:
    dag = _dag(
        nodes=[
            {
                "id": "a",
                "op": "stats.assoc@1.0",
                "params": {"gene": "g", "test_name": "t"},
                "inputs": {"cohort": "b.cohort"},
            },
            {
                "id": "b",
                "op": "stats.assoc@1.0",
                "params": {"gene": "g", "test_name": "t"},
                "inputs": {"cohort": "a.cohort"},
            },
        ],
        checkpoints=[],
    )
    assert any("cycle" in p for p in dag_problems(dag))


def test_unknown_checkpoint_is_rejected() -> None:
    dag = _dag(checkpoints=["ghost"])
    assert any("checkpoint references unknown node" in p for p in dag_problems(dag))


def test_checkpoint_requires_outputs() -> None:
    class _Empty(BaseModel):
        pass

    @operator(
        name="test.sink",
        version="1.0",
        doc="no outputs",
        inputs={},
        outputs={},
        params=_Empty,
    )
    def _sink(ctx):  # type: ignore[no-untyped-def]
        return {}

    try:
        dag = _dag(nodes=[{"id": "s", "op": "test.sink@1.0", "params": {}}], checkpoints=["s"])
        assert any("produces no artifact" in p for p in dag_problems(dag))
    finally:
        unregister("test.sink@1.0")


def test_parallel_mode_is_accepted_since_p6() -> None:
    dag = _dag(execution={"mode": "parallel"})
    assert dag_problems(dag) == []


def test_data_class_conflict_is_rejected() -> None:
    dag = _dag(data_class=1)
    assert any("operator needs D2" in p for p in dag_problems(dag))


def test_params_are_validated() -> None:
    dag = _dag(nodes=[{"id": "a", "op": "cohort.from_run@1.0", "params": {}}])
    assert any("run_id" in p for p in dag_problems(dag))


def test_validate_dag_raises_with_problems() -> None:
    dag = _dag(checkpoints=["ghost"])
    with pytest.raises(DagValidationError) as excinfo:
        dag.validate_dag()
    assert "checkpoint references unknown node" in str(excinfo.value)


def test_research_params_rejects_invalid_dag() -> None:
    from bacmap.tasks.params import ResearchParams

    with pytest.raises(ValueError, match="invalid dag"):
        ResearchParams(analysis="dag", dag={"schema": "bacmap.research.dag/1", "nodes": []})
    with pytest.raises(ValueError, match="requires a dag spec"):
        ResearchParams(analysis="dag")


def test_research_params_accepts_valid_dag() -> None:
    from bacmap.tasks.params import ResearchParams

    params = ResearchParams(analysis="dag", dag=DAG)
    assert params.analysis == "dag"
    assert params.dag is not None
    assert len(params.dag["nodes"]) == 4


def test_catalog_entry_has_ports_and_schema() -> None:
    entry = next(e for e in catalog() if e["ref"] == "stats.assoc@1.0")
    assert entry["inputs"] == {"cohort": PortType.COHORT.value}
    assert entry["outputs"] == {"table": PortType.TABLE.value}
    assert entry["params"]["title"]
    assert entry["data_class"] == 2
