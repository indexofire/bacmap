"""Tool handlers — the code that runs when the LLM calls each tool.

Design principles:
  - Python-only tools (seq_stats, seq_ops, fastq_qc, seq_convert) use Biopython
    and degrade gracefully if Biopython is not installed (lazy install).
  - External-CLI tools (blast, align, samtools, variant) detect the binary at
    call time and return a clear error JSON if missing — never raise.
  - All handlers return JSON strings. Errors are {"error": "..."}.

Handlers live in submodules by group (seq, cli, pipeline, services) and are
re-exported here so `from ..tools import <handler>` keeps working.
"""

from .cli import align, blast, samtools_op, variant
from .pipeline import (
    analyze_pathogen,
    diagnose_failure,
    gene_scan,
    generate_report,
    get_result,
    list_samples,
    verify_result,
)
from .seq import fastq_qc, seq_convert, seq_ops, seq_stats
from .services import (
    add_lab_result,
    add_metadata,
    cgmlst_traceback,
    query_lab_results,
    query_metadata,
    search_samples,
    snp_tree,
)

__all__ = [
    "add_lab_result",
    "add_metadata",
    "align",
    "analyze_pathogen",
    "blast",
    "cgmlst_traceback",
    "diagnose_failure",
    "fastq_qc",
    "gene_scan",
    "generate_report",
    "get_result",
    "list_samples",
    "query_lab_results",
    "query_metadata",
    "samtools_op",
    "search_samples",
    "seq_convert",
    "seq_ops",
    "seq_stats",
    "snp_tree",
    "variant",
    "verify_result",
]
