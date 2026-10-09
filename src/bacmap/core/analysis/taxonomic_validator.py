from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bacmap.config import CHECKM2_DB, GTDB_DB, pixi_path

logger = logging.getLogger(__name__)


@dataclass
class TaxonomyResult:
    mode: str = "simple"
    marker_gene_species: str = ""
    marker_gene_confidence: str = ""
    marker_gene_markers: list[dict[str, Any]] = field(default_factory=list)
    completeness: float | None = None
    contamination: float | None = None
    gtdb_taxonomy: str = ""
    gtdb_note: str = ""
    interpretation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "marker_gene_species": self.marker_gene_species,
            "marker_gene_confidence": self.marker_gene_confidence,
            "marker_gene_markers": self.marker_gene_markers,
            "completeness": self.completeness,
            "contamination": self.contamination,
            "gtdb_taxonomy": self.gtdb_taxonomy,
            "gtdb_note": self.gtdb_note,
            "interpretation": self.interpretation,
        }

    @property
    def summary(self) -> str:
        parts = [f"Mode: {self.mode}"]
        if self.marker_gene_species:
            parts.append(f"Marker gene: {self.marker_gene_species}")
        if self.completeness is not None:
            parts.append(f"Completeness: {self.completeness:.1f}%")
        if self.contamination is not None:
            parts.append(f"Contamination: {self.contamination:.1f}%")
        if self.gtdb_taxonomy:
            parts.append(f"GTDB-Tk: {self.gtdb_taxonomy}")
        return " | ".join(parts)


def _run_checkm2(contigs_path: str, output_dir: Path) -> tuple[float | None, float | None]:
    if not CHECKM2_DB:
        logger.warning("CheckM2 database not configured (set CHECKM2DB env var)")
        return None, None
    checkm2 = _find_tool("checkm2")
    if not checkm2:
        logger.warning("checkm2 not found in PATH")
        return None, None

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        checkm2,
        "predict",
        "--input",
        contigs_path,
        "--output",
        str(output_dir / "checkm2_results.tsv"),
        "--database_path",
        str(CHECKM2_DB),
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env={**__import__("os").environ, "PATH": pixi_path()},
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("CheckM2 failed: %s", e)
        return None, None

    tsv_path = output_dir / "checkm2_results.tsv"
    if not tsv_path.exists():
        return None, None

    lines = tsv_path.read_text().strip().split("\n")
    if len(lines) < 2:
        return None, None
    header = lines[0].split("\t")
    data = lines[1].split("\t")
    row = dict(zip(header, data))

    try:
        completeness = float(row.get("Completeness", 0))
    except (ValueError, TypeError):
        completeness = None
    try:
        contamination = float(row.get("Contamination", 0))
    except (ValueError, TypeError):
        contamination = None
    return completeness, contamination


def _run_gtdbtk(contigs_path: str, output_dir: Path) -> str:
    if not GTDB_DB:
        logger.warning("GTDB-Tk database not configured (set GTDBDB env var)")
        return ""
    gtdbtk = _find_tool("gtdbtk")
    if not gtdbtk:
        logger.warning("gtdbtk not found in PATH")
        return ""

    genome_dir = output_dir / "gtdb_genomes"
    genome_dir.mkdir(parents=True, exist_ok=True)
    genome_file = genome_dir / "query.fasta"
    genome_file.write_text(Path(contigs_path).read_text())

    cmd = [
        gtdbtk,
        "classify_wf",
        "--genome_dir",
        str(genome_dir),
        "--out_dir",
        str(output_dir / "gtdb_output"),
        "--database",
        str(GTDB_DB),
        "--cpus",
        "4",
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            env={**__import__("os").environ, "PATH": pixi_path()},
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("GTDB-Tk failed: %s", e)
        return ""

    summary = output_dir / "gtdb_output" / "gtdbtk.bac120.summary.tsv"
    if not summary.exists():
        summary = output_dir / "gtdb_output" / "gtdbtk.ar122.summary.tsv"
    if not summary.exists():
        return ""

    lines = summary.read_text().strip().split("\n")
    if len(lines) < 2:
        return ""
    header = lines[0].split("\t")
    data = lines[1].split("\t")
    row = dict(zip(header, data))
    return row.get("classification", "")


def _find_tool(name: str) -> str | None:
    import shutil

    return shutil.which(name, path=pixi_path())


def validate_genome(
    contigs_path: str | Path,
    mode: str = "simple",
    output_dir: str | Path | None = None,
) -> TaxonomyResult:
    contigs_path = str(contigs_path)
    if output_dir is None:
        output_dir = Path(contigs_path).parent.parent / "taxonomy"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from bacmap.core.analysis.species_identifier import identify

    marker_result = identify(contigs_path)
    result = TaxonomyResult(
        mode=mode,
        marker_gene_species=marker_result.species,
        marker_gene_confidence=marker_result.confidence,
        marker_gene_markers=marker_result.detected_markers,
    )

    if mode == "standard":
        result.completeness, result.contamination = _run_checkm2(contigs_path, output_dir)
        result.gtdb_taxonomy = _run_gtdbtk(contigs_path, output_dir)
        result.interpretation = _build_interpretation(result)
    else:
        result.interpretation = (
            f"Marker gene: {marker_result.species} (confidence: {marker_result.confidence})"
        )

    (output_dir / "validation.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    )
    return result


def _build_interpretation(result: TaxonomyResult) -> str:
    parts: list[str] = []

    if result.completeness is not None and result.contamination is not None:
        if result.completeness >= 90 and result.contamination <= 5:
            parts.append("Genome quality: PASS")
        elif result.completeness < 50:
            parts.append("Genome quality: WARNING (low completeness)")
        else:
            parts.append(
                f"Genome quality: CHECK (completeness={result.completeness:.1f}%,"
                f" contamination={result.contamination:.1f}%)"
            )

    if result.gtdb_taxonomy:
        parts.append(f"GTDB-Tk classification: {result.gtdb_taxonomy}")
        if result.marker_gene_species:
            marker_lower = result.marker_gene_species.lower()
            gtdb_lower = result.gtdb_taxonomy.lower()
            if marker_lower in gtdb_lower or any(m in gtdb_lower for m in marker_lower.split("/")):
                parts.append("Consistency: marker gene and GTDB-Tk agree")
            else:
                parts.append(
                    f"Consistency: DISCREPANCY (marker={result.marker_gene_species},"
                    f" GTDB={result.gtdb_taxonomy})"
                )

    if not parts:
        return "Standard mode requested but CheckM2/GTDB-Tk databases not available"

    return "; ".join(parts)
