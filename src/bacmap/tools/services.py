"""Service-backed tool handlers.

Covers bio_query_metadata, bio_add_metadata, bio_query_lab_results,
bio_add_lab_result, bio_snp_tree, bio_search_samples, bio_cgmlst. These talk
to the SQLite GOM database via hermes_bacmap.services (lazy imports). All
handlers return JSON strings. Errors are {"error": "..."}.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bacmap.core.analysis.cgmlst_projection import (
    CgmlstThresholds,
    load_thresholds_from_config,
    project_sample,
)
from bacmap.core.analysis.cgmlst_types import CgmlstProfile
from bacmap.core.utils import parse_cgmlst_profile, parse_cgmlst_profiles, parse_mlst

from ._common import (
    _DEFAULT_DB_PATH,
    _PROJECT_ROOT,
    _RESULTS_DIR,
    logger,
    tool_handler,
)

# Shigella shares the ecoli_2 scheme with E. coli and cannot be distinguished
# by scheme alone; we resolve to "E.coli" so ecoli thresholds apply. The
# project_sample S. sonnei caveat therefore only fires for samples whose
# species is set to "Shigella" elsewhere (out of scheme-driven scope here).
_CGMLST_SCHEME_SPECIES: dict[str, str] = {
    "senterica_2": "Salmonella",
    "ecoli_2": "E.coli",
    "vparahaemolyticus_3": "V.parahaemolyticus",
}


@tool_handler
def query_metadata(args: dict[str, Any], **kwargs: Any) -> str:
    """Query strain background metadata."""
    db_path = _DEFAULT_DB_PATH
    if not db_path.exists():
        return json.dumps({"error": "Database not found. Run analysis first."})

    try:
        from bacmap.store.strain_metadata import StrainMetadataService

        strain_id = args.get("strain_id")
        search_kwargs = {}
        for key in (
            "province",
            "outbreak_id",
            "sample_source",
            "isolation_date_from",
            "isolation_date_to",
        ):
            val = args.get(key)
            if val:
                search_kwargs[key] = val

        with StrainMetadataService(db_path) as svc:
            if strain_id:
                meta = svc.get(strain_id)
                if not meta:
                    return json.dumps({"error": f"Strain {strain_id} not found"})
                return json.dumps(meta.to_dict(), ensure_ascii=False)
            else:
                results = svc.search(**search_kwargs) if search_kwargs else svc.list_all()
                return json.dumps(
                    {"count": len(results), "results": [m.to_dict() for m in results]},
                    ensure_ascii=False,
                )
    except Exception as e:
        logger.exception("query_metadata failed")
        return json.dumps({"error": f"Query failed: {e}"})


@tool_handler
def add_metadata(args: dict[str, Any], **kwargs: Any) -> str:
    """Add or update strain background metadata."""
    strain_id = args.get("strain_id", "")
    data = args.get("data", {})

    if not strain_id:
        return json.dumps({"error": "strain_id is required"})
    if not data or not isinstance(data, dict):
        return json.dumps({"error": "data dict is required"})

    db_path = _DEFAULT_DB_PATH

    try:
        from bacmap.store.strain_metadata import StrainMetadataService

        with StrainMetadataService(db_path) as svc:
            meta = svc.upsert(strain_id, data)
            return json.dumps(
                {
                    "strain_id": strain_id,
                    "status": "saved",
                    "data": meta.to_dict(),
                },
                ensure_ascii=False,
            )
    except Exception as e:
        logger.exception("add_metadata failed")
        return json.dumps({"error": f"Add metadata failed: {e}"})


@tool_handler
def query_lab_results(args: dict[str, Any], **kwargs: Any) -> str:
    """Query wet lab experiment results."""
    db_path = _DEFAULT_DB_PATH
    if not db_path.exists():
        return json.dumps({"error": "Database not found."})

    try:
        from bacmap.store.lab_results import LabResultService

        sample_id = args.get("sample_id", "")
        category = args.get("category", "")
        interpretation = args.get("interpretation", "")
        test_name = args.get("test_name", "")
        result = args.get("result", "")

        with LabResultService(db_path) as svc:
            if sample_id:
                results = svc.get_by_strain(sample_id, category=category or None)
            elif any([category, interpretation, test_name, result]):
                search_kwargs: dict[str, Any] = {}
                if category:
                    search_kwargs["category"] = category
                if interpretation:
                    search_kwargs["interpretation"] = interpretation
                if test_name:
                    search_kwargs["test_name"] = test_name
                if result:
                    search_kwargs["result"] = result
                results = svc.search(**search_kwargs)
            else:
                results = svc.search(limit=200)

            return json.dumps(
                {"count": len(results), "results": [r.to_dict() for r in results]},
                ensure_ascii=False,
            )
    except Exception as e:
        logger.exception("query_lab_results failed")
        return json.dumps({"error": f"Query failed: {e}"})


@tool_handler
def add_lab_result(args: dict[str, Any], **kwargs: Any) -> str:
    """Record a wet lab experiment result."""
    strain_id = args.get("strain_id", "")
    category = args.get("category", "")
    test_name = args.get("test_name", "")
    result = args.get("result", "")

    if not all([strain_id, category, test_name, result]):
        return json.dumps({"error": "strain_id, category, test_name, result are required"})

    db_path = _DEFAULT_DB_PATH

    try:
        from bacmap.store.lab_results import LabResultService

        optional = {}
        for key in (
            "interpretation",
            "method",
            "unit",
            "standard",
            "tested_date",
            "tested_by",
            "lab",
        ):
            val = args.get(key)
            if val:
                optional[key] = val

        with LabResultService(db_path) as svc:
            lr = svc.add(strain_id, category, test_name, result, **optional)
            return json.dumps(
                {
                    "status": "saved",
                    "id": lr.id,
                    "strain_id": strain_id,
                    "category": category,
                    "test_name": test_name,
                    "result": result,
                },
                ensure_ascii=False,
            )
    except Exception as e:
        logger.exception("add_lab_result failed")
        return json.dumps({"error": f"Add lab result failed: {e}"})


@tool_handler
def snp_tree(args: dict[str, Any], **kwargs: Any) -> str:
    """Retrieve cohort-level SNP phylogenetic tree and distance matrix."""
    db_path = _DEFAULT_DB_PATH
    if db_path.exists():
        try:
            from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

            with GenomeObjectService(db_path) as gos:
                cohort_objs = [
                    o
                    for o in gos.list_by_type(ObjectType.ANALYSIS)
                    if o.strain_id
                    and o.strain_id.startswith("cohort:")
                    and o.strain_id.endswith("-snp")
                ]
                if cohort_objs:
                    latest = max(cohort_objs, key=lambda o: o.version)
                    result = {
                        "analysis_type": latest.payload.get("analysis_type"),
                        "samples": latest.payload.get("samples", []),
                        "n_samples": latest.payload.get("n_samples", 0),
                        "n_snp_sites": latest.payload.get("n_snp_sites", 0),
                        "missing_rate": latest.payload.get("missing_rate", 0),
                        "tree_newick": latest.payload.get("tree_newick", ""),
                        "pairwise_distances": latest.payload.get("pairwise_distances", {}),
                        "source": "gom",
                        "object_id": latest.object_id,
                        "version": latest.version,
                    }
                    return json.dumps(result, ensure_ascii=False)
        except Exception:
            logger.exception("GOM SNP lookup failed, falling back to disk")

    snp_json = _RESULTS_DIR / "snp" / "snp_summary.json"
    if not snp_json.exists():
        return json.dumps(
            {
                "error": "SNP tree not available. Run the SNP pipeline first "
                "(snp_calling -> joint_variant_calling -> snp_matrix -> "
                "phylo_tree -> snp_summary), then ingest via "
                "'python scripts/ingest_results.py --snp'."
            }
        )

    try:
        summary = json.loads(snp_json.read_text())
        summary["source"] = "disk"
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        logger.exception("snp_tree failed to read SNP summary")
        return json.dumps({"error": f"Failed to read SNP summary: {e}"})


@tool_handler
def cgmlst_traceback(args: dict[str, Any], **kwargs: Any) -> str:
    """Project a sample's cgMLST profile against the local reference library."""
    sample_id = args.get("sample_id", "")
    if not sample_id:
        return json.dumps({"error": "sample_id is required"})

    profile_payload = _load_cgmlst_profile_payload(sample_id)
    if profile_payload is None:
        return json.dumps(
            {"error": (f"no cgmlst profile for {sample_id}, run bio_analyze_pathogen first")}
        )

    scheme = profile_payload.get("scheme", "")
    species = _CGMLST_SCHEME_SPECIES.get(scheme, "")
    if not species:
        return json.dumps({"error": f"unknown cgmlst scheme {scheme!r} for {sample_id}"})

    query_profile = _payload_to_cgmlst_profile(profile_payload, sample_id)

    reference = _load_reference_profiles(species)
    if isinstance(reference, str):
        return json.dumps({"error": reference})
    if not reference:
        return json.dumps({"error": f"cgmlst reference library is empty for species {species!r}"})

    thresholds_or_err = _load_species_thresholds(species)
    if isinstance(thresholds_or_err, str):
        return json.dumps({"error": thresholds_or_err})
    thresholds = thresholds_or_err

    try:
        result = project_sample(query_profile, reference, thresholds, species=species)
    except ValueError as e:
        return json.dumps({"error": f"projection failed: {e}"})

    payload_dict = asdict(result)
    payload_dict["source"] = "gom" if profile_payload.get("_from_gom") else "disk"
    return json.dumps(payload_dict, ensure_ascii=False)


def _load_cgmlst_profile_payload(sample_id: str) -> dict[str, Any] | None:
    db_path = _DEFAULT_DB_PATH
    if db_path.exists():
        try:
            from bacmap.store.genome_object_service import (
                GenomeObjectService,
                ObjectType,
            )

            with GenomeObjectService(db_path) as gos:
                objs = [
                    o
                    for o in gos.list_by_type(ObjectType.ANALYSIS)
                    if o.strain_id == sample_id
                    and o.payload.get("analysis_type") == "cgmlst_profile"
                ]
                if objs:
                    latest = max(objs, key=lambda o: o.version)
                    payload = dict(latest.payload)
                    payload["_from_gom"] = True
                    return payload
        except Exception:
            logger.exception(
                "GOM cgmlst lookup failed for %s, falling back to disk",
                sample_id,
            )

    tsv_path = _RESULTS_DIR / sample_id / "typing" / "cgmlst.tsv"
    if not tsv_path.exists():
        return None

    try:
        profile = parse_cgmlst_profile(tsv_path.read_text())
    except (ValueError, OSError):
        logger.exception("cgmlst.tsv parse failed for %s", sample_id)
        return None

    if not profile.scheme or profile.n_total == 0:
        return None

    return {
        "analysis_type": "cgmlst_profile",
        "sample_id": profile.sample_id,
        "scheme": profile.scheme,
        "st_raw": profile.st_raw,
        "alleles": dict(profile.alleles),
        "n_called": profile.n_called,
        "n_total": profile.n_total,
        "missing_loci": list(profile.missing_loci),
        "novel_loci": list(profile.novel_loci),
        "ambiguous_loci": list(profile.ambiguous_loci),
        "_from_gom": False,
    }


def _payload_to_cgmlst_profile(payload: dict[str, Any], fallback_sample_id: str) -> CgmlstProfile:
    raw_alleles = payload.get("alleles", {})
    alleles: dict[str, int | None] = {}
    for locus, allele in raw_alleles.items():
        if allele is None:
            alleles[locus] = None
        elif isinstance(allele, int):
            alleles[locus] = allele
        else:
            try:
                alleles[locus] = int(allele)
            except (TypeError, ValueError):
                alleles[locus] = None

    n_total = payload.get("n_total", len(alleles))
    n_called = payload.get("n_called", sum(1 for v in alleles.values() if v is not None))
    return CgmlstProfile(
        sample_id=payload.get("sample_id", fallback_sample_id),
        scheme=payload.get("scheme", ""),
        st_raw=payload.get("st_raw", "-"),
        alleles=alleles,
        n_called=int(n_called),
        n_total=int(n_total),
        missing_loci=list(payload.get("missing_loci", [])),
        novel_loci=list(payload.get("novel_loci", [])),
        ambiguous_loci=list(payload.get("ambiguous_loci", [])),
    )


def _load_reference_profiles(species: str) -> list[CgmlstProfile] | str:
    species_key = species.lower().replace(".", "")
    ref_path = (
        _PROJECT_ROOT / "data" / "reference" / "cgmlst" / species_key / "reference_profiles.tsv"
    )
    if not ref_path.exists():
        return f"cgmlst reference library not found for species {species!r} (looked at {ref_path})"

    try:
        return parse_cgmlst_profiles(ref_path.read_text())
    except (ValueError, OSError):
        logger.exception("cgmlst reference parse failed for %s", species_key)
        return f"failed to parse cgmlst reference library for species {species!r}"


def _load_species_thresholds(species: str) -> CgmlstThresholds | str:
    config_path = _PROJECT_ROOT / "workflows" / "bacmap" / "config" / "config.yaml"
    try:
        return load_thresholds_from_config(config_path, species)
    except (ValueError, RuntimeError, OSError):
        logger.exception("cgmlst threshold load failed for %s", species)
        return f"failed to load cgmlst thresholds for species {species!r}"


@tool_handler
def search_samples(args: dict[str, Any], **kwargs: Any) -> str:
    """Search ingested samples by structured genotype fields or full-text query."""
    query = args.get("query", "").strip()
    serotype = args.get("serotype", "").strip()
    mlst_st = args.get("mlst_st", "").strip()
    amr_gene = args.get("amr_gene", "").strip()
    organism = args.get("organism", "").strip()
    limit = args.get("limit", 50)

    db_path = _DEFAULT_DB_PATH
    if not db_path.exists():
        return json.dumps(
            {"error": "GOM database not found. Run 'python scripts/ingest_results.py --all' first."}
        )

    try:
        from bacmap.store.strain_index import StrainGenotypeIndex

        idx = StrainGenotypeIndex(db_path)
        has_structured = any([serotype, mlst_st, amr_gene, organism])

        if has_structured:
            results = idx.search(
                serotype=serotype or None,
                mlst_st=mlst_st or None,
                amr_gene=amr_gene or None,
                organism=organism or None,
                limit=limit,
            )
            idx.close()

            return json.dumps(
                {
                    "filters": {
                        k: v
                        for k, v in {
                            "serotype": serotype,
                            "mlst_st": mlst_st,
                            "amr_gene": amr_gene,
                            "organism": organism,
                        }.items()
                        if v
                    },
                    "count": len(results),
                    "results": [
                        {
                            "strain_id": m.strain_id,
                            "organism": m.organism,
                            "species": m.species,
                            "serotype": m.serotype or "N/A",
                            "mlst_st": m.mlst_st or "N/A",
                            "amr_genes": sorted(set(m.amr_genes))[:20],
                            "analysis_date": m.analysis_date,
                        }
                        for m in results
                    ],
                },
                ensure_ascii=False,
            )

        idx.close()

        if not query:
            return json.dumps(
                {"error": "Provide at least one of: query, serotype, mlst_st, amr_gene, organism"}
            )

        from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

        with GenomeObjectService(db_path) as gos:
            fts_results = gos.search(query, object_type=ObjectType.ANALYSIS, limit=limit * 2)

            import re as _re

            st_match = _re.match(r"^ST\s*(\d+)$", query.strip(), _re.IGNORECASE)
            st_number = st_match.group(1) if st_match else None
            query_lower = query.lower()

            matches = []
            seen = set()
            for obj in fts_results:
                if not obj.strain_id:
                    continue
                if obj.strain_id in seen or obj.strain_id.startswith("cohort:"):
                    continue
                seen.add(obj.strain_id)

                p = obj.payload
                sero = p.get("serotype", {})
                serovar = sero.get("sistr", "") if isinstance(sero, dict) else ""

                mlst_raw = p.get("mlst", "")
                st_val = ""
                if mlst_raw and isinstance(mlst_raw, str):
                    parsed_st = parse_mlst(mlst_raw)["st"]
                    if parsed_st != "N/A":
                        st_val = parsed_st

                amr = p.get("amr", {})
                amr_genes = []
                if isinstance(amr, dict):
                    for db_name in ("abricate_card", "abricate_vfdb"):
                        for hit in amr.get(db_name, []):
                            if isinstance(hit, dict) and hit.get("GENE"):
                                amr_genes.append(hit["GENE"])

                reasons = []
                if serovar and query_lower in serovar.lower():
                    reasons.append(f"serotype={serovar}")
                if st_number and st_val == st_number:
                    reasons.append(f"MLST ST={st_val}")
                if any(query_lower in g.lower() for g in amr_genes):
                    matched = [g for g in amr_genes if query_lower in g.lower()][:3]
                    reasons.append(f"AMR: {', '.join(matched)}")
                if not reasons:
                    reasons.append("full-text match")

                matches.append(
                    {
                        "strain_id": obj.strain_id,
                        "organism": obj.organism,
                        "serotype": serovar or "N/A",
                        "mlst_st": f"ST{st_val}" if st_val else "N/A",
                        "amr_genes": sorted(set(amr_genes))[:20],
                        "matched_fields": reasons[:3],
                    }
                )

            return json.dumps(
                {"query": query, "count": len(matches), "results": matches[:limit]},
                ensure_ascii=False,
            )
    except Exception as e:
        logger.exception("search_samples failed")
        return json.dumps({"error": f"Search failed: {e}"})


@tool_handler
def review_flags(args: dict[str, Any], **kwargs: Any) -> str:
    """List Layer 3 NLI Reflector audit events (nli_reflected) from the GOM.

    Human-review loop read-back: which samples were flagged by the AI
    interpretation self-check (contradiction rate, contradicted claims)."""
    db_path = _DEFAULT_DB_PATH
    if not db_path.exists():
        return json.dumps(
            {"events": [], "note": f"GOM DB not found at {db_path}"}, ensure_ascii=False
        )

    from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

    gos = GenomeObjectService(db_path)
    limit = int(args.get("limit", 50))
    events = []
    for obj in gos.list_by_type(ObjectType.ANALYSIS):
        for ev in gos.list_events(obj.object_id):
            if ev.event_type == "nli_reflected":
                events.append(
                    {
                        "timestamp": ev.timestamp.isoformat(),
                        "object_id": obj.object_id,
                        **ev.event_payload,
                    }
                )
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return json.dumps({"events": events[:limit], "total": len(events)}, ensure_ascii=False)


def species_compare(args: dict[str, Any], **kwargs: Any) -> str:
    strain = str(args.get("strain_id", "")).strip()

    from bacmap.core.analysis.species_consensus import compare
    from bacmap.store.genome_object_service import GenomeObjectService

    with GenomeObjectService(Path(_DEFAULT_DB_PATH)) as gos:
        consensus = compare(strain, gos)

    if not consensus.methods:
        return f"菌株 {strain}: 暂无物种鉴定记录 (no species identification objects)"

    lines = [f"菌株 {strain} — 物种鉴定方法对比", "method\tspecies\tconfidence"]
    for m in consensus.methods:
        lines.append(f"{m.method}\t{m.species}\t{m.confidence}")
    lines.append(
        f"结论: {consensus.resolved_species} "
        f"(agreement={consensus.agreement}, basis={consensus.basis})"
    )
    if consensus.disagreeing_methods:
        lines.append(f"分歧方法: {', '.join(consensus.disagreeing_methods)}")
    if consensus.needs_review:
        lines.append("⚠ NEEDS_REVIEW: 同层方法冲突，需人工裁决")
    return "\n".join(lines)


_TIERS = {
    "instant": "159 MB — Mash sketch 快速预筛",
    "mini": "1-2 GB — RefSeq 精选面板 + skani（推荐，离线秒级真 ANI）",
    "sourmash": "3.7 GB — sourmash GTDB（含混合样本分解）",
    "full": "30 GB — skani 官方 GTDB 全库（查询需 <30GB RAM）",
    "standard": "101 GB — GTDB-Tk + CheckM2（classify 需 >=140GB RAM）",
}
_TIER_SCRIPT = {
    "instant": ["download_db_mash_refseq.py"],
    "mini": ["download_db_refseq_panel.py"],
    "sourmash": ["download_db_sourmash_gtdb.py"],
    "full": ["download_db_skani_gtdb.py"],
    "standard": ["download_db_gtdbtk.py", "download_db_checkm2.py"],
}


def _scripts_dir() -> Path:
    from bacmap.config import PROJECT_ROOT

    return PROJECT_ROOT / "scripts"


def _db_dir() -> Path:
    from bacmap.config import SPECIES_DB_DIR

    return SPECIES_DB_DIR


def db_setup(args: dict[str, Any], **kwargs: Any) -> str:
    import os
    import subprocess
    import sys as _sys

    action = args.get("action", "list")
    manifests = _db_dir() / "manifests"
    installed = {p.stem for p in manifests.glob("*.json")} if manifests.is_dir() else set()

    if action == "list":
        lines = ["可用鉴定数据库档位:"]
        ready_map = {
            "instant": "mash_refseq",
            "mini": "refseq_panel",
            "sourmash": "sourmash_gtdb",
            "full": "skani_gtdb",
            "standard": "gtdbtk_r232",
        }
        for tier, desc in _TIERS.items():
            mark = (
                "✅已装"
                if ready_map[tier] in installed or (tier == "standard" and "checkm2" in installed)
                else "⬜未装"
            )
            lines.append(f"  {tier:9s} {desc}  [{mark}]")
        lines.append("运行: bio_db_setup action=run tier=<档位>（后台执行，不阻塞）")
        return "\n".join(lines)

    tier = str(args.get("tier", ""))
    if tier not in _TIER_SCRIPT:
        return f"未知档位 {tier!r}；可用: {', '.join(_TIERS)}"
    scripts = _scripts_dir()
    missing = [s for s in _TIER_SCRIPT[tier] if not (scripts / s).exists()]
    if missing:
        return "下载脚本缺失: " + ", ".join(missing)

    _db_dir().mkdir(parents=True, exist_ok=True)
    log_path = _db_dir() / "setup.log"
    cmd = [
        _sys.executable,
        str(scripts / "setup_databases.py"),
        "--tier",
        tier,
        "--yes",
    ]
    with log_path.open("a") as log:
        log.write(f"\n=== bio_db_setup tier={tier} ===\n")
        subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(scripts.parent),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    return (
        f"已在后台启动 {tier} 档部署（{_TIERS[tier]}）。\n"
        f"日志: {log_path}\n用 bio_db_status 查询进度。"
    )


def db_status(args: dict[str, Any], **kwargs: Any) -> str:
    lines = []
    manifests = _db_dir() / "manifests"
    if manifests.is_dir():
        found = sorted(manifests.glob("*.json"))
        if found:
            lines.append("已装数据库:")
            import json as _json

            for m in found:
                try:
                    data = _json.loads(m.read_text())
                    lines.append(f"  ✅ {data.get('name', m.stem)} ({data.get('n_genomes', '')})")
                except _json.JSONDecodeError:
                    lines.append(f"  ✅ {m.stem}")
        else:
            lines.append("尚未安装任何鉴定数据库（仅 marker 模式可用）")
    else:
        lines.append("尚未安装任何鉴定数据库（仅 marker 模式可用）")

    log_path = _db_dir() / "setup.log"
    if log_path.is_file():
        tail = log_path.read_text(errors="replace").strip().splitlines()[-4:]
        lines.append(f"\n部署日志尾部 ({log_path}):")
        lines.extend("  " + ln for ln in tail)
    return "\n".join(lines)
