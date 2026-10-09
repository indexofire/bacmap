"""Tests for engine/utils.py — merge_intervals, confidence_tier, classify_allele, Hit.to_dict."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.engine.hits import Hit  # noqa: E402
from bacmap.core.engine.utils import (  # noqa: E402
    classify_allele,
    merge_intervals,
)


class TestMergeIntervals:
    def test_single_hit(self):
        h = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=10,
            subject_end=109,
            alignment_length=100,
        )
        cov, ident = merge_intervals([h], subject_length=1000)
        assert cov == 10.0
        assert ident == 99.0

    def test_overlapping_hits(self):
        h1 = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=1,
            subject_end=100,
            alignment_length=100,
        )
        h2 = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=50,
            subject_end=150,
            alignment_length=101,
        )
        cov, _ = merge_intervals([h1, h2], subject_length=1000)
        assert cov == 15.0

    def test_adjacent_hits_no_gap(self):
        h1 = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=1,
            subject_end=100,
            alignment_length=100,
        )
        h2 = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=101,
            subject_end=200,
            alignment_length=100,
        )
        cov, _ = merge_intervals([h1, h2], subject_length=1000)
        assert cov == 20.0

    def test_empty_hits(self):
        cov, ident = merge_intervals([], subject_length=1000)
        assert cov == 0.0
        assert ident == 0.0

    def test_coverage_capped_at_100(self):
        h = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=1,
            subject_end=100,
            alignment_length=100,
        )
        cov, _ = merge_intervals([h], subject_length=50)
        assert cov == 100.0


class TestMergeIntervalsReverseStrand:
    def test_reverse_strand_coverage(self):
        h = Hit(
            query_id="q",
            subject_id="s",
            identity=99.0,
            subject_start=500,
            subject_end=100,
            alignment_length=401,
        )
        cov, _ = merge_intervals([h], subject_length=0)
        assert cov > 0


class TestClassifyAllele:
    def test_exact(self):
        label, score = classify_allele(100.0, 100.0)
        assert label == "exact"
        assert score == 90

    def test_novel(self):
        label, score = classify_allele(98.0, 99.0, min_identity=95.0, min_coverage=98.0)
        assert label == "novel"
        assert score == 63

    def test_exact_respects_custom_min_identity(self):
        label, _ = classify_allele(99.99, 100.0, min_identity=100.0)
        assert label != "exact"

    def test_partial(self):
        label, score = classify_allele(96.0, 60.0, min_identity=95.0)
        assert label == "partial"
        assert score == 18

    def test_missing(self):
        label, score = classify_allele(80.0, 30.0)
        assert label == "missing"
        assert score == 0


class TestHitToDict:
    def test_preserves_zero_values(self):
        h = Hit(query_id="q", subject_id="s", identity=0.0, bit_score=0.0, alignment_length=0)
        d = h.to_dict()
        assert d["identity"] == 0.0
        assert d["bit_score"] == 0.0
        assert d["alignment_length"] == 0

    def test_preserves_empty_strings(self):
        h = Hit(query_id="q", subject_id="s", identity=99.0, strand="", backend="")
        d = h.to_dict()
        assert "strand" in d
        assert d["strand"] == ""
        assert "backend" in d
        assert d["backend"] == ""

    def test_preserves_all_fields(self):
        h = Hit(query_id="q", subject_id="s", identity=99.5)
        d = h.to_dict()
        expected_keys = {
            "query_id",
            "subject_id",
            "identity",
            "query_coverage",
            "subject_coverage",
            "evalue",
            "bit_score",
            "query_start",
            "query_end",
            "subject_start",
            "subject_end",
            "strand",
            "alignment_length",
            "mismatches",
            "mapq",
            "backend",
        }
        assert set(d.keys()) == expected_keys
