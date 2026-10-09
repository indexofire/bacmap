from __future__ import annotations

from collections.abc import Sequence

from .hits import Hit


def merge_intervals(hits: Sequence[Hit], subject_length: int = 0) -> tuple[float, float]:
    """Merge subject intervals across multiple HSPs for one subject.

    Returns (merged_coverage_pct, length_weighted_identity).
    """
    if not hits:
        return 0.0, 0.0

    if subject_length <= 0:
        subject_length = max(max(h.subject_start, h.subject_end) for h in hits)
    if subject_length <= 0:
        return 0.0, 0.0

    intervals: list[tuple[int, int]] = []
    total_aln = 0.0
    id_sum = 0.0
    for h in hits:
        s, e = h.subject_start, h.subject_end
        if s > e:
            s, e = e, s
        if s > 0 and e > 0:
            intervals.append((s, e))
        aln = float(h.alignment_length)
        total_aln += aln
        id_sum += h.identity * aln

    if not intervals:
        return 0.0, 0.0

    intervals.sort()
    merged: list[tuple[int, int]] = []
    for s, e in intervals:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    covered = sum(e - s + 1 for s, e in merged)
    coverage = min((covered / subject_length) * 100.0, 100.0)
    avg_id = (id_sum / total_aln) if total_aln > 0 else 0.0
    return round(coverage, 2), round(avg_id, 2)


def confidence_tier(coverage: float, identity: float) -> str:
    """6-tier quality scoring: perfect/very_high/high/good/low/none."""
    if coverage >= 99.0 and identity >= 99.0:
        return "perfect"
    if coverage >= 99.0 and identity >= 95.0:
        return "very_high"
    if coverage >= 95.0 and identity >= 90.0:
        return "high"
    if coverage >= 90.0 and identity >= 85.0:
        return "good"
    if coverage >= 80.0 and identity >= 80.0:
        return "low"
    return "none"


def classify_allele(
    identity: float,
    coverage: float,
    min_identity: float = 95.0,
    min_coverage: float = 98.0,
) -> tuple[str, int]:
    """4-tier allele classification: (label, score).

    Returns ("exact", 90) / ("novel", 63) / ("partial", 18) / ("missing", 0).
    """
    if identity >= 99.99 and coverage >= 99.9 and min_identity <= 99.99:
        return "exact", 90
    if coverage >= min_coverage and identity >= min_identity:
        return "novel", 63
    if coverage >= 50.0 and identity >= min_identity:
        return "partial", 18
    return "missing", 0
