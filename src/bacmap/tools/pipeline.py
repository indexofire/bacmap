"""High-level analysis pipeline tool handlers (project.md §7).

Covers bio_analyze_pathogen, bio_get_result, bio_verify_result,
bio_generate_report, bio_list_samples, bio_gene_scan,
bio_validate_taxonomy, bio_annotate, bio_diagnose. All handlers return JSON
strings. Errors are {"error": "..."}.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from bacmap.config import DEPLOYED_WORKFLOWS_DIR as _DEPLOYED_WORKFLOWS_DIR
from bacmap.config import GOM_DB as _REFLECTION_DB_PATH
from bacmap.core.utils import parse_mlst

from ._common import (
    _RESULTS_DIR,
    _run_project_script,
    _validate_sample_id,
    logger,
    tool_handler,
)


def _script_error(stdout: str) -> str | None:
    """从 `_run_project_script` 输出提取错误信封（避免诊断信息被吞）。"""
    try:
        obj = json.loads(stdout)
    except (TypeError, ValueError):
        return None
    if isinstance(obj, dict) and obj.get("error"):
        detail = str(obj["error"])
        if obj.get("stderr"):
            detail += " | " + str(obj["stderr"])[:300]
        return detail
    return None


@tool_handler
def analyze_pathogen(args: dict[str, Any], **kwargs: Any) -> str:
    """Trigger full analysis pipeline via Snakemake.
    Works for Salmonella, DEC, Shigella, EIEC — species routing is automatic
    via three-gene identification (invA/uidA/ipaH)."""
    sample_id = args.get("sample_id", "")
    cores = args.get("cores", 8)

    if not _validate_sample_id(sample_id):
        return json.dumps({"error": f"invalid sample_id: {sample_id!r}"})

    script_out = _run_project_script(
        "run_analysis.py", ["--sample", sample_id, "--cores", str(cores)]
    )

    summary_path = _RESULTS_DIR / sample_id / "report" / f"{sample_id}_summary.json"
    if summary_path.exists():
        with summary_path.open() as f:
            return str(f.read())
    detail = _script_error(script_out)
    if detail:
        return json.dumps({"error": "Pipeline failed", "detail": detail}, ensure_ascii=False)
    return json.dumps({"error": "Pipeline completed but summary not found"})


@tool_handler
def get_result(args: dict[str, Any], **kwargs: Any) -> str:
    """Retrieve analysis summary for a completed sample."""
    sample_id = args.get("sample_id", "")
    if not _validate_sample_id(sample_id):
        return json.dumps({"error": f"invalid sample_id: {sample_id!r}"})

    summary_path = _RESULTS_DIR / sample_id / "report" / f"{sample_id}_summary.json"
    if not summary_path.exists():
        return json.dumps(
            {"error": f"No results found for {sample_id}. Run bio_analyze_pathogen first."}
        )

    with summary_path.open() as f:
        summary = json.load(f)

    steps = summary.get("steps", {})

    sp = steps.get("species", {})
    # 真实 summary 存 steps.species.species（species.smk/gside 输出）；旧 fixtures 用 verdict。
    if isinstance(sp, dict):
        verdict = str(sp.get("verdict") or sp.get("species") or "N/A")
    else:
        verdict = str(sp) if sp else "N/A"

    mlst_raw = steps.get("mlst", "")
    st = parse_mlst(mlst_raw)["st"] if isinstance(mlst_raw, str) and mlst_raw else "N/A"

    sero = steps.get("serotype", {})
    serovar = sero.get("sistr", "N/A") if isinstance(sero, dict) else "N/A"

    amr = steps.get("amr", {})
    card = amr.get("abricate_card", []) if isinstance(amr, dict) else []
    vfdb = amr.get("abricate_vfdb", []) if isinstance(amr, dict) else []
    plas = steps.get("plasmid", {})
    pl = plas.get("plasmidfinder", []) if isinstance(plas, dict) else []

    dec = steps.get("dec", {}) if isinstance(steps.get("dec", {}), dict) else {}
    ipah = dec.get("ipaH", "N/A")
    pathotype = dec.get("pathotype", "N/A")

    # 物种归类：四病原沿用既有短标签；gside 常见病原（Genus_species）用规范名。
    from bacmap.core.analysis.species_canon import UNKNOWN as _SPECIES_UNKNOWN
    from bacmap.core.analysis.species_canon import canonical_from_verdict as _canon

    canon = _canon(verdict, str(ipah))
    if canon == "Salmonella":
        species_type = "Salmonella"
    elif canon == "Shigella" or "positive" in str(ipah):
        species_type = "Shigella/EIEC"
    elif canon == "E. coli":
        species_type = "E. coli/DEC"
    elif canon != _SPECIES_UNKNOWN:
        species_type = canon
    else:
        species_type = "unknown"

    pt_line = "N/A"
    if pathotype and pathotype != "N/A":
        # 新契约（gapit typing 归一）：pathotype 已是干净字符串（如 EHEC）；
        # 兼容旧 summary 的多行 TSV：取最后一行第一列。
        pt_line = pathotype.strip().splitlines()[-1].split("\t")[0]

    compact = {
        "sample_id": sample_id,
        "species_type": species_type,
        "species_verdict": verdict,
        "mlst_st": st,
        "serotype": serovar,
        "ipaH": ipah,
        "pathotype": pt_line,
        "amr_genes_count": len(card),
        "virulence_genes_count": len(vfdb),
        "plasmid_count": len(pl),
        "report_path": str(summary_path),
    }
    return json.dumps(compact, ensure_ascii=False)


@tool_handler
def verify_result(args: dict[str, Any], **kwargs: Any) -> str:
    """Run Deterministic Verifier (Layer 2) on a sample's results.

    With ``interpretation_text`` also runs the NLI Reflector (Layer 3):
    atomic claims from the text are compared against the sample's
    Source-of-Truth facts; contradiction rate above threshold flags
    NEEDS_HUMAN_REVIEW (project.md §8.2)."""
    sample_id = args.get("sample_id", "")
    interpretation_text = str(args.get("interpretation_text") or "")
    if not _validate_sample_id(sample_id):
        return json.dumps({"error": f"invalid sample_id: {sample_id!r}"})

    summary_path = _RESULTS_DIR / sample_id / "report" / f"{sample_id}_summary.json"
    if not summary_path.exists():
        return json.dumps({"error": f"No results for {sample_id}"})

    with summary_path.open() as f:
        summary = json.load(f)

    try:
        from bacmap.core.verify.deterministic_verifier import DeterministicVerifier

        v = DeterministicVerifier()
        result = v.verify_all(summary)
        response: dict[str, Any] = {
            "passed": result.passed,
            "failed_count": result.failed_count,
            "needs_human_review": result.needs_human_review,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message} for c in result.checks
            ],
        }
        if interpretation_text:
            from bacmap.core.verify.nli_reflector import (
                extract_facts,
                record_reflection_event,
                reflect,
            )

            facts = extract_facts(summary, sample_id)
            reflection = reflect(interpretation_text, facts)
            response["layer3"] = {
                "verifiable_count": reflection.verifiable_count,
                "contradicted_count": reflection.contradicted_count,
                "contradiction_rate": reflection.contradiction_rate,
                "needs_human_review": reflection.needs_human_review,
                "corroborated_count": reflection.corroborated_count,
                "threshold": reflection.threshold,
                "verdicts": [
                    {
                        "claim_type": str(cv.claim.claim_type),
                        "value": cv.claim.value,
                        "verdict": str(cv.verdict),
                        "evidence": cv.evidence,
                    }
                    for cv in reflection.verdicts
                ],
            }
            if reflection.needs_human_review:
                record_reflection_event(_REFLECTION_DB_PATH, sample_id, reflection)
        return json.dumps(response, ensure_ascii=False)
    except Exception as e:
        logger.exception("verify_result failed")
        return json.dumps({"error": f"Verifier failed: {e}"})


@tool_handler
def generate_report(args: dict[str, Any], **kwargs: Any) -> str:
    """Generate HTML report for a sample."""
    sample_id = args.get("sample_id", "")
    if not _validate_sample_id(sample_id):
        return json.dumps({"error": f"invalid sample_id: {sample_id!r}"})
    # 内部调用（run 级隔离）可指定本次运行的物理结果目录；MCP/工具面不暴露该参数。
    results_dir = Path(args["results_dir"]) if args.get("results_dir") else _RESULTS_DIR
    script_args = ["--sample", sample_id]
    if results_dir != _RESULTS_DIR:
        script_args += ["--results-dir", str(results_dir)]
    script_out = _run_project_script("generate_report.py", script_args, timeout=60)
    report_path = results_dir / sample_id / "report" / f"{sample_id}_report.html"
    if report_path.exists():
        return json.dumps({"sample_id": sample_id, "report_path": str(report_path)})
    detail = _script_error(script_out)
    if detail:
        return json.dumps(
            {"error": "Report generation failed", "detail": detail}, ensure_ascii=False
        )
    return json.dumps({"error": "Report generation failed"})


@tool_handler
def list_samples(args: dict[str, Any], **kwargs: Any) -> str:
    """List all samples and their analysis status."""
    import csv

    samples_tsv = _DEPLOYED_WORKFLOWS_DIR / "config" / "samples.tsv"
    if not samples_tsv.exists():
        return json.dumps({"error": "samples.tsv not found"})

    status_list = []
    with samples_tsv.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            sid = r["sample"]
            summary = _RESULTS_DIR / sid / "report" / f"{sid}_summary.json"
            contigs = _RESULTS_DIR / sid / "assembly" / "contigs.fasta"

            if summary.exists():
                status = "completed"
            elif contigs.exists():
                status = "in-progress"
            else:
                status = "not-started"

            status_list.append(
                {"sample_id": sid, "species": r.get("species", ""), "status": status}
            )

    return json.dumps({"samples": status_list}, ensure_ascii=False)



@tool_handler
def gene_scan(args: dict[str, Any], **kwargs: Any) -> str:
    """Scan contigs against gene database(s) via gapit (ADR-20). Returns JSON."""

    contigs_path = args.get("contigs_path", "")
    database = args.get("database", "card")
    min_identity = args.get("min_identity", 80.0)
    min_coverage = args.get("min_coverage", 80.0)

    contigs = Path(contigs_path)
    if not contigs.exists():
        return json.dumps({"error": f"Contigs not found: {contigs_path}"})

    columns = [
        "file", "sequence", "start", "end", "strand", "gene", "coverage",
        "coverage_map", "gaps", "pct_coverage", "pct_identity", "database",
        "accession", "product", "resistance",
    ]

    def run_one(db: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["gapit", "screen", str(contigs), "--db", db,
                 "--minid", str(min_identity), "--mincov", str(min_coverage)],
                capture_output=True, text=True, timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"database": db, "error": f"gapit unavailable: {exc}", "hits": [], "n_hits": 0}
        if proc.returncode != 0:
            return {"database": db, "error": proc.stderr[-500:], "hits": [], "n_hits": 0}
        hits = []
        for line in proc.stdout.splitlines():
            if line.startswith("#"):
                continue
            fields = line.split("	")
            if len(fields) >= 6:
                hits.append(dict(zip(columns, fields, strict=False)))  # 行超长时截断多余列
        return {"tool": "gapit", "database": db, "hits": hits, "n_hits": len(hits)}

    db_list = [d.strip() for d in database.split(",")]
    results = [run_one(d) for d in db_list]
    payload = results[0] if len(results) == 1 else {"tool": "gapit", "results": results}
    return json.dumps(payload, ensure_ascii=False)


@tool_handler





@tool_handler
def diagnose_failure(args: dict[str, Any], **kwargs: Any) -> str:
    """Diagnose pipeline failure from Snakemake log or stderr text."""
    from bacmap.core.analysis.failure_diagnostics import diagnose, diagnose_from_log

    stderr_text = args.get("stderr_text", "")
    log_path = args.get("log_path", "")

    if stderr_text:
        result = diagnose(stderr_text)
    elif log_path:
        result = diagnose_from_log(log_path)
    else:
        result = diagnose_from_log(str(_DEPLOYED_WORKFLOWS_DIR / ".snakemake" / "log"))

    return json.dumps(result.to_dict(), ensure_ascii=False)
