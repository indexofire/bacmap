"""DBOS-backed TaskEngine（ADR-06 默认实现；ADR-02：唯一导入 dbos 的模块群）。

analyze 任务为直线工作流（冻结设计 §5）：运行 → 运行记录 → 最小 GOM 入库
→ 分析结论门。门产出 NEEDS_HUMAN_REVIEW 时任务进入 AWAITING_APPROVAL，
approve() 后落 SUCCEEDED。

步骤与工作流采用 DBOS 规范的模块级装饰器（恢复语义要求步骤身份跨执行
稳定）；测试经模块级可注入辅助（_run_snakemake 等）monkeypatch。

**本模块只保留 step/workflow 编排核**（step 与其可注入辅助、workflow 与其
step 必须同模块——DBOS 恢复语义与测试 monkeypatch 契约）。其余职责拆至：
- ``_runtime``：DBOS 单例生命周期；
- ``_outcomes``：审批副作用 + 工作流状态→任务终态映射；
- ``task_engine``：DbosTaskEngine（tasks.sqlite CRUD/对账/审批落库）。

下方 re-export 保持 ``bacmap.tasks.engine.dbos_engine`` 的模块契约不变
（测试与既有导入路径继续生效）。
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dbos import DBOS

from bacmap.tasks.spec import Approval  # noqa: F401 — re-export（模块契约）

logger = logging.getLogger(__name__)

# --- 拆分模块 re-export（模块契约：测试/既有导入路径不变） ---------------------
from bacmap.tasks.engine._outcomes import (  # noqa: F401,E402
    _APPROVE_FINALIZERS,
    _MINE_INTERNAL_FILES,
    _finalize_curate_approval,
    _finalize_mine_approval,
    _map_workflow_outcome,
    _mine_artifacts,
)
from bacmap.tasks.engine._runtime import (  # noqa: F401,E402
    _dbos_ready,
    init_dbos,
    shutdown_dbos,
)


def _run_snakemake(params: dict[str, Any]) -> Any:
    from bacmap.workflow.runner import WorkflowRunner, deploy

    home = Path(params["home"])
    # 必须走 deploy()：全新 BACMAP_HOME 下 <home>/workflows/bacmap 尚不存在，
    # 直接把它当 cwd 会 FileNotFoundError；而显式传 deployed_dir 又会跳过内容哈希
    # 检查（升级后仍跑旧模板）。deploy() 幂等且内容变化时自动重部署。
    deployed = deploy()
    if deployed != home / "workflows" / "bacmap":
        logger.warning(
            "engine home %s 与规范部署目录 %s 不一致（BACMAP_HOME 未对齐？）", home, deployed
        )
    from bacmap.store.results_layout import link_run_results, run_results_dir

    task_id = str(params.get("task_id", ""))
    run_dir = run_results_dir(home, task_id) if task_id else home / "results"
    run_dir.mkdir(parents=True, exist_ok=True)
    runner = WorkflowRunner(
        deployed_dir=deployed, timeout=params.get("timeout", 12 * 3600)
    )
    targets = [
        str(run_dir / s / "report" / f"{s}_summary.json") for s in params["samples"]
    ]
    # 同一部署目录有 Snakemake 目录锁：并发 analyze（TUI+CLI 同时提交是合法用户行为）
    # 会撞 LockException——退避重试而非直接失败（v1.4.39）。
    import time as _time

    overrides = {"workdir": f"results/runs/{task_id}"} if task_id else None
    for attempt in range(4):
        result = runner.run(
            targets=targets, cores=params.get("cores", 8), config_overrides=overrides
        )
        if result.returncode == 0:
            # 物理结果在 runs/<task_id>/，扁平路径只做"最新运行"别名（P2 方案 A）。
            link_run_results(home, task_id, params["samples"])
            return result
        if "LockException" not in (result.stderr or ""):
            return result
        wait_s = 45 * (attempt + 1)
        logger.warning(
            "snakemake 目录锁被占用（attempt %d/4），%ds 后重试", attempt + 1, wait_s
        )
        _time.sleep(wait_s)
    return result


def _load_summary(home: Path, sample: str) -> dict[str, Any]:
    p = home / "results" / sample / "report" / f"{sample}_summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _fastqs(home: Path, samples: list[str]) -> list[Path]:
    """样本输入文件解析：samples.tsv 登记优先（路径相对部署目录 workflows/bacmap），
    gs/ 约定布局回退——登记在任意位置的样本不再丢失 input_files（C4 证据链）。
    v1.4.33：assembly 直入样本（无 R1/R2，登记 assembly 列）以 FASTA 入证据链。"""
    tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    registered: dict[str, tuple[str, str]] = {}
    registered_asm: dict[str, str] = {}
    if tsv.is_file():
        with tsv.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                sid = (row.get("sample") or "").strip()
                r1 = (row.get("R1") or "").strip()
                r2 = (row.get("R2") or "").strip()
                asm = (row.get("assembly") or "").strip()
                if sid and r1 and r2:
                    registered[sid] = (r1, r2)
                elif sid and asm:
                    registered_asm[sid] = asm
    out: list[Path] = []
    for s in samples:
        if s in registered:
            pair = [home / "workflows" / "bacmap" / p for p in registered[s]]
        elif s in registered_asm:
            # assembly 直入：与 Snakefile assembly_path 同约定（相对 BACMAP_HOME）
            pair = [home / registered_asm[s]]
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


def _progress(params: dict[str, Any], step: str) -> None:
    from bacmap.tasks.engine._progress import record_step

    record_step(Path(params["home"]), str(params.get("task_id", "")), step)


@DBOS.step()
def _step_run(params: dict[str, Any]) -> dict[str, Any]:
    _progress(params, "pipeline")
    try:
        with _memory_arbiter().heavy_step():
            proc = _run_snakemake(params)
    except Exception as exc:  # 记录而非静默：失败以 FAILED + message 呈现，不留裸 DBOS 堆栈
        logger.exception("analyze step failed")
        return {"returncode": 1, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "returncode": proc.returncode,
        "error": None,
        "stderr_tail": (getattr(proc, "stderr", "") or "").strip()[-500:],
    }


@DBOS.step()
def _step_create_run(params: dict[str, Any]) -> dict[str, Any]:
    from bacmap.store import runs

    _progress(params, "run_record")
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

    _progress(params, "ingest_and_gates")
    home = Path(params["home"])
    runs.finalize_run(run_id, home / "runs.sqlite", home / "runs")


def _analysis_provenance(home: Path, run_id: str) -> dict[str, Any]:
    """ANALYSIS 对象的证据链字段（C4/ADR-18）：流程版本 + 数据库/工具实测版本。

    pipeline_version 优先取运行记录的工作流 Git commit，缺省回退部署期工作流内容哈希
    （`.bacmap_workflow_sha`）；tool_versions 由运行记录 probe 保证非空。
    """
    from bacmap.store import runs

    stamp = home / "workflows" / "bacmap" / ".bacmap_workflow_sha"
    fallback = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else "unknown"
    fallback = fallback or "unknown"
    run = runs.read_run(run_id, home / "runs.sqlite")
    if run is None:
        return {
            "pipeline_version": fallback,
            "database_versions": {},
            "tool_versions": {"workflow": fallback},
        }
    pipeline_version = run.workflow_commit or fallback
    return {
        "pipeline_version": pipeline_version,
        "database_versions": {r.name: r.version for r in run.ref_databases},
        "tool_versions": dict(run.tool_versions) or {"workflow": pipeline_version},
    }


def _ingest_analysis_object(
    home: Path,
    object_id: str,
    strain_id: str,
    payload: dict[str, Any],
    provenance: dict[str, Any],
    organism: str | None,
) -> str:
    """幂等写入一个 ANALYSIS 对象；同 object_id 已存在（崩溃恢复重跑）则返回既有 id。"""
    from bacmap.store.genome_object_service import (
        GenomeObject,
        GenomeObjectService,
        GOMImmutableError,
        ObjectType,
    )

    try:
        with GenomeObjectService(home / "gom.sqlite") as gos:
            created = gos.create(
                GenomeObject(
                    object_id=object_id,
                    object_type=ObjectType.ANALYSIS,
                    version=1,
                    schema_version="1.0.0",
                    created_at=datetime.now(UTC),
                    created_by="bacmap.tasks",
                    payload=payload,
                    pipeline_version=provenance["pipeline_version"],
                    database_versions=provenance["database_versions"],
                    tool_versions=provenance["tool_versions"],
                    organism=organism or None,
                    strain_id=strain_id,
                )
            )
        return created.object_id
    except GOMImmutableError:
        return object_id


@DBOS.step()
def _step_ingest_gom(home_s: str, sample: str, run_id: str, summary: dict[str, Any]) -> str:
    """把单样本分析结果入库 GOM（ANALYSIS，指向 run_id）并同步特征索引。

    payload 采用"扁平分型视图 + 完整 summary"：扁平键（species_verdict/serotype/
    mlst/amr/dec/plasmid）供 `bio_search_samples` 与特征索引读取，`summary` 保留
    原始结果供比较运行（compare_runs）与报告。
    """
    from bacmap.store.strain_index import StrainGenotypeIndex, _extract_genotype

    home = Path(home_s)
    steps = summary.get("steps", {}) or {}
    sp = steps.get("species", {}) or {}
    species = (
        str(sp.get("verdict") or sp.get("species") or "") if isinstance(sp, dict) else str(sp)
    )
    payload: dict[str, Any] = {
        "analysis_type": "sample_analysis",
        "sample_id": sample,
        "run_id": run_id,
        "species_verdict": species,
        "serotype": steps.get("serotype") if isinstance(steps.get("serotype"), dict) else {},
        "mlst": steps.get("mlst") if isinstance(steps.get("mlst"), str) else "",
        "amr": steps.get("amr") if isinstance(steps.get("amr"), dict) else {},
        "dec": steps.get("dec") if isinstance(steps.get("dec"), dict) else {},
        "plasmid": steps.get("plasmid") if isinstance(steps.get("plasmid"), dict) else {},
        "summary": summary,
    }
    provenance = _analysis_provenance(home, run_id)
    object_id = _ingest_analysis_object(
        home, f"analysis:{sample}:{run_id}", sample, payload, provenance, species or None
    )

    # 同步本地菌株特征索引（ADR-19 读回/去重）：与 GOM 同库，供 bio_search_samples。
    genotype = _extract_genotype(payload)
    idx = StrainGenotypeIndex(home / "gom.sqlite")
    try:
        idx.upsert(
            strain_id=sample,
            organism=species,
            species=genotype["species"],
            serotype=genotype["serotype"],
            serotype_method=genotype["serotype_method"],
            mlst_scheme=genotype["mlst_scheme"],
            mlst_st=genotype["mlst_st"],
            plasmid_types=genotype["plasmid_types"],
            amr_genes=genotype["amr_genes"],
            object_id=object_id,
            analysis_date=datetime.now(UTC).isoformat(),
            pipeline_version=provenance["pipeline_version"],
        )
    finally:
        idx.close()
    return object_id


@DBOS.step()
def _step_ingest_cgmlst_profiles(home_s: str, samples: list[str], run_id: str) -> int:
    """入库逐样本 cgMLST 谱（ANALYSIS cgmlst_profile，指向 run_id）。"""
    from bacmap.core.utils import parse_cgmlst_profile

    home = Path(home_s)
    provenance = _analysis_provenance(home, run_id)
    count = 0
    for sample in samples:
        tsv = home / "results" / sample / "typing" / "cgmlst.tsv"
        if not tsv.is_file():
            continue
        try:
            profile = parse_cgmlst_profile(tsv.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.exception("cgmlst profile parse failed for %s", sample)
            continue
        if not profile.scheme or profile.n_total == 0:
            continue
        payload: dict[str, Any] = {
            "analysis_type": "cgmlst_profile",
            "sample_id": profile.sample_id or sample,
            "scheme": profile.scheme,
            "n_loci": profile.n_total,
            "st_raw": profile.st_raw,
            "alleles": dict(profile.alleles),
            "n_called": profile.n_called,
            "n_total": profile.n_total,
            "missing_loci": list(profile.missing_loci),
            "novel_loci": list(profile.novel_loci),
            "ambiguous_loci": list(profile.ambiguous_loci),
        }
        _ingest_analysis_object(
            home, f"cgmlst_profile:{sample}:{run_id}", sample, payload, provenance, None
        )
        count += 1
    return count


@DBOS.step()
def _step_ingest_cohorts(home_s: str, run_id: str) -> int:
    """入库队列级 SNP / cgMLST 汇总（ANALYSIS，strain_id = cohort:<group>-<kind>）。"""
    home = Path(home_s)
    provenance = _analysis_provenance(home, run_id)
    specs = (
        ("snp", "snp_summary.json", "-snp", "snp_cohort"),
        ("cgmlst", "cgmlst_summary.json", "-cgmlst", "cgmlst_cohort"),
    )
    count = 0
    for sub, filename, suffix, analysis_type in specs:
        base = home / "results" / sub
        if not base.is_dir():
            continue
        for summary_path in sorted(base.glob(f"*/{filename}")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                logger.exception("cohort summary read failed: %s", summary_path)
                continue
            if not isinstance(summary, dict):
                continue
            group = summary_path.parent.name
            payload = dict(summary)
            payload["analysis_type"] = analysis_type
            payload["run_id"] = run_id
            payload.setdefault("group", group)
            strain_id = f"cohort:{group}{suffix}"
            organism = summary.get("organism")
            _ingest_analysis_object(
                home,
                f"{strain_id}:{run_id}",
                strain_id,
                payload,
                provenance,
                organism if isinstance(organism, str) else None,
            )
            count += 1
    return count


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
    with gos:
        try:
            gos.get_latest_version(task_id)
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
        return created.object_id


@DBOS.step()
def _step_gate_audit(home_s: str, task_id: str, gate_result: dict[str, Any]) -> None:
    """把无样本锚点的门评估写入 GOM 任务对象（§4.2/ADR-07）。"""
    from bacmap.store.genome_object_service import record_gate_event
    from bacmap.tasks.engine._progress import record_step

    home = Path(home_s)
    record_step(home, task_id, "gate")
    object_id = _ensure_task_object(home, task_id)
    record_gate_event(home / "gom.sqlite", object_id, gate_result)


# ---------------------------------------------------------------------------
# analyze 工作流（模块级装饰；函数体经模块名引用步骤，测试可替换）
# ---------------------------------------------------------------------------


@DBOS.step()
def _step_register_inputs(params: dict[str, Any]) -> dict[str, Any]:
    """目录直入登记（v1.4.38/39）：``fasta_dir``（物种逐株 gside 自动识别）或
    ``fastq_dir``（配对识别，species 省略时登记 UNK）→ samples.tsv。
    登记是写操作，经由任务引擎执行（助手可直接规划这些参数）。"""
    from bacmap.workflow.samples_registry import register_fastas, register_fastqs_dir

    _progress(params, "register_inputs")
    home = Path(params["home"])
    species = str(params.get("species") or "")
    if params.get("fasta_dir"):
        return register_fastas(home, Path(str(params["fasta_dir"])).expanduser(), species)
    return register_fastqs_dir(home, Path(str(params["fastq_dir"])).expanduser(), species)


@DBOS.workflow()
def analyze_workflow(params: dict[str, Any]) -> dict[str, Any]:
    home = Path(params["home"])

    if params.get("fasta_dir") or params.get("fastq_dir"):
        reg = _step_register_inputs(params)
        if not reg["samples"]:
            reasons = "；".join(f"{s['file']}: {s['reason']}" for s in reg["skipped"][:3])
            return {
                "status": "FAILED",
                "snakemake_returncode": 0,
                "message": f"目录登记后无可分析样本。{reasons}",
                "gates": {},
            }
        params = {**params, "samples": reg["samples"]}

    rc = _step_run(params)
    if rc["returncode"] != 0:
        detail = rc.get("error") or rc.get("stderr_tail") or "无 stderr 输出"
        return {
            "status": "FAILED",
            "snakemake_returncode": rc["returncode"],
            "message": f"snakemake 退出码 {rc['returncode']}：{detail}",
            "gates": {},
        }

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
    out["cgmlst_profiles_ingested"] = _step_ingest_cgmlst_profiles(
        str(home), params["samples"], run["run_id"]
    )
    out["cohorts_ingested"] = _step_ingest_cohorts(str(home), run["run_id"])
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
        logger.exception("report generation failed for %s", sample_id)
        return {"error": f"report generation failed: {exc}"}


@DBOS.step()
def _step_report(sample_id: str) -> dict[str, Any]:
    return _generate_report_for(sample_id)


def _run_sandbox(spec: Any) -> Any:
    """可注入的沙箱执行（测试 monkeypatch 点；默认 Apptainer/Podman 回退链）。"""
    from bacmap.agent.sandbox import SandboxExecutor

    return SandboxExecutor().run(spec)


def _sandbox_backend_name() -> str:
    """实际执行时会用的后端名（可注入；用于沙箱访问面/context 决策）。"""
    from bacmap.agent.sandbox import SandboxExecutor

    return SandboxExecutor().backend_name()


# ---------------------------------------------------------------------------
# mine / write 工作流（迁移第 10 步：开放路径 + V11⑤⑥）
# ---------------------------------------------------------------------------


@DBOS.step()
def _step_mine_run(params: dict[str, Any]) -> dict[str, Any]:
    """登记外部数据（零拷贝）→ 只读挂载 → 沙箱执行脚本（L2，ADR-11）。"""
    from bacmap.agent.sandbox.access import allowed_roots, build_access
    from bacmap.store.datasets import DatasetRegistry

    _progress(params, "sandbox")
    home = Path(params["home"])
    workspace = home / "workspaces" / params["task_id"]
    workspace.mkdir(parents=True, exist_ok=True)
    script = workspace / "analysis.py"
    script.write_text(params.get("script", "# no-op\n"), encoding="utf-8")

    # A：登记用户给定的数据路径（SHA256 证据链，零拷贝），随后只读挂载进沙箱。
    datasets: list[Any] = []
    input_paths = params.get("input_paths") or []
    if input_paths:
        registry = DatasetRegistry(home / "gom.sqlite")
        try:
            for path in input_paths:
                datasets.append(
                    registry.register(
                        path,
                        registered_by=params.get("submitted_by", "task"),
                        data_class=params.get("input_data_class", "D3"),
                    )
                )
        finally:
            registry.close()

    backend = _sandbox_backend_name()
    mounts, context = build_access(
        backend,
        results_dir=home / "results",
        gom_db=home / "gom.sqlite",
        datasets=datasets,
    )
    (workspace / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    spec = _build_sandbox_spec(
        params.get("sandbox_image"),
        script.name,
        workspace,
        readonly_mounts=mounts,
        allowed_readonly_roots=allowed_roots(
            results_dir=home / "results", gom_db=home / "gom.sqlite", datasets=datasets
        ),
    )
    try:
        result = _run_sandbox(spec)
    except Exception as exc:
        # 环境级失败（无沙箱后端等）不是脚本问题：带回可操作原因，而非笼统 workflow ERROR。
        result = _mine_sandbox_failure(exc, workspace, datasets)
    return {
        "returncode": result.returncode,
        "artifacts": _mine_artifacts(workspace),
        "workspace": str(workspace),
        "datasets": [d.dataset_id for d in datasets],
        # 失败时把脚本 stderr 带回任务 message（便于在 TUI/Web 直接看到原因）。
        "stderr": (getattr(result, "stderr", "") or "").strip()[-500:],
    }


def _mine_sandbox_failure(exc: Exception, workspace: Path, datasets: list[Any]) -> Any:
    """沙箱启动失败 → rc=1 结果信封（stderr 带原因；mine_workflow 转成 FAILED message）。"""
    from bacmap.agent.sandbox import SandboxResult

    hint = (
        "（安装 Apptainer 或 Podman 即解，见安装指南 §6；受控开发环境可设 "
        "BACMAP_ALLOW_UNSANDBOXED=1）" if "no apptainer" in str(exc) else ""
    )
    return SandboxResult(
        returncode=1,
        stdout="",
        stderr=f"沙箱启动失败：{type(exc).__name__}: {exc}{hint}",
        backend="unavailable",
    )


def _build_sandbox_spec(
    image: str | None,
    script_name: str,
    workspace: Path,
    readonly_mounts: dict[str, str] | None = None,
    allowed_readonly_roots: tuple[Path, ...] = (),
) -> Any:
    from bacmap.agent.sandbox import SandboxSpec

    return SandboxSpec(
        image=image or "docker://python:3.12-slim",
        command=["python", script_name],
        workspace=workspace,
        readonly_mounts=dict(readonly_mounts or {}),
        allowed_readonly_roots=tuple(allowed_readonly_roots),
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
        detail = (result.get("stderr") or "").strip() or "无 stderr 输出"
        return {
            "status": "FAILED",
            "sandbox_returncode": result["returncode"],
            "message": f"沙箱脚本退出码 {result['returncode']}：{detail[-500:]}",
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
    _progress(params, "draft")
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

    _progress(params, "curate_build")
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


# DbosTaskEngine 延迟 re-export（task_engine 反向引用本模块的 workflow，
# 顶部互相导入会循环；底部导入时双方均已定义完毕）。
from bacmap.tasks.engine.task_engine import DbosTaskEngine  # noqa: E402,F401

# ---------------------------------------------------------------------------
# record 工作流（v1.7：元数据 / 化验 / 知识库——写操作仍只经任务层）
# ---------------------------------------------------------------------------


@DBOS.step()
def _step_record(params: dict[str, Any]) -> dict[str, Any]:
    """把一条记录写入对应 store；知识库导入只入暂存，审核另起一条记录任务。"""
    from bacmap.tasks.records import (
        KnowledgeApprove,
        KnowledgeImport,
        LabResultRecord,
        MetadataRecord,
        parse_record,
    )

    _progress(params, "record")
    home = Path(params["home"])
    record = parse_record(params)
    actor = str(params.get("submitted_by") or "record")

    if isinstance(record, MetadataRecord):
        from bacmap.store.strain_metadata import StrainMetadataService

        data = dict(record.fields)
        data["sample_id"] = record.sample_id or record.strain_id
        StrainMetadataService(home / "data" / "bacmap.sqlite").upsert(record.strain_id, data)
        return {
            "status": "SUCCEEDED",
            "kind": record.kind,
            "strain_id": record.strain_id,
            "message": f"recorded metadata for {record.strain_id}",
        }

    if isinstance(record, LabResultRecord):
        from bacmap.store.lab_results import LabResultService

        payload = record.model_dump(exclude={"kind"})
        strain_id = payload.pop("strain_id")
        category = payload.pop("category")
        test_name = payload.pop("test_name")
        result_value = payload.pop("result")
        row = LabResultService(home / "data" / "bacmap.sqlite").add(
            strain_id, category, test_name, result_value, **payload
        )
        return {
            "status": "SUCCEEDED",
            "kind": record.kind,
            "lab_result_id": row.id,
            "message": f"recorded lab result for {strain_id}",
        }

    if isinstance(record, KnowledgeImport):
        from bacmap.store.knowledge import KnowledgeStore

        payload = record.model_dump(exclude={"kind"})
        payload["kind"] = payload.pop("entry_kind", "literature")
        entry_id = KnowledgeStore(home / "data" / "knowledge.sqlite").import_candidate(
            payload, imported_by=actor, task_id=str(params.get("task_id") or "")
        )
        return {
            "status": "SUCCEEDED",
            "kind": record.kind,
            "entry_id": entry_id,
            "staged": True,
            "message": f"staged knowledge entry {entry_id} (awaiting approval)",
        }

    # KNOWLEDGE_APPROVE：人审后才成为引用门认可来源
    from bacmap.store.knowledge import KnowledgeStore

    store = KnowledgeStore(home / "data" / "knowledge.sqlite")
    if not isinstance(record, KnowledgeApprove):  # pragma: no cover — 判别联合已保证
        return {"status": "FAILED", "kind": record.kind, "message": "unexpected record kind"}
    try:
        store.approve(record.entry_id, approver=actor)
    except KeyError:
        return {
            "status": "FAILED",
            "kind": record.kind,
            "message": f"no knowledge entry {record.entry_id}",
        }
    return {
        "status": "SUCCEEDED",
        "kind": record.kind,
        "entry_id": record.entry_id,
        "approved_by": actor,
        "message": f"approved knowledge entry {record.entry_id}",
    }


@DBOS.workflow()
def record_workflow(params: dict[str, Any]) -> dict[str, Any]:
    try:
        out = _step_record(params)
    except Exception as exc:  # 记录失败原因进任务消息，而不是只剩裸 workflow ERROR
        logger.exception("record step failed")
        return {"status": "FAILED", "message": f"{type(exc).__name__}: {exc}"}
    if out.get("status") != "SUCCEEDED":
        return {**out, "status": "FAILED"}
    return out
