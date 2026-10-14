"""DBOS-backed TaskEngine（ADR-06 默认实现；ADR-02：唯一导入 dbos 的模块）。

analyze 任务为直线工作流（冻结设计 §5）：运行 → 运行记录 → 最小 GOM 入库
→ 分析结论门。门产出 NEEDS_HUMAN_REVIEW 时任务进入 AWAITING_APPROVAL，
approve() 后落 SUCCEEDED。

步骤与工作流采用 DBOS 规范的模块级装饰器（恢复语义要求步骤身份跨执行
稳定）；测试经模块级可注入辅助（_run_snakemake 等）monkeypatch。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dbos import DBOS
from pydantic import BaseModel

from bacmap.tasks.spec import (
    APPROVALS_DDL,
    TASKS_DDL,
    Approval,
    TaskId,
    TaskState,
    TaskStatus,
    TaskType,
)

_dbos_ready = False


def init_dbos(db_path: Path) -> None:
    global _dbos_ready
    if _dbos_ready:
        return
    from dbos._dbos_config import DBOSConfig

    cfg = DBOSConfig(
        name="bacmap", system_database_url=f"sqlite:///{db_path.resolve().as_posix()}"
    )
    DBOS(config=cfg)
    DBOS.launch()
    _dbos_ready = True


def shutdown_dbos() -> None:
    global _dbos_ready
    if not _dbos_ready:
        return
    DBOS.destroy()
    _dbos_ready = False


# ---------------------------------------------------------------------------
# 可注入辅助（测试 monkeypatch 点；步骤函数本身保持模块级装饰）
# ---------------------------------------------------------------------------


def _run_snakemake(params: dict[str, Any]) -> Any:
    from bacmap.workflow.runner import WorkflowRunner

    home = Path(params["home"])
    runner = WorkflowRunner(
        deployed_dir=home / "workflows" / "bacmap", timeout=params.get("timeout", 12 * 3600)
    )
    targets = [
        str(home / "results" / s / "report" / f"{s}_summary.json") for s in params["samples"]
    ]
    return runner.run(targets, cores=params.get("cores", 8))


def _load_summary(home: Path, sample: str) -> dict[str, Any]:
    p = home / "results" / sample / "report" / f"{sample}_summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _fastqs(home: Path, samples: list[str]) -> list[Path]:
    """样本 FASTQ 解析：samples.tsv 登记优先（路径相对部署目录 workflows/bacmap），
    gs/ 约定布局回退——登记在任意位置的样本不再丢失 input_files（C4 证据链）。"""
    tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    registered: dict[str, tuple[str, str]] = {}
    if tsv.is_file():
        for line in tsv.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 4 and parts[0].strip():
                registered[parts[0].strip()] = (parts[2].strip(), parts[3].strip())
    out: list[Path] = []
    for s in samples:
        if s in registered:
            pair = [home / "workflows" / "bacmap" / p for p in registered[s]]
        else:
            pair = [home / "gs" / s / f"{s}_{r}.fastq.gz" for r in ("R1", "R2")]
        out.extend(f for f in pair if f.exists())
    return out


# ---------------------------------------------------------------------------
# DBOS steps（模块级装饰：步骤身份稳定，崩溃恢复可对齐）
# ---------------------------------------------------------------------------


def _memory_arbiter() -> Any:
    """构建本地模型资源仲裁器（ADR-17 / §4.5 ``[llm.resources]``）。

    模型与管线同机（co_located=true）时启用：内存密集步骤前检查可用内存，
    不足则 POST /unload 释放 Strata，步骤后 /load 恢复；模型独立主机时直通。
    测试可 monkeypatch 本函数以隔离内存探测与网络。
    """
    from bacmap.agent.llm.arbitration import StrataArbiter
    from bacmap.agent.llm.endpoints import load_llm_config
    from bacmap.config import BACMAP_HOME

    cfg = load_llm_config(BACMAP_HOME / "config.toml")
    if not cfg.resources.co_located:
        return StrataArbiter(enabled=False)
    admin_url = "http://127.0.0.1:8080"
    endpoint = cfg.endpoints.get("strata") or next(iter(cfg.endpoints.values()), None)
    if endpoint is not None:
        if endpoint.admin_url:
            admin_url = endpoint.admin_url
        else:
            admin_url = endpoint.base_url.rstrip("/")
            if admin_url.endswith("/v1"):
                admin_url = admin_url[: -len("/v1")]
    return StrataArbiter(
        admin_url=admin_url,
        enabled=True,
        min_free_gb=cfg.resources.min_free_ram_gb_for_heavy_steps,
    )


@DBOS.step()
def _step_run(params: dict[str, Any]) -> dict[str, Any]:
    with _memory_arbiter().heavy_step():
        proc = _run_snakemake(params)
    return {"returncode": proc.returncode}


@DBOS.step()
def _step_create_run(params: dict[str, Any]) -> dict[str, Any]:
    from bacmap.store import runs

    home = Path(params["home"])
    run = runs.create_run(
        workflow="bacmap",
        workflow_dir=home / "workflows" / "bacmap",
        strain_ids=params["samples"],
        input_files=_fastqs(home, params["samples"]),
        db_path=home / "runs.sqlite",
        task_id=params.get("task_id", ""),
    )
    return {"run_id": run.run_id}


@DBOS.step()
def _step_finish_run(run_id: str, params: dict[str, Any]) -> None:
    from bacmap.store import runs

    home = Path(params["home"])
    runs.finalize_run(run_id, home / "runs.sqlite", home / "runs")


@DBOS.step()
def _step_ingest_gom(home_s: str, sample: str, run_id: str, summary: dict[str, Any]) -> str:
    from bacmap.store.genome_object_service import (
        GenomeObject,
        GenomeObjectService,
        ObjectType,
    )

    gos = GenomeObjectService(Path(home_s) / "gom.sqlite")
    species = ""
    sp = ((summary.get("steps", {}) or {}).get("species", {})) or {}
    if isinstance(sp, dict):
        species = str(sp.get("verdict") or sp.get("species") or "")
    obj = GenomeObject(
        object_id=uuid.uuid4().hex,
        object_type=ObjectType.SAMPLE,
        version=1,
        schema_version="1.0.0",
        created_at=datetime.now(UTC),
        created_by="bacmap.tasks",
        payload={"summary": summary, "run_id": run_id},
        organism=species or None,
        strain_id=sample,
    )
    created = gos.create(obj)
    return created.object_id


@DBOS.step()
def _step_gate(home_s: str, sample: str, interpretation_text: str) -> dict[str, Any]:
    from bacmap.tasks import gates

    summary = _load_summary(Path(home_s), sample)
    if not summary:
        return {
            "gate": "analysis_claims",
            "verdict": "reject",
            "details": {"reason": "summary_missing", "sample_id": sample},
        }
    result = gates.evaluate_analysis_claims(interpretation_text, summary, sample)
    return result.model_dump(mode="json")


@DBOS.step()
def _step_record_gate(home_s: str, object_id: str, gate_result: dict[str, Any]) -> None:
    """把门评估写入 GOM events（§4.2 / ADR-07：event_type = "gate.<name>"）。"""
    from bacmap.store.genome_object_service import record_gate_event

    record_gate_event(Path(home_s) / "gom.sqlite", object_id, gate_result)


def _ensure_task_object(home: Path, task_id: str) -> str:
    """为任务建一个 GOM TASK 对象作门事件锚点（幂等，object_id == task_id）。

    mine / write / curate 的门没有样本对象可挂，§4.2 要求每次门评估留痕，
    故以任务对象为锚。
    """
    from bacmap.store.genome_object_service import (
        GenomeObject,
        GenomeObjectService,
        GOMNotFoundError,
        ObjectType,
    )

    gos = GenomeObjectService(home / "gom.sqlite")
    try:
        gos.get_latest_version(task_id)
        gos.close()
        return task_id
    except GOMNotFoundError:
        pass
    obj = GenomeObject(
        object_id=task_id,
        object_type=ObjectType.TASK,
        version=1,
        schema_version="1.0.0",
        created_at=datetime.now(UTC),
        created_by="bacmap.tasks",
        payload={},
    )
    created = gos.create(obj)
    gos.close()
    return created.object_id


@DBOS.step()
def _step_gate_audit(home_s: str, task_id: str, gate_result: dict[str, Any]) -> None:
    """把无样本锚点的门评估写入 GOM 任务对象（§4.2/ADR-07）。"""
    from bacmap.store.genome_object_service import record_gate_event

    home = Path(home_s)
    object_id = _ensure_task_object(home, task_id)
    record_gate_event(home / "gom.sqlite", object_id, gate_result)


# ---------------------------------------------------------------------------
# analyze 工作流（模块级装饰；函数体经模块名引用步骤，测试可替换）
# ---------------------------------------------------------------------------


@DBOS.workflow()
def analyze_workflow(params: dict[str, Any]) -> dict[str, Any]:
    home = Path(params["home"])

    rc = _step_run(params)
    if rc["returncode"] != 0:
        return {"status": "FAILED", "snakemake_returncode": rc["returncode"], "gates": {}}

    run = _step_create_run(params)
    _step_finish_run(run["run_id"], params)

    out: dict[str, Any] = {"status": "SUCCEEDED", "run_id": run["run_id"], "gates": {}}
    text = params.get("interpretation_text", "")
    for s in params["samples"]:
        summary = _load_summary(home, s)
        object_id: str | None = None
        if summary:
            object_id = _step_ingest_gom(str(home), s, run["run_id"], summary)
        gate_out = _step_gate(str(home), s, text)
        if object_id is not None:
            _step_record_gate(str(home), object_id, gate_out)
        out["gates"][s] = gate_out
        out.setdefault("reports", {})[s] = _step_report(s)
    if any(g["verdict"] != "pass" for g in out["gates"].values()):
        out["status"] = "AWAITING_APPROVAL"
    return out


def _generate_report_for(sample_id: str) -> dict[str, Any]:
    """任务末尾模板化分析报告（冻结 §2 注①：确定性路径、C3 无 LLM 可用）。

    报告失败不拖垮分析任务——返回 error 信封供人审跟进。
    """
    from bacmap.tools.pipeline import generate_report

    try:
        raw = generate_report({"sample_id": sample_id})
        parsed = json.loads(raw) if isinstance(raw, str) else {"error": str(raw)}
        return dict(parsed)
    except Exception as exc:  # 报告为呈现层：任何失败降级为 error 信封
        return {"error": f"report generation failed: {exc}"}


@DBOS.step()
def _step_report(sample_id: str) -> dict[str, Any]:
    return _generate_report_for(sample_id)


def _run_sandbox(spec: Any) -> Any:
    """可注入的沙箱执行（测试 monkeypatch 点；默认 Apptainer/Podman 回退链）。"""
    from bacmap.agent.sandbox import SandboxExecutor

    return SandboxExecutor().run(spec)


# ---------------------------------------------------------------------------
# mine / write 工作流（迁移第 10 步：开放路径 + V11⑤⑥）
# ---------------------------------------------------------------------------


@DBOS.step()
def _step_mine_run(params: dict[str, Any]) -> dict[str, Any]:
    """沙箱执行脚本，产物落 workspace（L2，ADR-11）。"""
    home = Path(params["home"])
    workspace = home / "workspaces" / params["task_id"]
    workspace.mkdir(parents=True, exist_ok=True)
    script = workspace / "analysis.py"
    script.write_text(params.get("script", "# no-op\n"), encoding="utf-8")
    spec = _build_sandbox_spec(params.get("sandbox_image"), script.name, workspace)
    result = _run_sandbox(spec)
    artifacts = [
        {"name": f.name, "reproducible": True}
        for f in sorted(workspace.iterdir())
        if f.is_file() and f != script
    ]
    return {
        "returncode": result.returncode,
        "artifacts": artifacts,
        "workspace": str(workspace),
    }


def _build_sandbox_spec(image: str | None, script_name: str, workspace: Path) -> Any:
    from bacmap.agent.sandbox import SandboxSpec

    return SandboxSpec(
        image=image or "docker://python:3.12-slim",
        command=[sys.executable, script_name],
        workspace=workspace,
    )


@DBOS.step()
def _step_mining_gate(artifacts: list[dict[str, Any]], signed_by: str | None) -> dict[str, Any]:
    from bacmap.tasks import gates

    result = gates.evaluate_mining({"artifacts": artifacts, "signed_by": signed_by})
    return result.model_dump(mode="json")


@DBOS.workflow()
def mine_workflow(params: dict[str, Any]) -> dict[str, Any]:
    """沙箱运行 → 产物清单 → 挖掘门校验（未签字必 REJECT）→ AWAITING_APPROVAL。

    approve() 时带 signed_by 重过挖掘门（V11⑤：未签字产物不得进入报告）。
    """
    result = _step_mine_run(params)
    if result["returncode"] != 0:
        return {
            "status": "FAILED",
            "sandbox_returncode": result["returncode"],
            "gates": {},
        }
    gate = _step_mining_gate(result["artifacts"], None)
    _step_gate_audit(params["home"], params["task_id"], gate)
    return {
        "status": "AWAITING_APPROVAL",
        "gates": gate,
        "artifacts": result["artifacts"],
        "workspace": result["workspace"],
    }


@DBOS.step()
def _step_write_draft(params: dict[str, Any]) -> dict[str, Any]:
    """成稿（provided-draft 模式；LLM 生成走 gateway，本步可注入）。

    known_citations 缺省时从本地文献知识库装载已人审条目标识符
    （store.knowledge，引用门后端；ADR-07/V11⑥）。
    """
    known = params.get("known_citations")
    if known is None:
        from bacmap.store.knowledge import KnowledgeStore

        home = Path(params["home"])
        known = KnowledgeStore(home / "data" / "knowledge.sqlite").known_citations()
    return {
        "draft": params.get("draft", ""),
        "known_citations": list(known),
    }


@DBOS.step()
def _step_citation_gate(draft: str, known: list[str]) -> dict[str, Any]:
    from bacmap.tasks import gates

    result = gates.evaluate_citation({"draft": draft, "known_citations": known})
    return result.model_dump(mode="json")


@DBOS.workflow()
def write_workflow(params: dict[str, Any]) -> dict[str, Any]:
    """成稿 → 引用门（V11⑥：不在知识库的引用 → 拒绝）→ AWAITING_APPROVAL。"""
    draft_result = _step_write_draft(params)
    gate = _step_citation_gate(draft_result["draft"], draft_result["known_citations"])
    _step_gate_audit(params["home"], params["task_id"], gate)
    if gate["verdict"] != "pass":
        return {
            "status": "FAILED",
            "gates": {"citation": gate},
            "draft": draft_result["draft"],
        }
    return {
        "status": "AWAITING_APPROVAL",
        "gates": {"citation": gate},
        "draft": draft_result["draft"],
    }


# ---------------------------------------------------------------------------
# curate 工作流（ADR-19：本地流行特征库）
# ---------------------------------------------------------------------------


@DBOS.step()
def _step_curate_build(params: dict[str, Any]) -> dict[str, Any]:
    from bacmap.store import baseline
    from bacmap.tasks import gates

    home = Path(params["home"])
    manifest = baseline.build_candidate(home, params.get("scope"))
    gate = gates.evaluate_baseline_release(manifest)
    gate_d = gate.model_dump(mode="json")
    baseline.save_candidate(home / "baseline.sqlite", params["task_id"], manifest, gate_d)
    if gate.verdict != gates.GateVerdict.PASS:
        return {"status": "FAILED", "gate": gate_d, "n_strains": 0}
    return {
        "status": "AWAITING_APPROVAL",
        "gate": gate_d,
        "n_strains": len(manifest.get("strains", [])),
        "n_excluded": len(manifest.get("excluded", [])),
    }


@DBOS.workflow()
def curate_workflow(params: dict[str, Any]) -> dict[str, Any]:
    out = _step_curate_build(params)
    if isinstance(out.get("gate"), dict):
        _step_gate_audit(params["home"], params["task_id"], out["gate"])
    return out


# ---------------------------------------------------------------------------
# TaskEngine 实现
# ---------------------------------------------------------------------------


class DbosTaskEngine:
    """analyze 任务的 DBOS 实现（curate/mine/write 随迁移第 7/10 步接入）。"""

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.db = self.home / "tasks.sqlite"
        self.home.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(TASKS_DDL)
            conn.execute(APPROVALS_DDL)
        init_dbos(self.home / "dbos.sqlite")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn

    def submit(
        self, task_type: TaskType, params: BaseModel | dict[str, Any], submitted_by: str
    ) -> TaskId:
        workflows = {
            TaskType.ANALYZE: analyze_workflow,
            TaskType.CURATE: curate_workflow,
            TaskType.MINE: mine_workflow,
            TaskType.WRITE: write_workflow,
        }
        if task_type not in workflows:
            raise NotImplementedError(f"unsupported task type: {task_type}")
        p = params.model_dump() if isinstance(params, BaseModel) else dict(params)
        p.setdefault("home", str(self.home))
        p.setdefault("cores", 8)
        task_id = uuid.uuid4().hex
        p["task_id"] = task_id

        handle = DBOS.start_workflow(workflows[task_type], p)
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
                " created_at, updated_at, workflow_id, current_step)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    task_type.value,
                    "running",
                    json.dumps(p, ensure_ascii=False),
                    submitted_by,
                    now,
                    now,
                    handle.workflow_id,
                    "analyze",
                ),
            )
        return TaskId(task_id)

    def status(self, task_id: TaskId) -> TaskStatus:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, workflow_id, current_step, message FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        state = TaskState(row["state"])
        message: str | None = row["message"]

        if state == TaskState.RUNNING and row["workflow_id"]:
            handle: Any = DBOS.retrieve_workflow(row["workflow_id"])
            raw_status = handle.get_status()
            ws = str(getattr(raw_status, "status", raw_status)).upper()
            if ws in ("PENDING", "RUNNING"):
                pass
            elif ws == "SUCCESS":
                result = handle.get_result()
                status_val = str(result.get("status", "SUCCEEDED"))
                state = {
                    "AWAITING_APPROVAL": TaskState.AWAITING_APPROVAL,
                    "FAILED": TaskState.FAILED,
                }.get(status_val, TaskState.SUCCEEDED)
                message = json.dumps(result.get("gates", {}), ensure_ascii=False)
            elif ws == "CANCELLED":
                state = TaskState.CANCELLED
            else:
                state = TaskState.FAILED
            self._transition_from_running(task_id, state.value, message)

        return TaskStatus(
            task_id=task_id, state=state, current_step=row["current_step"], message=message
        )

    def _transition_from_running(
        self, task_id: TaskId, new_state: str, message: str | None
    ) -> bool:
        """条件状态更新：仅当当前为 running 才写入（防与 approve() 的写竞态把终态降级）。"""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET state = ?, message = ?, updated_at = ?"
                " WHERE task_id = ? AND state = ?",
                (new_state, message, now, task_id, "running"),
            )
            return cur.rowcount > 0

    def cancel(self, task_id: TaskId) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT workflow_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        if row["workflow_id"]:
            DBOS.cancel_workflow(row["workflow_id"])
        self._update_state(task_id, TaskState.CANCELLED)

    def approve(self, task_id: TaskId, approval: Approval) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state, task_type, workflow_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no such task: {task_id}")
        if row["state"] != "awaiting_approval":
            raise ValueError(
                f"task {task_id} state is {row['state']!r}; "
                "only awaiting_approval tasks can be approved"
            )
        decision = getattr(approval.decision, "value", approval.decision)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO approvals (task_id, approver, decision, signature, comment, at)"
                " VALUES (?,?,?,?,?,?)",
                (task_id, approval.approver, decision, approval.signature, approval.comment, now),
            )
        new_state = TaskState.SUCCEEDED if decision == "approve" else TaskState.FAILED
        message = f"approved by {approval.approver}"
        if decision == "approve" and row["task_type"] == TaskType.MINE.value:
            from bacmap.tasks import gates as _gates

            workspace = self.home / "workspaces" / task_id
            artifacts: list[dict[str, Any]] = []
            if workspace.is_dir():
                artifacts = [
                    {"name": f.name, "reproducible": True}
                    for f in sorted(workspace.iterdir())
                    if f.is_file() and f.name != "analysis.py"
                ]
            gate = _gates.evaluate_mining(
                {"artifacts": artifacts, "signed_by": approval.approver}
            )
            if gate.verdict != _gates.GateVerdict.PASS:
                new_state = TaskState.FAILED
                message = f"mining gate rejected: {gate.details.get('problems')}"
        if decision == "approve" and row["task_type"] == TaskType.CURATE.value:
            from bacmap.store import baseline

            cand = baseline.load_candidate(self.home / "baseline.sqlite", task_id)
            if cand is None:
                new_state = TaskState.FAILED
                message = "candidate manifest missing; cannot publish"
            else:
                version = baseline.publish(
                    self.home / "baseline.sqlite",
                    cand["manifest"],
                    created_by=approval.approver,
                    signature=approval.signature,
                )
                message = f"published baseline v{version} (signed by {approval.approver})"
        self._update_state(task_id, new_state, message)

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """最近任务列表（Web 列表页消费）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT task_id, task_type, state, submitted_by, created_at, updated_at,"
                " current_step, message FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _update_state(self, task_id: TaskId, state: TaskState, message: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE tasks SET state = ?, updated_at = ?, message = COALESCE(?, message)"
                " WHERE task_id = ?",
                (state.value, now, message, task_id),
            )
