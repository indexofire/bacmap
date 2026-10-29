"""接口层共享的只读视图数据（Web / CLI / TUI 复用，避免逻辑三处重复）。

所有函数都从注入的 ``DbosTaskEngine``（其 ``home``）解析路径，随 ``--home`` 正确，
不读模块级常量（ADR-03）。
"""

from __future__ import annotations

import json
import os
import shutil
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from bacmap.agent.llm.endpoints import load_llm_config
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine


def overview_data(engine: DbosTaskEngine) -> dict[str, Any]:
    """系统概览只读数据——端点/路由/数据策略/版本/路径/沙箱/任务分布，零密钥。"""
    home = Path(engine.home)
    cfg = load_llm_config(home / "config.toml")
    endpoints = [
        {
            "name": e.name,
            "location": e.location,
            "base_url": e.base_url,
            "model": e.model,
            "enabled": e.enabled,
        }
        for e in cfg.endpoints.values()
    ]
    versions: dict[str, str] = {}
    for pkg in ("bacmap", "gside", "gapit", "gmlst"):
        try:
            versions[pkg] = pkg_version(pkg)
        except PackageNotFoundError:
            versions[pkg] = "未安装"
    if shutil.which("apptainer"):
        sandbox = "Apptainer"
    elif shutil.which("podman"):
        sandbox = "Podman"
    else:
        sandbox = "无可用后端（mine 任务将失败）"
    if os.environ.get("BACMAP_ALLOW_UNSANDBOXED") == "1":
        sandbox += " · 直通通道已开启"
    try:
        counts = engine.count_states()
    except Exception:
        counts = {}
    return {
        "endpoints": endpoints,
        "routing": cfg.routing,
        "cloud_max_data_class": cfg.policy.cloud_max_data_class.name,
        "versions": versions,
        "paths": {
            "BACMAP_HOME": str(home),
            "data/": str(home / "data"),
            "results/": str(home / "results"),
            "workflows/": str(home / "workflows"),
        },
        "sandbox": sandbox,
        "task_counts": dict(counts),
    }


def sample_digest(summary: dict[str, Any]) -> dict[str, Any]:
    """summary JSON → 展示行（物种/MLST/血清型/基因计数，口径对齐 bio_get_result）。"""
    from bacmap.core.utils import parse_mlst

    steps = summary.get("steps", {}) or {}
    sp = steps.get("species", {}) or {}
    # 真实 summary 存 steps.species.species（gside）；旧 fixtures 用 verdict。
    if isinstance(sp, dict):
        verdict = str(sp.get("verdict") or sp.get("species") or "N/A")
    else:
        verdict = str(sp) if sp else "N/A"
    mlst_raw = steps.get("mlst", "")
    st = parse_mlst(mlst_raw)["st"] if isinstance(mlst_raw, str) and mlst_raw else "N/A"
    sero = steps.get("serotype", {}) or {}
    serovar = sero.get("sistr", "N/A") if isinstance(sero, dict) else "N/A"
    amr = steps.get("amr", {}) or {}
    card = amr.get("abricate_card", []) if isinstance(amr, dict) else []
    vfdb = amr.get("abricate_vfdb", []) if isinstance(amr, dict) else []
    plasmid_steps = steps.get("plasmid", {}) or {}
    plasmid = plasmid_steps.get("plasmidfinder", []) if isinstance(plasmid_steps, dict) else []
    dec = steps.get("dec", {}) if isinstance(steps.get("dec", {}), dict) else {}

    def _genes(hits: Any) -> list[str]:
        if not isinstance(hits, list):
            return []
        return sorted(
            {str(g.get("GENE", "")) for g in hits if isinstance(g, dict) and g.get("GENE")}
        )

    card_genes = _genes(card)
    vfdb_genes = _genes(vfdb)
    return {
        "sample_id": summary.get("_sample_id", summary.get("sample", "")),
        "verdict": verdict,
        "st": st,
        "serovar": serovar,
        "n_card": len(card) if isinstance(card, list) else 0,
        "n_vfdb": len(vfdb) if isinstance(vfdb, list) else 0,
        "n_plasmid": len(plasmid) if isinstance(plasmid, list) else 0,
        "ipaH": dec.get("ipaH", "N/A"),
        "pathotype": dec.get("pathotype", "N/A"),
        "card_genes": card_genes,
        "vfdb_genes": vfdb_genes,
        "plasmids": sorted(
            {str(p.get("GENE", "")) for p in plasmid if isinstance(p, dict) and p.get("GENE")}
        )
        if isinstance(plasmid, list)
        else [],
    }


def endpoint_status(engine: Any) -> str:
    """一行 LLM 端点状态（名称/位置/模型 + 连通性），供 TUI/CLI 显示。

    连通性用 ``GET <base_url>/models`` 轻量探测（3s 超时），失败按未连接报告；
    无端点时明确说明"确定性路径仍可用"（C3）。
    """
    import httpx

    from bacmap.agent.llm.endpoints import load_llm_config

    cfg = load_llm_config(Path(engine.home) / "config.toml")
    endpoint = cfg.resolve("intent_classifier")
    if endpoint is None:
        enabled = [e for e in cfg.endpoints.values() if e.enabled]
        endpoint = enabled[0] if enabled else None
    if endpoint is None:
        return "无可用 LLM 端点（确定性路径仍可用）"
    try:
        resp = httpx.get(endpoint.base_url.rstrip("/") + "/models", timeout=3.0)
        conn = "已连接" if resp.status_code < 500 else f"异常 HTTP {resp.status_code}"
    except Exception as exc:  # 连接失败/超时：如实报告
        conn = f"未连接（{type(exc).__name__}）"
    return f"{endpoint.name} [{endpoint.location}] {endpoint.model} · {conn}"


def list_runs(home: Path | str, limit: int = 50) -> list[dict[str, Any]]:
    """运行记录列表（ADR-18 证据链的只读入口）。"""
    from bacmap.store import runs as runs_store

    db = Path(home) / "runs.sqlite"
    if not db.is_file():
        return []
    return runs_store.list_runs(db, limit)


def run_detail(home: Path | str, run_id: str) -> dict[str, Any] | None:
    """单条运行记录全文（含参数、工具/数据库版本、输入哈希、种子）。"""
    from bacmap.store import runs as runs_store

    db = Path(home) / "runs.sqlite"
    if not db.is_file():
        return None
    run = runs_store.read_run(run_id, db)
    return run.model_dump(mode="json") if run is not None else None


def compare_run_records(home: Path | str, run_a: str, run_b: str) -> dict[str, Any] | None:
    """两次运行的来源逐字段比较（ADR-18）；任一不存在返回 None。"""
    from bacmap.store import runs as runs_store

    db = Path(home) / "runs.sqlite"
    if not db.is_file():
        return None
    a = runs_store.read_run(run_a, db)
    b = runs_store.read_run(run_b, db)
    if a is None or b is None:
        return None
    return runs_store.compare_runs(a, b)


def list_gom_objects(
    home: Path | str, object_type: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """GOM 最新版本对象（只读摘要：类型/版本/菌株/时间 + 载荷键名）。"""
    from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

    db = Path(home) / "gom.sqlite"
    if not db.is_file():
        return []
    if object_type:
        try:
            types = [ObjectType(object_type)]
        except ValueError:
            return []
    else:
        types = list(ObjectType)
    svc = GenomeObjectService(db)
    try:
        out: list[dict[str, Any]] = []
        for t in types:
            for go in svc.list_by_type(t, limit=limit):
                out.append(
                    {
                        "object_id": go.object_id,
                        "object_type": str(getattr(go.object_type, "value", go.object_type)),
                        "version": go.version,
                        "organism": go.organism,
                        "strain_id": go.strain_id,
                        "created_at": go.created_at.isoformat(),
                        "created_by": go.created_by,
                        "payload_keys": sorted(str(k) for k in go.payload),
                    }
                )
    finally:
        svc.close()
    out.sort(key=lambda o: str(o["created_at"]), reverse=True)
    return out[: max(1, min(limit, 500))]


def gom_object(
    home: Path | str, object_id: str, version: int | None = None
) -> dict[str, Any] | None:
    """GOM 对象全文（指定版本或最新版本）。"""
    from bacmap.store.genome_object_service import GenomeObjectService

    db = Path(home) / "gom.sqlite"
    if not db.is_file():
        return None
    svc = GenomeObjectService(db)
    try:
        try:
            latest = svc.get_latest_version(object_id)
            go = svc.read(object_id, version if version is not None else latest)
        except Exception:  # 对象/版本不存在 → 统一 None（接口层映射 404）
            return None
    finally:
        svc.close()
    return {
        "object_id": go.object_id,
        "object_type": str(getattr(go.object_type, "value", go.object_type)),
        "version": go.version,
        "schema_version": go.schema_version,
        "created_at": go.created_at.isoformat(),
        "created_by": go.created_by,
        "organism": go.organism,
        "strain_id": go.strain_id,
        "pipeline_version": go.pipeline_version,
        "payload": go.payload,
    }


def _read_summary(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["_sample_id"] = path.parent.parent.name
    return data


def load_summaries(engine: DbosTaskEngine) -> list[dict[str, Any]]:
    """已完成样本的 summary 扫描（基于 engine.home）。"""
    results = Path(engine.home) / "results"
    out: list[dict[str, Any]] = []
    for sj in sorted(results.glob("*/report/*_summary.json")):
        # 只认与样本目录同名的 summary（与 sample_page/report_path 口径一致）：
        # 报告目录里遗留的旧名 summary 不得变成第二行/读成错误样本。
        if sj.name != f"{sj.parent.parent.name}_summary.json":
            continue
        data = _read_summary(sj)
        if data is not None:
            out.append(data)
    return out


def sample_page(
    home: Path, cursor: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """按样本 ID 排序的游标分页：只列目录项，仅解析本页 summary（v1.5.2）。"""
    results = Path(home) / "results"
    # 只收与样本目录同名的 summary（与 report_path 口径一致）
    paths = sorted(
        (
            p
            for p in results.glob("*/report/*_summary.json")
            if p.name == f"{p.parent.parent.name}_summary.json"
        ),
        key=lambda p: p.parent.parent.name,
    )
    if cursor:
        paths = [p for p in paths if p.parent.parent.name > cursor]
    page: list[dict[str, Any]] = []
    has_more = False
    for sj in paths:
        if len(page) == limit:
            has_more = True
            break
        data = _read_summary(sj)
        if data is not None:
            page.append(sample_digest(data))
    next_cursor = str(page[-1]["sample_id"]) if page and has_more else None
    return page, next_cursor


def sample_rows(engine: DbosTaskEngine) -> list[dict[str, Any]]:
    """所有已完成样本的展示行。"""
    return [sample_digest(s) for s in load_summaries(engine)]


def report_path(engine: DbosTaskEngine, sample_id: str) -> Path:
    return Path(engine.home) / "results" / sample_id / "report" / f"{sample_id}_report.html"


def search_rows(
    rows: list[dict[str, Any]],
    query: str = "",
    serotype: str = "",
    mlst_st: str = "",
    amr_gene: str = "",
) -> list[dict[str, Any]]:
    """对样本展示行做关键词 + 结构化过滤（与 Web /search 同口径）。"""
    terms = [q.lower() for q in query.split() if q.strip()]
    ser_l = serotype.strip().lower()
    st_u = mlst_st.strip().upper()
    gene_l = amr_gene.strip().lower()
    hits: list[dict[str, Any]] = []
    for r in rows:
        hay = " ".join(
            [str(r.get("verdict", "")), str(r.get("serovar", "")), str(r.get("st", "")),
             *r.get("card_genes", []), *r.get("vfdb_genes", [])]
        ).lower()
        if terms and not all(t in hay for t in terms):
            continue
        if ser_l and ser_l not in str(r.get("serovar", "")).lower():
            continue
        if st_u and str(r.get("st", "")).upper() != st_u:
            continue
        if gene_l and gene_l not in [
            g.lower() for g in (*r.get("card_genes", []), *r.get("vfdb_genes", []))
        ]:
            continue
        hits.append(r)
    return hits
