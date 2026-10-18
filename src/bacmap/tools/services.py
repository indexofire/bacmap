"""Service-backed tool handlers.

Covers bio_query_metadata, bio_add_metadata, bio_query_lab_results,
bio_add_lab_result, bio_snp_tree, bio_search_samples, bio_cgmlst,
bio_compare_runs. These talk to the SQLite GOM/runs databases and baseline
store (lazy imports). All handlers return JSON strings. Errors are {"error": "..."}.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bacmap.config import DATA_DIR as _DATA_DIR
from bacmap.config import DEPLOYED_WORKFLOWS_DIR as _DEPLOYED_WORKFLOWS_DIR
from bacmap.config import GOM_DB as _GOM_DB
from bacmap.config import REFS_DIR as _REFS_DIR
from bacmap.config import RUNS_DB as _RUNS_DB
from bacmap.core.analysis.cgmlst_projection import (
    CgmlstThresholds,
    load_thresholds_from_config,
    project_sample,
)
from bacmap.core.analysis.cgmlst_types import CgmlstProfile
from bacmap.core.utils import parse_cgmlst_profile, parse_cgmlst_profiles, parse_mlst

from ._common import (
    _DEFAULT_DB_PATH,
    _RESULTS_DIR,
    _validate_sample_id,
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
    db_path = _GOM_DB
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
    db_path = _GOM_DB
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
        _DATA_DIR / "reference" / "cgmlst" / species_key / "reference_profiles.tsv"
    )
    if not ref_path.exists():
        return f"cgmlst reference library not found for species {species!r} (looked at {ref_path})"

    try:
        return parse_cgmlst_profiles(ref_path.read_text())
    except (ValueError, OSError):
        logger.exception("cgmlst reference parse failed for %s", species_key)
        return f"failed to parse cgmlst reference library for species {species!r}"


def _load_species_thresholds(species: str) -> CgmlstThresholds | str:
    config_path = _DEPLOYED_WORKFLOWS_DIR / "config" / "config.yaml"
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
    try:
        limit = max(0, int(args.get("limit", 50)))
    except (TypeError, ValueError):
        limit = 50

    db_path = _GOM_DB
    if not db_path.exists():
        return json.dumps(
            {"error": "GOM database not found. Run an analysis first to populate it."}
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
    db_path = _GOM_DB
    if not db_path.exists():
        return json.dumps(
            {"events": [], "note": f"GOM DB not found at {db_path}"}, ensure_ascii=False
        )

    from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

    try:
        limit = max(0, int(args.get("limit", 50)))
    except (TypeError, ValueError):
        limit = 50
    events = []
    with GenomeObjectService(db_path) as gos:
        for obj in gos.list_by_type(ObjectType.ANALYSIS):
            for ev in gos.list_events(obj.object_id):
                if ev.event_type == "nli_reflected":
                    events.append(
                        {
                            # payload 先展开，timestamp/object_id 保持权威不被覆盖
                            **ev.event_payload,
                            "timestamp": ev.timestamp.isoformat(),
                            "object_id": obj.object_id,
                        }
                    )
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return json.dumps({"events": events[:limit], "total": len(events)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# bio_inspect_dataset —— 沙箱数据集登记查看（A/B，ADR-11）
# ---------------------------------------------------------------------------


@tool_handler
def inspect_dataset(args: dict[str, Any], **kwargs: Any) -> str:
    """列出/查看已登记的可沙箱访问数据集（零拷贝，SHA256 证据链）。"""
    dataset_id = str(args.get("dataset_id", "")).strip()
    verify = bool(args.get("verify", False))
    db_path = _GOM_DB
    if not db_path.is_file():
        return json.dumps(
            {"count": 0, "datasets": [], "note": "尚无登记数据集"}, ensure_ascii=False
        )

    from bacmap.store.datasets import DatasetRegistry

    with DatasetRegistry(db_path) as reg:
        if dataset_id:
            ds = reg.get(dataset_id)
            if ds is None:
                return json.dumps(
                    {"error": f"unknown dataset: {dataset_id}"}, ensure_ascii=False
                )
            if verify:
                reg.verify(dataset_id)
                ds = reg.get(dataset_id)
                assert ds is not None
            return json.dumps(
                {
                    "dataset_id": ds.dataset_id,
                    "kind": ds.kind,
                    "source_path": ds.source_path,
                    "resolved_path": ds.resolved_path,
                    "total_size": ds.total_size,
                    "manifest_sha256": ds.manifest_sha256,
                    "status": ds.status,
                    "mount": ds.mount_guest,
                    "data_class": ds.data_class,
                    "registered_by": ds.registered_by,
                    "registered_at": ds.registered_at,
                    "n_entries": len(ds.entries),
                    "entries": ds.entries[:200],
                },
                ensure_ascii=False,
            )

        items = [
            {
                "dataset_id": d.dataset_id,
                "kind": d.kind,
                "total_size": d.total_size,
                "status": d.status,
                "source_path": d.source_path,
                "mount": d.mount_guest,
            }
            for d in reg.list_all()
        ]
    return json.dumps({"count": len(items), "datasets": items}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# bio_list_reference_genomes —— 参考基因组清单与供给状态（智能体 skill 支撑）
# ---------------------------------------------------------------------------

_REFERENCE_MANIFEST = "reference_accessions.yaml"


def _reference_manifest_path() -> Path:
    """部署副本优先（站点可改），缺省回退包内模板。"""
    deployed = _DEPLOYED_WORKFLOWS_DIR / "config" / _REFERENCE_MANIFEST
    if deployed.is_file():
        return deployed
    return Path(__file__).resolve().parents[1] / "workflow" / "config" / _REFERENCE_MANIFEST


@tool_handler
def list_reference_genomes(args: dict[str, Any], **kwargs: Any) -> str:
    """列出参考基因组清单与供给状态（供智能体判断 SNP cohort 就绪度）。"""
    import yaml

    wanted = str(args.get("group", "")).strip()
    manifest_path = _reference_manifest_path()
    genomes_dir = _DATA_DIR / "reference" / "genomes"
    if not manifest_path.is_file():
        return json.dumps(
            {"error": f"reference manifest not found: {manifest_path}"}, ensure_ascii=False
        )
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as exc:
        return json.dumps({"error": f"manifest parse failed: {exc}"}, ensure_ascii=False)

    registered: dict[str, dict[str, Any]] = {}
    refs_manifest = _REFS_DIR / "manifest.json"
    if refs_manifest.is_file():
        try:
            payload = json.loads(refs_manifest.read_text(encoding="utf-8"))
            for entry in payload.get("databases") or []:
                if isinstance(entry, dict) and str(entry.get("name", "")).startswith("ref:"):
                    registered[str(entry["name"])] = entry
        except (OSError, ValueError):
            pass

    genomes: list[dict[str, Any]] = []
    for group, spec in (manifest.get("genomes") or {}).items():
        if wanted and group != wanted:
            continue
        out_path = genomes_dir / str(spec.get("out", ""))
        rec = registered.get(f"ref:{group}", {})
        genomes.append(
            {
                "group": group,
                "out": str(out_path),
                "organism": spec.get("organism", ""),
                "accessions": [str(a) for a in (spec.get("accessions") or [])],
                "version": spec.get("version", ""),
                "present": out_path.is_file(),
                "registered": bool(rec),
                "registered_checksum": rec.get("checksum", ""),
            }
        )
    fetch_command = (
        "python workflows/bacmap/scripts/fetch_reference_genomes.py "
        f"--manifest {manifest_path} --out-dir {genomes_dir} --refs-dir {_REFS_DIR}"
    )
    return json.dumps(
        {
            "manifest": str(manifest_path),
            "genomes_dir": str(genomes_dir),
            "n_total": len(genomes),
            "n_present": sum(1 for g in genomes if g["present"]),
            "genomes": genomes,
            "fetch_command": fetch_command,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# bio_compare_runs —— 运行比较（ADR-18）
# ---------------------------------------------------------------------------


def _diff_mapping(a: Any, b: Any, prefix: str = "") -> list[dict[str, Any]]:
    """递归逐字段比较两个映射（summary 结构），返回差异列表。"""
    out: list[dict[str, Any]] = []
    if not isinstance(a, dict) or not isinstance(b, dict):
        return out
    for key in sorted(set(a) | set(b)):
        va, vb = a.get(key), b.get(key)
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(va, dict) and isinstance(vb, dict):
            out.extend(_diff_mapping(va, vb, path))
        elif va != vb:
            out.append({"path": path, "a": va, "b": vb})
    return out


def _gom_summary_for_run(sample_id: str, run_id: str) -> dict[str, Any] | None:
    """从 GOM 取某样本某次运行的 summary（ANALYSIS 对象 payload:{summary,run_id}）。"""
    from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

    if not _GOM_DB.is_file():
        return None
    with GenomeObjectService(_GOM_DB) as gos:
        for obj in gos.list_by_type(ObjectType.ANALYSIS, limit=1000):
            if obj.strain_id != sample_id:
                continue
            payload = obj.payload or {}
            if payload.get("run_id") == run_id:
                summary = payload.get("summary")
                return summary if isinstance(summary, dict) else None
    return None


@tool_handler
def compare_runs(args: dict[str, Any], **kwargs: Any) -> str:
    """比较同一样本的两次运行（ADR-18）：来源逐字段归因 + 结果比对。

    若来源（参数/数据库/工具/输入/工作流）全部相同而结果不同 → NOT_REPRODUCIBLE；
    否则把差异归因到变化的类别；结果一致 → IDENTICAL。
    """
    from bacmap.store import runs as runs_store

    sample_id = str(args.get("sample_id", ""))
    run_a = str(args.get("run_a", ""))
    run_b = str(args.get("run_b", ""))
    if not (sample_id and run_a and run_b):
        return json.dumps({"error": "sample_id、run_a、run_b 均为必填"}, ensure_ascii=False)
    if not _validate_sample_id(sample_id):
        return json.dumps({"error": f"invalid sample_id: {sample_id!r}"})

    rec_a = runs_store.read_run(run_a, _RUNS_DB)
    rec_b = runs_store.read_run(run_b, _RUNS_DB)
    missing = [r for r, rec in ((run_a, rec_a), (run_b, rec_b)) if rec is None]
    if missing:
        return json.dumps({"error": f"run not found: {missing}"}, ensure_ascii=False)
    assert rec_a is not None and rec_b is not None

    provenance = runs_store.compare_runs(rec_a, rec_b)
    summary_a = _gom_summary_for_run(sample_id, run_a)
    summary_b = _gom_summary_for_run(sample_id, run_b)
    result_diffs = _diff_mapping(summary_a or {}, summary_b or {})
    same_results = not result_diffs

    if provenance["same_provenance"] and same_results:
        verdict = "IDENTICAL"
    elif provenance["same_provenance"]:
        verdict = "NOT_REPRODUCIBLE"
    else:
        verdict = "DIFF_ATTRIBUTED"

    return json.dumps(
        {
            "sample_id": sample_id,
            "run_a": run_a,
            "run_b": run_b,
            "verdict": verdict,
            "same_provenance": provenance["same_provenance"],
            "changed_categories": provenance["changed_categories"],
            "provenance_diffs": provenance["diffs"],
            "result_change_count": len(result_diffs),
            "result_diffs": result_diffs[:100],
            "summary_a_found": summary_a is not None,
            "summary_b_found": summary_b is not None,
        },
        ensure_ascii=False,
    )
