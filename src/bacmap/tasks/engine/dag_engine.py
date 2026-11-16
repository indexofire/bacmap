"""研究 DAG 执行器（P1：线性 + 检查点 + 内容寻址产物）。

职责边界：
- 本模块只做**节点级编排**（取算子、校验参数、解析输入产物、落产物、记状态）；
- 具体计算在 ``bacmap.research.operators``（research 层不得导入 tasks，反向可以）；
- 工作流本体仍是 ``dbos_engine.research_workflow``（同一 task 身份），
  本模块的 ``run_dag`` 由它调用，避免出现"工作流里再开工作流"。

检查点语义：节点执行完且属于 ``dag.checkpoints`` 时返回 ``PAUSED``；恢复走
既有 ``DbosTaskEngine.resume``（删除旧工作流行、同 task_id 重建），本模块通过
``dag_nodes`` 的已完成集合跳过已完成节点。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from dbos import DBOS

from bacmap.research.dag import DagValidationError, ResearchDag, parallel_waves
from bacmap.research.dagstore import DagStore
from bacmap.research.operators import OperatorContext, OperatorError, get_operator
from bacmap.tasks.engine.dag_runner import run_sandbox

logger = logging.getLogger(__name__)


def _now_state(home: Path, task_id: str) -> str:
    db = Path(home) / "tasks.sqlite"
    if not task_id or not db.is_file():
        return ""
    try:
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT state FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    except sqlite3.Error:  # pragma: no cover - 读取失败按运行中处理
        return ""
    return str(row[0]) if row else ""


def _stopped(home: Path, task_id: str) -> bool:
    return _now_state(home, task_id) in {"paused", "cancelled", "failed"}


def _has_code_approval(home: Path, task_id: str) -> bool:
    """任务是否已有一次 ``decision=approve``（代码签字）。"""
    db = Path(home) / "tasks.sqlite"
    if not task_id or not db.is_file():
        return False
    try:
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
            row = conn.execute(
                "SELECT 1 FROM approvals WHERE task_id = ? AND decision = 'approve' LIMIT 1",
                (task_id,),
            ).fetchone()
    except sqlite3.Error:  # pragma: no cover - 读取失败按未签字处理
        return False
    return bool(row)


def _first_code_node(dag: ResearchDag) -> str | None:
    for node in dag.linear_order():
        try:
            if get_operator(node.op).spec.approval == "code":
                return node.id
        except OperatorError:  # pragma: no cover - 校验阶段已拦截未知算子
            continue
    return None


def execute_node(payload: dict[str, Any]) -> dict[str, Any]:
    """执行单个 DAG 节点（可单独测试；不依赖 DBOS）。"""
    home = Path(str(payload["home"]))
    task_id = str(payload["task_id"])
    node_id = str(payload["node_id"])
    op_ref = str(payload["op"])
    params = dict(payload.get("params") or {})
    input_artifacts = {str(k): str(v) for k, v in (payload.get("inputs") or {}).items()}
    data_class = int(payload.get("data_class", 2))

    store = DagStore(home)
    try:
        store.mark_running(task_id, node_id, op_ref)
        try:
            op = get_operator(op_ref)
        except OperatorError as exc:
            store.mark_failed(task_id, node_id, exc.message)
            return {"status": "failed", "error": exc.message}

        spec = op.spec
        if spec.data_class > data_class:
            message = (
                f"data class violation: operator needs D{spec.data_class},"
                f" plan allows D{data_class}"
            )
            store.mark_failed(task_id, node_id, message)
            return {"status": "failed", "error": message}

        try:
            validated = spec.params_model.model_validate(params)
        except Exception as exc:  # pydantic ValidationError
            message = f"invalid params: {exc}"
            store.mark_failed(task_id, node_id, message)
            return {"status": "failed", "error": message}

        inputs: dict[str, Any] = {}
        try:
            for port, artifact_id in input_artifacts.items():
                inputs[port] = store.load_artifact(artifact_id)["value"]
        except (KeyError, OSError, ValueError) as exc:
            message = f"missing input artifact: {exc}"
            store.mark_failed(task_id, node_id, message)
            return {"status": "failed", "error": message}

        workdir = home / "workspaces" / task_id / node_id
        workdir.mkdir(parents=True, exist_ok=True)

        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "op": op_ref,
                    "params": validated.model_dump(mode="json"),
                    "inputs": input_artifacts,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if op.spec.determinism == "deterministic" and not payload.get("no_cache"):
            cached = store.cache_get(cache_key)
            if cached:
                store.mark_succeeded(task_id, node_id, cached, cache_hit=True)
                return {"status": "succeeded", "outputs": cached, "cache_hit": True}
        ctx = OperatorContext(
            home=home,
            task_id=task_id,
            node_id=node_id,
            params=validated.model_dump(),
            inputs=inputs,
            input_artifacts=input_artifacts,
            workdir=workdir,
            runner=run_sandbox,
        )
        try:
            produced = op.fn(ctx)
        except OperatorError as exc:
            store.mark_failed(task_id, node_id, f"[{exc.code}] {exc.message}")
            return {"status": "failed", "error": exc.message}
        except Exception as exc:  # 节点失败要落库，不能拖垮工作流
            logger.exception("dag node %s/%s failed", task_id, node_id)
            store.mark_failed(task_id, node_id, f"{type(exc).__name__}: {exc}")
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

        missing = [port for port in spec.outputs if port not in produced]
        extra = [port for port in produced if port not in spec.outputs]
        if missing or extra:
            message = f"operator output mismatch: missing={missing} extra={extra}"
            store.mark_failed(task_id, node_id, message)
            return {"status": "failed", "error": message}

        outputs = {
            port: store.put_artifact(
                type_=spec.outputs[port].value,
                value=produced[port],
                task_id=task_id,
                node_id=node_id,
                data_class=data_class,
            )
            for port in spec.outputs
        }
        store.mark_succeeded(task_id, node_id, outputs)
        if op.spec.determinism == "deterministic":
            store.cache_put(cache_key, op_ref, outputs)
        return {"status": "succeeded", "outputs": outputs, "cache_hit": False}
    finally:
        store.close()


@DBOS.step()
def _step_dag_operator(payload: dict[str, Any]) -> dict[str, Any]:
    return execute_node(payload)


def _resolve_inputs(store: DagStore, task_id: str, node: Any) -> dict[str, str] | None:
    resolved: dict[str, str] = {}
    for port, ref in node.inputs.items():
        src, _, src_port = str(ref).partition(".")
        artifact_id = store.node_outputs(task_id, src).get(src_port)
        if not artifact_id:
            return None
        resolved[str(port)] = artifact_id
    return resolved


def _run_parallel(
    home: Path, task_id: str, dag: ResearchDag, store: DagStore, completed: set[str]
) -> dict[str, Any]:
    """分层并行执行：同一 wave 内互不依赖（P6）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from bacmap.tasks.engine._progress import record_step

    for wave in parallel_waves(dag):
        pending = [node for node in wave if node.id not in completed]
        if not pending:
            continue
        if _stopped(home, task_id):
            store.set_run_state(task_id, "paused")
            return {
                "status": "PAUSED",
                "message": "task paused",
                "nodes": store.node_rows(task_id),
            }
        payloads = []
        for node in pending:
            record_step(home, task_id, f"dag:{node.id}")
            inputs = _resolve_inputs(store, task_id, node)
            if inputs is None:
                store.set_run_state(task_id, "failed")
                return {
                    "status": "FAILED",
                    "message": f"node {node.id}: upstream artifacts missing",
                }
            payloads.append(
                {
                    "home": str(home),
                    "task_id": task_id,
                    "node_id": node.id,
                    "op": node.op,
                    "params": node.params,
                    "inputs": inputs,
                    "data_class": dag.data_class,
                }
            )
        with ThreadPoolExecutor(max_workers=min(4, len(payloads))) as pool:
            futures = {pool.submit(execute_node, payload): payload for payload in payloads}
            for future in as_completed(futures):
                payload = futures[future]
                result = future.result()
                if result.get("status") != "succeeded":
                    store.set_run_state(task_id, "failed")
                    return {
                        "status": "FAILED",
                        "message": (
                            f"node {payload['node_id']} failed: {result.get('error', '')}"
                        ),
                        "nodes": store.node_rows(task_id),
                    }
        if any(node.id in dag.checkpoints for node in pending):
            store.set_run_state(task_id, "paused")
            return {
                "status": "PAUSED",
                "message": f"checkpoint:{next(n.id for n in pending if n.id in dag.checkpoints)}",
                "nodes": store.node_rows(task_id),
                "artifacts": store.list_artifacts(task_id),
            }
    store.set_run_state(task_id, "succeeded")
    return {
        "status": "SUCCEEDED",
        "nodes": store.node_rows(task_id),
        "artifacts": store.list_artifacts(task_id),
    }


def run_dag(params: dict[str, Any]) -> dict[str, Any]:
    """在工作流内线性执行 DAG；返回 ``SUCCEEDED`` / ``PAUSED`` / ``FAILED`` 信封。"""
    home = Path(str(params["home"]))
    task_id = str(params["task_id"])
    try:
        dag = ResearchDag.model_validate(params["dag"])
        dag.validate_dag()
    except (DagValidationError, ValueError) as exc:
        return {"status": "FAILED", "message": f"invalid dag: {exc}"}

    store = DagStore(home)
    try:
        store.ensure_run(task_id, dag.plan_hash(), dag.data_class)
        completed = store.completed_nodes(task_id)
        from bacmap.research.config import load_research_config

        if (
            load_research_config(home).approval.code_review == "always"
            and not _has_code_approval(home, task_id)
        ):
            code_node = _first_code_node(dag)
            if code_node:
                store.set_run_state(task_id, "awaiting_approval")
                return {
                    "status": "AWAITING_APPROVAL",
                    "message": f"code_approval:{code_node}",
                    "nodes": store.node_rows(task_id),
                }
        from bacmap.tasks.engine._progress import record_step

        if dag.execution.mode == "parallel":
            return _run_parallel(home, task_id, dag, store, completed)

        for node in dag.linear_order():
            if node.id in completed:
                continue
            if _stopped(home, task_id):
                store.set_run_state(task_id, "paused")
                return {
                    "status": "PAUSED",
                    "message": "task paused",
                    "nodes": store.node_rows(task_id),
                }
            record_step(home, task_id, f"dag:{node.id}")
            inputs = _resolve_inputs(store, task_id, node)
            if inputs is None:
                message = f"node {node.id}: upstream artifacts missing"
                store.set_run_state(task_id, "failed")
                return {"status": "FAILED", "message": message}
            result = _step_dag_operator(
                {
                    "home": str(home),
                    "task_id": task_id,
                    "node_id": node.id,
                    "op": node.op,
                    "params": node.params,
                    "inputs": inputs,
                    "data_class": dag.data_class,
                }
            )
            if result.get("status") != "succeeded":
                store.set_run_state(task_id, "failed")
                return {
                    "status": "FAILED",
                    "message": f"node {node.id} failed: {result.get('error', '')}",
                    "nodes": store.node_rows(task_id),
                }
            if node.id in dag.checkpoints:
                store.set_run_state(task_id, "paused")
                return {
                    "status": "PAUSED",
                    "message": f"checkpoint:{node.id}",
                    "nodes": store.node_rows(task_id),
                    "artifacts": store.list_artifacts(task_id),
                }
        store.set_run_state(task_id, "succeeded")
        return {
            "status": "SUCCEEDED",
            "nodes": store.node_rows(task_id),
            "artifacts": store.list_artifacts(task_id),
        }
    except Exception as exc:  # 编排失败必须以 FAILED 收场
        logger.exception("dag orchestration failed for %s", task_id)
        store.set_run_state(task_id, "failed")
        return {"status": "FAILED", "message": f"dag orchestration failed: {exc}"}
    finally:
        store.close()
