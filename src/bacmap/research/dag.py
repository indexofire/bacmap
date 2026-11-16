"""研究计划 DAG：模型、校验与确定性哈希（P1）。

设计见 ``dev/PLAN-research-orchestration.md`` §4：

- ``inputs`` 即边：``"<node>.<port>"``，不额外维护边表；
- 校验在计划确认前完成（类型/无环/检查点/数据级别），不在运行期才发现；
- P1 只支持线性执行（``mode=linear``），并行留给 P2；
- 不允许嵌套 DAG（节点参数里不能再出现 DAG）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bacmap.research.operators.spec import OperatorError, OperatorSpec, PortType, get_operator

DAG_SCHEMA: Literal["bacmap.research.dag/1"] = "bacmap.research.dag/1"
NODE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class DagNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=NODE_ID_PATTERN)
    op: str = Field(min_length=3, max_length=120)
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)


class DagExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["linear", "parallel"] = "linear"
    on_failure: Literal["fail_fast", "continue"] = "fail_fast"


class ResearchDag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["bacmap.research.dag/1"] = Field(default=DAG_SCHEMA, alias="schema")
    study_id: str = ""
    nodes: list[DagNode] = Field(min_length=1, max_length=32)
    checkpoints: list[str] = Field(default_factory=list)
    execution: DagExecution = Field(default_factory=DagExecution)
    data_class: int = Field(default=2, ge=0, le=4)

    # ---- 校验 ----------------------------------------------------------

    def validate_dag(self) -> None:
        problems = dag_problems(self)
        if problems:
            raise DagValidationError(problems)

    def operator_of(self, node: DagNode) -> OperatorSpec:
        return get_operator(node.op).spec

    def producers(self) -> dict[str, OperatorSpec]:
        return {node.id: self.operator_of(node) for node in self.nodes}

    def linear_order(self) -> list[DagNode]:
        return linear_order(self)

    def plan_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class DagValidationError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def dag_problems(dag: ResearchDag) -> list[str]:
    """收集全部问题（不 fail-fast，便于计划器一次修复）。"""
    problems: list[str] = []
    problems.extend(_check_node_ids(dag))
    specs = _resolve_specs(dag, problems)
    problems.extend(_check_ports_and_types(dag, specs))
    problems.extend(_check_acyclic(dag))
    problems.extend(_check_checkpoints(dag, specs))
    problems.extend(_check_data_class(dag, specs))
    problems.extend(_check_execution(dag))
    return problems


def _check_node_ids(dag: ResearchDag) -> list[str]:
    seen: set[str] = set()
    problems: list[str] = []
    for node in dag.nodes:
        if node.id in seen:
            problems.append(f"duplicate node id: {node.id}")
        seen.add(node.id)
    return problems


def _resolve_specs(dag: ResearchDag, problems: list[str]) -> dict[str, OperatorSpec]:
    specs: dict[str, OperatorSpec] = {}
    for node in dag.nodes:
        try:
            op = get_operator(node.op)
        except OperatorError as exc:
            problems.append(f"node {node.id}: {exc.message}")
            continue
        specs[node.id] = op.spec
        try:
            op.spec.params_model.model_validate(node.params)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(x) for x in first.get("loc", ()))
            problems.append(f"node {node.id}: params.{loc}: {first.get('msg', 'invalid')}")
    return specs


def _check_ports_and_types(
    dag: ResearchDag, specs: dict[str, OperatorSpec]
) -> list[str]:
    problems: list[str] = []
    for node in dag.nodes:
        spec = specs.get(node.id)
        if spec is None:
            continue
        for port in node.inputs:
            if port not in spec.inputs:
                problems.append(f"node {node.id}: unknown input port {port!r}")
        for port in spec.inputs:
            if port not in node.inputs and port not in spec.optional_inputs:
                problems.append(f"node {node.id}: missing input for port {port!r}")
        for port, ref in node.inputs.items():
            src_id, _, src_port = ref.partition(".")
            if not src_id or not src_port:
                problems.append(
                    f"node {node.id}.{port}: bad input ref {ref!r} (expected '<node>.<port>')"
                )
                continue
            src_spec = specs.get(src_id)
            if src_spec is None:
                problems.append(f"node {node.id}.{port}: unknown source node {src_id!r}")
                continue
            if src_port not in src_spec.outputs:
                problems.append(
                    f"node {node.id}.{port}: node {src_id!r} has no output port {src_port!r}"
                )
                continue
            expected = spec.inputs.get(port)
            actual = src_spec.outputs[src_port]
            if expected is not None and expected is not actual:
                problems.append(
                    f"node {node.id}.{port}: type mismatch, expects {expected.value},"
                    f" got {actual.value} from {ref!r}"
                )
    return problems


def _check_acyclic(dag: ResearchDag) -> list[str]:
    try:
        linear_order(dag)
    except DagValidationError:
        return ["graph contains a cycle"]
    return []


def _check_checkpoints(dag: ResearchDag, specs: dict[str, OperatorSpec]) -> list[str]:
    problems: list[str] = []
    ids = {node.id for node in dag.nodes}
    for node_id in dag.checkpoints:
        if node_id not in ids:
            problems.append(f"checkpoint references unknown node {node_id!r}")
            continue
        spec = specs.get(node_id)
        if spec is not None and not spec.outputs:
            problems.append(f"checkpoint node {node_id!r} produces no artifact to inspect")
    if len(set(dag.checkpoints)) != len(dag.checkpoints):
        problems.append("duplicate checkpoint")
    return problems


def _check_data_class(dag: ResearchDag, specs: dict[str, OperatorSpec]) -> list[str]:
    problems: list[str] = []
    for node in dag.nodes:
        spec = specs.get(node.id)
        if spec is None:
            continue
        if spec.data_class > dag.data_class:
            problems.append(
                f"node {node.id}: operator needs D{spec.data_class},"
                f" plan declares D{dag.data_class}"
            )
    return problems


def _check_execution(dag: ResearchDag) -> list[str]:
    return []


def linear_order(dag: ResearchDag) -> list[DagNode]:
    """稳定拓扑序：同层按计划中的书写顺序（确定性执行与哈希）。"""
    order_index = {node.id: idx for idx, node in enumerate(dag.nodes)}
    deps: dict[str, set[str]] = {node.id: set() for node in dag.nodes}
    for node in dag.nodes:
        for ref in node.inputs.values():
            src, _, _port = ref.partition(".")
            if src in deps:
                deps[node.id].add(src)
    ready = sorted((nid for nid, d in deps.items() if not d), key=order_index.__getitem__)
    emitted: list[str] = []
    while ready:
        nid = ready.pop(0)
        emitted.append(nid)
        for other, needs in deps.items():
            if nid in needs:
                needs.discard(nid)
                if not needs and other not in emitted and other not in ready:
                    ready.append(other)
        ready.sort(key=order_index.__getitem__)
    if len(emitted) != len(dag.nodes):
        raise DagValidationError(["graph contains a cycle"])
    by_id = {node.id: node for node in dag.nodes}
    return [by_id[nid] for nid in emitted]


def parallel_waves(dag: ResearchDag) -> list[list[DagNode]]:
    """按依赖分层：同层节点互不依赖，可并行执行（稳定顺序）。"""
    order_index = {node.id: idx for idx, node in enumerate(dag.nodes)}
    deps: dict[str, set[str]] = {node.id: set() for node in dag.nodes}
    for node in dag.nodes:
        for ref in node.inputs.values():
            src, _, _port = ref.partition(".")
            if src in deps:
                deps[node.id].add(src)
    remaining = set(deps)
    done: set[str] = set()
    waves: list[list[DagNode]] = []
    by_id = {node.id: node for node in dag.nodes}
    while remaining:
        ready = sorted(
            (nid for nid in remaining if deps[nid] <= done), key=order_index.__getitem__
        )
        if not ready:
            raise DagValidationError(["graph contains a cycle"])
        waves.append([by_id[nid] for nid in ready])
        done |= set(ready)
        remaining -= set(ready)
    return waves


def port_type_of(dag: ResearchDag, node_id: str, port: str) -> PortType:
    spec = get_operator(next(n.op for n in dag.nodes if n.id == node_id)).spec
    return spec.outputs[port]
