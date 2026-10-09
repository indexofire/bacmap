"""Species identifier — unified pathogen identification from contigs.

Single BLAST scan against species_markers database (invA/uidA/ipaH/toxR/tlh).
Replaces 4 separate Snakemake rules (species_blastn_inva, dec_ipaH_blast,
vpara_targets). Extensible: add new genes to species_markers.fasta to support
new pathogens without changing code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bacmap.config import REF_DIR
from bacmap.core.analysis.gene_scanner import scan
from bacmap.core.pathogen_registry import load_registry

_SPECIES_MIN_IDENTITY = 85.0
_SPECIES_MIN_COVERAGE = 30.0
_HIGH_CONF_IDENTITY = 90.0

# Markers with documented near-relative homologs: a sub-90% single hit is a
# cross-reaction (e.g. V. alginolyticus tlh vs V. parahaemolyticus, 85.2% —
# see docs/cases/species-crossreaction.md) and must not call the species.
_SINGLE_HIT_GUARD_MARKERS = frozenset({"tlh"})

_gene_map, _priority = load_registry().species_markers()
_GENE_TO_SPECIES: dict[str, tuple[str, str]] = _gene_map
_SPECIES_PRIORITY: list[str] = _priority

_MARKERS_FASTA = REF_DIR / "species" / "markers.fasta"


def _markers_db_version() -> str:
    try:
        return hashlib.sha256(_MARKERS_FASTA.read_bytes()).hexdigest()[:8]
    except OSError:
        return "unknown"


@dataclass
class SpeciesIdResult:
    species: str = "Unknown"
    confidence: str = "low"
    detected_markers: list[dict[str, Any]] = field(default_factory=list)
    all_hits: list[dict[str, Any]] = field(default_factory=list)
    method: str = "marker"
    database_version: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "species": self.species,
            "confidence": self.confidence,
            "method": self.method,
            "database": {"name": "species_markers", "version": self.database_version},
            "detected_markers": self.detected_markers,
            "notes": self.notes,
            "interpretation": self._interpret(),
        }

    def _interpret(self) -> str:
        if self.species == "Unknown":
            return "No species-specific markers detected"
        markers = [m["gene"] for m in self.detected_markers]
        return f"Identified as {self.species} based on: {', '.join(markers)}"


def identify(contigs_fasta: str | Path, mode: str = "simple") -> SpeciesIdResult:
    if mode != "simple":
        raise ValueError(
            f"identify() only supports mode='simple', got {mode!r}. "
            "Use analysis.taxonomic_validator.validate_genome for full taxonomy validation."
        )

    scan_result = scan(
        contigs_fasta,
        db_name="species_markers",
        min_identity=_SPECIES_MIN_IDENTITY,
        min_coverage=_SPECIES_MIN_COVERAGE,
    )

    result = SpeciesIdResult(database_version=_markers_db_version())

    gene_hits: dict[str, dict[str, Any]] = {}
    for hit in scan_result.genes:
        gene_lower = hit.gene.lower()
        if gene_lower in _GENE_TO_SPECIES:
            if gene_lower not in gene_hits or hit.identity > gene_hits[gene_lower]["identity"]:
                gene_hits[gene_lower] = {
                    "gene": hit.gene,
                    "identity": hit.identity,
                    "coverage": hit.coverage,
                    "contig": hit.contig,
                }
        result.all_hits.append(
            {
                "gene": hit.gene,
                "identity": hit.identity,
                "coverage": hit.coverage,
            }
        )

    result.detected_markers = [gene_hits[g] for g in _SPECIES_PRIORITY if g in gene_hits]

    if not gene_hits:
        return result

    for gene in _SPECIES_PRIORITY:
        if gene not in gene_hits:
            continue
        species, _ = _GENE_TO_SPECIES[gene]
        identity = gene_hits[gene]["identity"]
        if gene in _SINGLE_HIT_GUARD_MARKERS and identity < _HIGH_CONF_IDENTITY:
            result.notes.append(
                f"{gene} single hit at {identity:.1f}% identity (below "
                f"{_HIGH_CONF_IDENTITY:.0f}%): near-relative homolog suspected "
                "(e.g. Vibrio alginolyticus tlh); species call withheld, "
                "ANI recheck advised"
            )
            break
        result.species = species
        result.confidence = "high" if identity >= _HIGH_CONF_IDENTITY else "medium"
        if result.confidence == "medium":
            result.notes.append(
                f"{gene} hit at {identity:.1f}% identity (85-90% band): "
                "confidence downgraded, ANI recheck advised"
            )
        break

    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Species identifier")
    parser.add_argument("contigs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = identify(args.contigs)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        d = result.to_dict()
        print(f"Species: {d['species']} ({d['confidence']})")
        for m in d["detected_markers"]:
            print(f"  {m['gene']}: {m['identity']}% identity, {m['coverage']}% coverage")
        print(d["interpretation"])


if __name__ == "__main__":
    main()
