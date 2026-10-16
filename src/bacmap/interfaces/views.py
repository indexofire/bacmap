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
    except Exception:  # noqa: BLE001 —— 概览为只读展示，统计失败降级为空
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
    verdict = sp.get("verdict", "N/A") if isinstance(sp, dict) else str(sp)
    mlst_raw = steps.get("mlst", "")
    st = parse_mlst(mlst_raw)["st"] if isinstance(mlst_raw, str) and mlst_raw else "N/A"
    sero = steps.get("serotype", {}) or {}
    serovar = sero.get("sistr", "N/A") if isinstance(sero, dict) else "N/A"
    amr = steps.get("amr", {}) or {}
    card = amr.get("abricate_card", []) if isinstance(amr, dict) else []
    vfdb = amr.get("abricate_vfdb", []) if isinstance(amr, dict) else []
    plasmid = (steps.get("plasmid", {}) or {}).get("plasmidfinder", [])
    dec = steps.get("dec", {}) if isinstance(steps.get("dec", {}), dict) else {}
    return {
        "sample_id": summary.get("_sample_id", summary.get("sample", "")),
        "verdict": verdict,
        "st": st,
        "serovar": serovar,
        "n_card": len(card),
        "n_vfdb": len(vfdb),
        "n_plasmid": len(plasmid),
        "ipaH": dec.get("ipaH", "N/A"),
        "pathotype": dec.get("pathotype", "N/A"),
        "card_genes": sorted({str(g.get("GENE", "")) for g in card if g.get("GENE")}),
        "vfdb_genes": sorted({str(g.get("GENE", "")) for g in vfdb if g.get("GENE")}),
        "amr_genes": sorted({str(g.get("GENE", "")) for g in card if g.get("GENE")}),
        "virulence_genes": sorted({str(g.get("GENE", "")) for g in vfdb if g.get("GENE")}),
        "plasmids": sorted(
            {str(p.get("GENE", "")) for p in plasmid if isinstance(p, dict) and p.get("GENE")}
        ),
    }


def load_summaries(engine: DbosTaskEngine) -> list[dict[str, Any]]:
    """已完成样本的 summary 扫描（基于 engine.home）。"""
    results = Path(engine.home) / "results"
    out: list[dict[str, Any]] = []
    for sj in sorted(results.glob("*/report/*_summary.json")):
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["_sample_id"] = sj.parent.parent.name
            out.append(data)
    return out


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
