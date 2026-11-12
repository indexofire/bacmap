"""Bakta + eggNOG-mapper 注释结果解析与合并（纯函数，无 Snakemake 依赖）。

工作流 ``rules/annotation.smk`` 在 QUAST 之后运行 Bakta（基因组注释）与
eggNOG-mapper（功能分类），本模块把两种输出归一为 ``annotation.json``：

- ``summary.total_CDS`` / ``annotated_CDS`` / ``annotation_rate``（Bakta）
- ``summary.bakta``（CDS/rRNA/tRNA/tmRNA/ncRNA/CRISPR/sORF 计数）
- ``summary.eggnog``（COG 分类计数、GO/KEGG/CAZy/Pfam 计数）
- ``features``（非 hypothetical 的 CDS，附带 eggNOG 功能字段）
- ``eggnog``（eggNOG 原始行，供下游报告/挖掘使用）

Bakta v6 schema 变更（v1.10.25）：``stats`` 只剩
``size/gc/n_ratio/n50/n90/coding_ratio``——rRNA/tRNA/tmRNA/ncRNA/CRISPR/sORF/
pseudogene 计数改由 ``features[].type``（及 ``pseudogene`` 标记）统计，
``coding_density`` 由 ``coding_ratio`` × 100 换算。v5 的 ``stats`` 计数仍优先，
旧运行目录的 JSON 不受影响。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

_HYPOTHETICAL = {
    "",
    "hypothetical protein",
    "hypothetical",
    "unknown protein",
    "putative protein",
    "uncharacterized protein",
}


def _count(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("count", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"-", "None", "nan"} else text


def _split_list(value: Any) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    return [
        part.strip()
        for part in text.replace(";", ",").split(",")
        if part.strip() not in {"", "-"}
    ]


def parse_bakta(data: dict[str, Any]) -> dict[str, Any]:
    """Bakta JSON → 统计与 CDS 特征（容忍不同小版本字段差异）。"""
    stats = data.get("stats", {}) if isinstance(data.get("stats"), dict) else {}
    raw_features = data.get("features", [])
    features = raw_features if isinstance(raw_features, list) else []

    cds_features = [
        feat
        for feat in features
        if isinstance(feat, dict)
        and str(feat.get("type", "")).lower() in {"cds", "sorf"}
    ]
    total_cds = _count(stats.get("cds")) or sum(
        1 for feat in cds_features if str(feat.get("type", "")).lower() == "cds"
    )

    # Bakta v6：stats 不再带特征计数，按 features[].type 统计（v5 stats 优先）。
    type_counts: Counter[str] = Counter(
        str(feat.get("type", "")).lower() for feat in features if isinstance(feat, dict)
    )

    def _stat(names: tuple[str, ...], feat_type: str) -> int:
        for name in names:
            if name in stats and stats.get(name) is not None:
                return _count(stats.get(name))
        return type_counts.get(feat_type, 0)

    if "pseudogenes" in stats and stats.get("pseudogenes") is not None:
        pseudogenes = _count(stats.get("pseudogenes"))
    else:
        pseudogenes = sum(
            1
            for feat in features
            if isinstance(feat, dict)
            and str(feat.get("type", "")).lower() == "cds"
            and bool(feat.get("pseudogene"))
        )
    coding_density = stats.get("coding_density")
    if coding_density is None and isinstance(stats.get("coding_ratio"), (int, float)):
        # v6：coding_ratio 为 0-1 比例；报告沿用百分数口径。
        coding_density = round(float(stats["coding_ratio"]) * 100, 2)

    annotated: list[dict[str, Any]] = []
    for feat in cds_features:
        product = _clean(feat.get("product"))
        gene = _clean(
            feat.get("gene")
            or feat.get("locus")
            or feat.get("locus_tag")
            or feat.get("id")
        )
        hypothetical = (
            product.lower() in _HYPOTHETICAL
            or product.lower().startswith("hypothetical")
        )
        if not gene:
            continue
        record = {
            "gene": gene,
            "product": product,
            "identity": 100.0,
            "source": "bakta",
            "type": str(feat.get("type", "cds")).lower(),
            "locus_tag": _clean(feat.get("locus") or feat.get("locus_tag") or gene),
            "contig": _clean(feat.get("contig")),
            "start": feat.get("start"),
            "stop": feat.get("stop"),
            "strand": _clean(feat.get("strand")),
            "hypothetical": hypothetical,
        }
        annotated.append(record)

    return {
        "total_cds": total_cds,
        "annotated_cds": sum(
            1
            for feat in annotated
            if feat["type"] == "cds" and not feat["hypothetical"]
        ),
        "features": annotated,
        "stats": {
            "cds": total_cds,
            "rrna": _stat(("rrna",), "rrna"),
            "trna": _stat(("trna",), "trna"),
            "tmrna": _stat(("tmrna",), "tmrna"),
            "ncrna": _stat(("ncrna",), "ncrna"),
            "crispr": _stat(("crispr",), "crispr"),
            "orfs": _stat(("orfs", "sorf"), "sorf"),
            "pseudogenes": pseudogenes,
            "coding_density": coding_density,
        },
    }


def parse_eggnog(text: str) -> list[dict[str, Any]]:
    """eggNOG-mapper ``.emapper.annotations`` 文本 → 行字典列表。

    注释文件头部是 ``##`` 注释与 ``#query`` 表头；缺失列补空串，``-`` 归一为空。
    """
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    for line in text.splitlines():
        if not line or line.startswith("##"):
            continue
        if line.startswith("#"):
            header = [part.lstrip("#").strip() for part in line.split("\t")]
            continue
        if header is None:
            continue
        fields = line.split("\t")
        if len(fields) < len(header):
            fields += [""] * (len(header) - len(fields))
        row = {key: _clean(value) for key, value in zip(header, fields, strict=False)}
        if row.get("query"):
            rows.append(row)
    return rows


def _eggnog_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cog_counts: dict[str, int] = {}
    go_terms: set[str] = set()
    ko_terms: set[str] = set()
    pathways: set[str] = set()
    cazy: set[str] = set()
    pfams: set[str] = set()
    annotated = 0
    for row in rows:
        category = _clean(row.get("COG_category"))
        if category:
            for letter in category:
                if letter.isalpha():
                    cog_counts[letter.upper()] = cog_counts.get(letter.upper(), 0) + 1
        go_terms.update(_split_list(row.get("GOs")))
        ko_terms.update(_split_list(row.get("KEGG_ko")))
        pathways.update(_split_list(row.get("KEGG_Pathway")))
        cazy.update(_split_list(row.get("CAZy")))
        pfams.update(_split_list(row.get("PFAMs")))
        if (
            category
            or _clean(row.get("Description"))
            or _clean(row.get("Preferred_name"))
        ):
            annotated += 1
    return {
        "queries": len(rows),
        "annotated": annotated,
        "cog_category_counts": dict(sorted(cog_counts.items())),
        "go_term_count": len(go_terms),
        "kegg_ko_count": len(ko_terms),
        "kegg_pathway_count": len(pathways),
        "cazy_count": len(cazy),
        "pfam_count": len(pfams),
    }


def _attach_eggnog(features: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    by_query = {row.get("query", ""): row for row in rows if row.get("query")}
    for feature in features:
        keys = {
            feature.get("locus_tag", ""),
            feature.get("gene", ""),
            feature.get("locus_tag", "").split("_")[0],
        }
        match = next((by_query[key] for key in keys if key in by_query), None)
        if match is None:
            continue
        feature["eggnog"] = {
            "seed_ortholog": match.get("seed_ortholog", ""),
            "evalue": match.get("evalue", ""),
            "score": match.get("score", ""),
            "cog_category": match.get("COG_category", ""),
            "description": match.get("Description", ""),
            "preferred_name": match.get("Preferred_name", ""),
            "gos": _split_list(match.get("GOs")),
            "ec": _split_list(match.get("EC")),
            "kegg_ko": _split_list(match.get("KEGG_ko")),
            "kegg_pathway": _split_list(match.get("KEGG_Pathway")),
            "pfam": _split_list(match.get("PFAMs")),
        }


def merge_annotation(
    bakta: dict[str, Any],
    eggnog_rows: list[dict[str, Any]],
    *,
    sample: str,
) -> dict[str, Any]:
    """Bakta + eggNOG → ``bacmap.annotation/1`` JSON。"""
    parsed = parse_bakta(bakta)
    features = parsed["features"]
    _attach_eggnog(features, eggnog_rows)
    annotated_features = [feat for feat in features if not feat.get("hypothetical")]
    total = int(parsed["total_cds"])
    annotated = int(parsed["annotated_cds"])
    return {
        "schema": "bacmap.annotation/1",
        "sample": sample,
        "status": "ok",
        "summary": {
            "total_CDS": total,
            "annotated_CDS": annotated,
            "annotation_rate": round(annotated / total, 4) if total else 0.0,
            "bakta": parsed["stats"],
            "eggnog": _eggnog_summary(eggnog_rows),
        },
        "features": annotated_features,
        "eggnog": eggnog_rows,
    }
