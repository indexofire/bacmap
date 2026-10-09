"""Engine — unified sequence operations abstraction layer.

Decouples pipeline logic from specific CLI tools (blastn, minimap2, bwa).

Usage:

        query="contigs.fasta",
        db_prefix="data/reference/amr/card",
        mode="blastn",
    )
"""

from __future__ import annotations

from .backends import available
from .hits import Hit
from .read_mapper import ReadMapper
from .utils import classify_allele, confidence_tier, merge_intervals

__all__ = [
    "Hit",
    "ReadMapper",
    "available",
    "merge_intervals",
    "confidence_tier",
    "classify_allele",
]


