"""P3 研究计划器：目录约束、结构化输出、校验修复循环与澄清问题。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bacmap.agent.llm.gateway import LlmUnavailableError
from bacmap.agent.planner import (
    PlannerConstraints,
    PlannerOutput,
    build_prompt,
    propose_dag,
    recent_run_summaries,
)

VALID_DAG = {
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


class FakeGateway:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def structured(self, **kwargs: Any) -> PlannerOutput:
        self.calls.append(kwargs)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _ok(dag: dict | None = VALID_DAG, questions: list[str] | None = None) -> PlannerOutput:
    return PlannerOutput(dag=dag, questions=questions or [], rationale="test")


def test_valid_dag_is_accepted() -> None:
    gateway = FakeGateway([_ok()])
    proposal = propose_dag("沙门菌 blaCTX-M-15 与美罗培南关联", gateway)  # type: ignore[arg-type]
    assert proposal.ok
    assert proposal.attempts == 1
    assert proposal.dag is not None
    assert [n["id"] for n in proposal.dag["nodes"]] == ["cohort", "assoc", "forest", "report"]
    prompt = gateway.calls[0]["prompt"]
    assert "stats.assoc@1.0" in prompt
    assert "沙门菌" in prompt


def test_questions_only_returns_clarification() -> None:
    gateway = FakeGateway([_ok(dag=None, questions=["哪个 run？", "耐药折点如何定义？"])])
    proposal = propose_dag("看看最近的耐药情况", gateway)  # type: ignore[arg-type]
    assert proposal.dag is None
    assert proposal.questions == ["哪个 run？", "耐药折点如何定义？"]
    assert proposal.attempts == 1


def test_validation_failure_triggers_repair() -> None:
    bad = {
        "schema": "bacmap.research.dag/1",
        "nodes": [
            {"id": "cohort", "op": "cohort.from_run@1.0", "params": {"run_id": "r"}},
            {
                "id": "forest",
                "op": "figure.forest@1.0",
                "params": {},
                "inputs": {"table": "cohort.cohort"},
            },
        ],
    }
    gateway = FakeGateway([_ok(dag=bad), _ok()])
    proposal = propose_dag("问题", gateway)  # type: ignore[arg-type]
    assert proposal.ok
    assert proposal.attempts == 2
    assert "type mismatch" in gateway.calls[1]["prompt"]


def test_exhausted_repair_returns_problems() -> None:
    bad = {
        "schema": "bacmap.research.dag/1",
        "nodes": [{"id": "x", "op": "ghost.op@1.0", "params": {}}],
    }
    gateway = FakeGateway([_ok(dag=bad), _ok(dag=bad), _ok(dag=bad)])
    proposal = propose_dag("问题", gateway, max_attempts=3)  # type: ignore[arg-type]
    assert proposal.dag is None
    assert proposal.attempts == 3
    assert any("no such operator" in p for p in proposal.problems)


def test_data_class_is_passed_to_gateway() -> None:
    gateway = FakeGateway([_ok()])
    propose_dag(
        "问题",
        gateway,  # type: ignore[arg-type]
        constraints=PlannerConstraints(max_data_class=2),
    )
    assert gateway.calls[0]["data_class"].name == "D2"
    assert gateway.calls[0]["purpose"] == "planner"


def test_checkpoint_constraint_is_in_prompt() -> None:
    prompt = build_prompt(
        "问题",
        constraints=PlannerConstraints(allow_checkpoints=False),
        runs=None,
    )
    assert "不要设置 checkpoints" in prompt


def test_prompt_lists_runs_and_forbids_guessing() -> None:
    prompt = build_prompt(
        "问题",
        constraints=PlannerConstraints(),
        runs=[{"run_id": "run-1", "strain_ids": ["S1", "S2"], "started_at": "2026-01-01"}],
    )
    assert "run_id=run-1" in prompt
    assert "不要猜测" in prompt
    assert "checkpoints" in prompt


def test_unavailable_gateway_propagates() -> None:
    gateway = FakeGateway([LlmUnavailableError("no endpoint")])
    with pytest.raises(LlmUnavailableError):
        propose_dag("问题", gateway)  # type: ignore[arg-type]


def test_recent_run_summaries(tmp_path: Path) -> None:
    from bacmap.store import runs as runs_store

    wf = tmp_path / "workflows" / "bacmap" / "config"
    wf.mkdir(parents=True)
    (wf / "config.yaml").write_text("threads: 1\n")
    runs_store.create_run(
        "bacmap",
        tmp_path / "workflows" / "bacmap",
        ["S1", "S2"],
        db_path=tmp_path / "runs.sqlite",
        task_id="t1",
    )
    summaries = recent_run_summaries(tmp_path)
    assert summaries and summaries[0]["strain_ids"] == ["S1", "S2"]
    # 没有 runs.sqlite 的 home 返回空列表（计划器提示向用户询问）
    empty = tmp_path / "empty"
    empty.mkdir()
    assert recent_run_summaries(empty) == []


def test_planner_output_rejects_non_dict_dag() -> None:
    with pytest.raises(Exception):
        PlannerOutput(dag="not-a-dict")  # type: ignore[arg-type]
