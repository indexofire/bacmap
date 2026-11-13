"""gspec 分型结果归一（`run_gspec_typing.py` 输出 → summary 字段）。

纯适配（ADR-20：判定由 gspec 做）。把每库结果整形成
``{status, databases: {db: {status, schemes, confidence, genes, error}},
serogroup, serogroup_scheme}``；`serogroup` 从 scheme 名含 ``serogroup`` 且给出
表型者取（如 ``doumith_serogroup`` → L. monocytogenes 血清群）。

``vpara_virulence`` / ``ecoh`` 的种以下判定也出自这里（v1.4.41 起无逐菌专用
smk 规则）：毒力标记（tdh/trh/tlh）与 O/H 血清型都是 gspec 库筛查结论，
bacmap 只做契约归一。
"""

from __future__ import annotations

from typing import Any

_VPARA_VIRULENCE_MARKS = ("tdh", "trh", "tlh")


def _db_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"status": "", "schemes": {}, "confidence": "", "genes": [], "error": ""}
    schemes_raw = raw.get("schemes")
    schemes = (
        {str(k): str(v) for k, v in schemes_raw.items()}
        if isinstance(schemes_raw, dict)
        else {}
    )
    genes = raw.get("genes")
    entry: dict[str, Any] = {
        "status": str(raw.get("status", "")),
        "schemes": schemes,
        "confidence": str(raw.get("confidence", "")),
        "genes": [str(g) for g in genes] if isinstance(genes, list) else [],
        "error": str(raw.get("error", "")) if raw.get("error") else "",
    }
    # cluster 库（gspec.cluster/1|2）：保留表型与最佳位点，供报告/API 消费。
    for key in (
        "kind",
        "phenotype",
        "best_locus",
        "type",
        "loci_count",
        "raw_schema",
    ):
        if key in raw:
            entry[key] = raw[key]
    phenotypes = raw.get("phenotypes")
    if isinstance(phenotypes, dict):
        entry["phenotypes"] = {
            str(name): dict(call)
            for name, call in phenotypes.items()
            if isinstance(call, dict)
        }
    return entry


def summarize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "", "databases": {}, "serogroup": "", "serogroup_scheme": ""}
    raw_dbs = payload.get("databases")
    databases: dict[str, Any] = {}
    serogroup = ""
    serogroup_scheme = ""
    if isinstance(raw_dbs, dict):
        for db, raw in raw_dbs.items():
            entry = _db_entry(raw)
            databases[str(db)] = entry
            for scheme_name, phenotype in entry["schemes"].items():
                if "serogroup" in scheme_name.lower() and phenotype:
                    serogroup, serogroup_scheme = phenotype, scheme_name
    return {
        "status": str(payload.get("status", "")),
        "databases": databases,
        "serogroup": serogroup,
        "serogroup_scheme": serogroup_scheme,
    }


def virulence_marks(databases: Any) -> dict[str, Any] | None:
    """gspec 库筛查结果 → summary ``steps.vpa_virulence`` 契约（tdh/trh/tlh）。

    按基因名扫**所有已运行库**的 genes（官方 ``vpa_vf`` 或用户显式选择的任何
    含 tdh/trh/tlh 的库都命中；v1.4.41 前的私有 ``vpara_virulence`` 库同理）。
    无库、库未运行或无命中 → None（summary 不写该段；库 unavailable 不算失败）。
    保持既有键名（tool/database/tdh/trh/tlh/n_hits/hits），TUI 与 strain_index 零改动。
    """
    if not isinstance(databases, dict):
        return None
    merged: set[str] = set()
    source = ""
    status = ""
    for name, entry in databases.items():
        if not isinstance(entry, dict):
            continue
        # ran = 库带 scheme 且跑完；no_scheme = 库可筛查但无表型 scheme。
        # 两者 screen 都成功，基因存在性结论（tdh/trh/tlh）均有效。
        if entry.get("status") not in ("ran", "no_scheme"):
            continue
        genes = {str(g).strip().lower() for g in entry.get("genes", []) or []}
        hits = genes & set(_VPARA_VIRULENCE_MARKS)
        if hits:
            merged |= hits
            source = str(name)
            status = str(entry.get("status", ""))
    if not merged:
        return None
    return virulence_marks_from_genes(merged, source=source, status=status)


def virulence_marks_from_genes(
    genes: Any, *, source: str, status: str = "ran"
) -> dict[str, Any] | None:
    """基因名集合 → ``steps.vpa_virulence`` 契约（tdh/trh/tlh）。

    VFDB 筛查同样覆盖 tdh/tlh/trh（且官方 gspec 目录并无 ``vpa_vf`` 库），
    因此 collect_summary 在 gspec 库筛查无命中时以此作为回退来源。
    """
    marks = {str(g).strip().lower() for g in (genes or [])} & set(_VPARA_VIRULENCE_MARKS)
    if not marks:
        return None
    return {
        "tool": "gspec",
        "database": source,
        "status": status,
        **{mark: (mark in marks) for mark in _VPARA_VIRULENCE_MARKS},
        "n_hits": len(marks),
        "hits": [{"gene": g} for g in sorted(marks)],
    }


def ecoh_serotype_summary(entry: Any) -> dict[str, Any] | None:
    """``databases["ecoh"]`` → summary ``steps.dec`` 的 ecoh 血清型字段。

    ecoh 库带 typing scheme 前不可判定（no_scheme/unavailable/failed）：如实记录
    能力状态，不猜测表型；给出 scheme 表型后填 serotype/o_type/h_type。
    库未登记（None）→ None。
    """
    if not isinstance(entry, dict):
        return None
    schemes_raw = entry.get("schemes")
    schemes = schemes_raw if isinstance(schemes_raw, dict) else {}
    oh = str(schemes.get("oh_serotype", "") or "")
    o_type = str(schemes.get("o_type", "") or "")
    h_type = str(schemes.get("h_type", "") or "")
    status = str(entry.get("status", ""))
    if oh or o_type or h_type:
        return {
            "serotype": oh or "-:-",
            "o_type": o_type or "-",
            "h_type": h_type or "-",
            "interpretation": "gspec ecoh typing",
            "status": status,
        }
    reason = str(entry.get("error", "") or "")
    return {
        "serotype": "N/A",
        "o_type": "-",
        "h_type": "-",
        "interpretation": (
            "E. coli O/H serotyping needs a gspec DB built with --typing; none available yet"
        ),
        "status": status or "unavailable",
        "reason": reason,
    }


def shigella_serotype_summary(entry: Any) -> dict[str, Any] | None:
    """``databases["shi_sero"]`` → summary ``steps.dec`` 的志贺菌血清型字段。

    shi_sero 是 gspec 的 marker-set 库（``gspec.serotype/1``）：screen + typing
    后给出 ``schemes["serotype"]``。库未登记（None）→ None；库存在但无表型时
    如实记录 no_scheme/unavailable/failed，不猜血清型。
    """
    if not isinstance(entry, dict):
        return None
    schemes_raw = entry.get("schemes")
    schemes = schemes_raw if isinstance(schemes_raw, dict) else {}
    serotype = str(schemes.get("serotype", "") or "").strip()
    status = str(entry.get("status", ""))
    genes_raw = entry.get("genes")
    genes = [str(g) for g in genes_raw] if isinstance(genes_raw, list) else []
    species = "Shigella" if serotype and serotype != "Not Shigella/EIEC" else ""
    if serotype:
        return {
            "serotype": serotype,
            "species": species,
            "status": status or "ran",
            "method": "gspec shi_sero",
            "confidence": str(entry.get("confidence", "") or ""),
            "genes": genes,
        }
    return {
        "serotype": "N/A",
        "species": "",
        "status": status or "unavailable",
        "method": "gspec shi_sero",
        "confidence": "",
        "genes": genes,
        "reason": str(entry.get("error", "") or ""),
    }
