"""Unit tests for engine/utils.py + hits.py parser edge cases.

Extends tests/unit/test_engine.py with:
- Hit.from_blast_line edge cases (reverse strand, zero-coverage, malformed)
- Hit.from_paf_line edge cases (NM tag, malformed tags, comment lines)
- merge_intervals (subject_length inference, weighted identity)
- confidence_tier (all 6 tiers)
- classify_allele (full branch coverage incl. exact-blocked path)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.engine.hits import Hit  # noqa: E402
from bacmap.core.engine.utils import (  # noqa: E402
    classify_allele,
    confidence_tier,
    merge_intervals,
)

# ===========================================================================
# Hit.from_blast_line
# ===========================================================================


class TestHitFromBlastLine:
    def test_forward_strand_with_full_coverage_math(self):
        line = "q1\ts1\t98.50\t295\t3\t0\t1\t295\t10\t304\t1e-100\t500\t295\t300"
        h = Hit.from_blast_line(line)
        assert h.query_id == "q1"
        assert h.subject_id == "s1"
        assert h.identity == 98.5
        assert h.alignment_length == 295
        assert h.mismatches == 3
        assert h.query_start == 1
        assert h.query_end == 295
        assert h.subject_start == 10
        assert h.subject_end == 304
        assert h.evalue == 1e-100
        assert h.bit_score == 500.0
        assert h.query_coverage == 100.0
        assert h.subject_coverage == pytest.approx(98.33, abs=0.01)
        assert h.strand == "+"
        assert h.backend == "blast"

    def test_reverse_strand_when_sstart_greater_than_send(self):
        line = "q1\ts1\t99.0\t200\t1\t0\t1\t200\t400\t201\t1e-50\t300\t200\t400"
        h = Hit.from_blast_line(line)
        assert h.strand == "-"
        assert h.query_coverage == 100.0
        assert h.subject_coverage == 50.0

    def test_short_line_raises_valueerror(self):
        with pytest.raises(ValueError, match="need >=14"):
            Hit.from_blast_line("q1\ts1\t98.5")

    def test_exactly_fourteen_fields_succeeds(self):
        line = "q\ts\t100.0\t100\t0\t0\t1\t100\t1\t100\t1e-50\t200\t100\t100"
        h = Hit.from_blast_line(line)
        assert h.identity == 100.0
        assert h.query_coverage == 100.0
        assert h.subject_coverage == 100.0

    def test_zero_qlen_yields_zero_qcov(self):
        line = "q\ts\t100.0\t0\t0\t0\t1\t0\t1\t0\t1e-50\t0\t0\t100"
        h = Hit.from_blast_line(line)
        assert h.query_coverage == 0.0
        assert h.subject_coverage == 0.0
        assert h.alignment_length == 0

    def test_zero_slen_yields_zero_scov(self):
        line = "q\ts\t100.0\t0\t0\t0\t1\t0\t1\t0\t1e-50\t0\t100\t0"
        h = Hit.from_blast_line(line)
        assert h.subject_coverage == 0.0

    def test_whitespace_is_stripped(self):
        line = "  q1\ts1\t98.50\t295\t3\t0\t1\t295\t10\t304\t1e-100\t500\t295\t300  \n"
        h = Hit.from_blast_line(line)
        assert h.query_id == "q1"
        assert h.identity == 98.5

    def test_extra_fields_beyond_fourteen_ignored(self):
        line = "q\ts\t99.0\t100\t0\t0\t1\t100\t1\t100\t1e-50\t200\t100\t100\textra1\textra2"
        h = Hit.from_blast_line(line)
        assert h.identity == 99.0
        assert h.subject_coverage == 100.0

    def test_equal_sstart_send_is_forward(self):
        line = "q\ts\t99.0\t1\t0\t0\t1\t1\t100\t100\t1e-50\t10\t1\t200"
        h = Hit.from_blast_line(line)
        assert h.strand == "+"


# ===========================================================================
# Hit.from_paf_line
# ===========================================================================


class TestHitFromPafLine:
    def test_valid_paf_with_nm_tag(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60\tNM:i:20"
        h = Hit.from_paf_line(line)
        assert h.query_id == "q1"
        assert h.subject_id == "t1"
        assert h.identity == 95.0
        assert h.query_coverage == 40.0
        assert h.subject_coverage == 20.0
        assert h.alignment_length == 400
        assert h.mismatches == 20
        assert h.mapq == 60
        assert h.strand == "+"
        assert h.backend == "minimap2"
        assert h.query_start == 100
        assert h.query_end == 500
        assert h.subject_start == 50
        assert h.subject_end == 450

    def test_minus_strand_preserved(self):
        line = "q1\t1000\t100\t500\t-\tt1\t2000\t50\t450\t380\t400\t60\tNM:i:5"
        h = Hit.from_paf_line(line)
        assert h.strand == "-"

    def test_invalid_nm_tag_value_keeps_zero(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60\tNM:i:abc"
        h = Hit.from_paf_line(line)
        assert h.mismatches == 0

    def test_nm_tag_wrong_type_skipped(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60\tNM:f:5.0"
        h = Hit.from_paf_line(line)
        assert h.mismatches == 0

    def test_short_line_raises_valueerror(self):
        with pytest.raises(ValueError, match="Invalid PAF"):
            Hit.from_paf_line("q1\t1000\t100")

    def test_empty_line_raises_valueerror(self):
        with pytest.raises(ValueError, match="Empty/comment"):
            Hit.from_paf_line("")

    def test_whitespace_only_line_raises_valueerror(self):
        with pytest.raises(ValueError, match="Empty/comment"):
            Hit.from_paf_line("    ")

    def test_comment_line_raises_valueerror(self):
        with pytest.raises(ValueError, match="Empty/comment"):
            Hit.from_paf_line("# comment")

    def test_zero_aln_len_yields_zero_identity(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t0\t0\t60"
        h = Hit.from_paf_line(line)
        assert h.identity == 0.0
        assert h.query_coverage == 40.0

    def test_paf_without_nm_tag_keeps_zero_mismatches(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60"
        h = Hit.from_paf_line(line)
        assert h.mismatches == 0

    def test_non_nm_tags_do_not_set_mismatches(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60\tAS:i:300\txs:i:200"
        h = Hit.from_paf_line(line)
        assert h.mismatches == 0

    def test_malformed_tag_does_not_crash(self):
        line = "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60\tBROKEN"
        h = Hit.from_paf_line(line)
        assert h.mismatches == 0


# ===========================================================================
# merge_intervals extension cases
# ===========================================================================


class TestMergeIntervalsExt:
    def test_subject_length_zero_uses_max_coord(self):
        h = Hit(
            subject_start=1,
            subject_end=200,
            alignment_length=200,
            identity=99.0,
        )
        cov, ident = merge_intervals([h], subject_length=0)
        assert cov == 100.0
        assert ident == 99.0

    def test_subject_length_negative_uses_max_coord(self):
        h = Hit(
            subject_start=1,
            subject_end=100,
            alignment_length=100,
            identity=99.0,
        )
        cov, _ = merge_intervals([h], subject_length=-5)
        assert cov == 100.0

    def test_all_zero_hits_returns_zeros(self):
        h = Hit(identity=99.0)
        cov, ident = merge_intervals([h], subject_length=0)
        assert cov == 0.0
        assert ident == 0.0

    def test_length_weighted_identity_two_hits(self):
        h1 = Hit(
            subject_start=1,
            subject_end=100,
            alignment_length=100,
            identity=99.0,
        )
        h2 = Hit(
            subject_start=200,
            subject_end=500,
            alignment_length=300,
            identity=90.0,
        )
        _, ident = merge_intervals([h1, h2], subject_length=10000)
        expected = (99.0 * 100 + 90.0 * 300) / 400
        assert ident == round(expected, 2)

    def test_skips_intervals_with_zero_coords(self):
        h1 = Hit(subject_start=0, subject_end=0, alignment_length=10, identity=99.0)
        h2 = Hit(subject_start=100, subject_end=200, alignment_length=101, identity=95.0)
        cov, _ = merge_intervals([h1, h2], subject_length=1000)
        assert cov == 10.1

    def test_reverse_intervals_are_swapped(self):
        h = Hit(
            subject_start=200,
            subject_end=100,
            alignment_length=101,
            identity=99.0,
        )
        cov, _ = merge_intervals([h], subject_length=1000)
        assert cov == 10.1

    def test_contig_intervals_merged_into_one(self):
        h1 = Hit(subject_start=1, subject_end=100, alignment_length=100, identity=99.0)
        h2 = Hit(subject_start=50, subject_end=150, alignment_length=101, identity=99.0)
        h3 = Hit(subject_start=120, subject_end=200, alignment_length=81, identity=99.0)
        cov, _ = merge_intervals([h1, h2, h3], subject_length=1000)
        assert cov == 20.0


# ===========================================================================
# confidence_tier
# ===========================================================================


class TestConfidenceTier:
    @pytest.mark.parametrize(
        "coverage,identity,expected",
        [
            (100.0, 100.0, "perfect"),
            (99.0, 99.0, "perfect"),
            (99.5, 95.0, "very_high"),
            (99.5, 96.0, "very_high"),
            (95.0, 90.0, "high"),
            (97.0, 92.0, "high"),
            (99.99, 94.99, "high"),
            (90.0, 85.0, "good"),
            (92.0, 87.0, "good"),
            (80.0, 80.0, "low"),
            (85.0, 82.0, "low"),
            (50.0, 50.0, "none"),
            (75.0, 99.0, "none"),
            (99.0, 75.0, "none"),
            (0.0, 0.0, "none"),
        ],
    )
    def test_tier_classification(self, coverage, identity, expected):
        assert confidence_tier(coverage, identity) == expected

    def test_perfect_boundary_is_inclusive(self):
        assert confidence_tier(99.0, 99.0) == "perfect"

    def test_below_perfect_coverage_falls_to_high(self):
        assert confidence_tier(98.99, 99.0) == "high"


# ===========================================================================
# classify_allele
# ===========================================================================


class TestClassifyAlleleExt:
    def test_exact_at_default_thresholds(self):
        assert classify_allele(99.99, 99.9) == ("exact", 90)
        assert classify_allele(100.0, 100.0) == ("exact", 90)

    def test_exact_blocked_by_custom_min_identity_above_threshold(self):
        label, score = classify_allele(100.0, 100.0, min_identity=100.0)
        assert label == "novel"
        assert score == 63

    def test_novel_default_thresholds(self):
        label, score = classify_allele(97.0, 99.0)
        assert label == "novel"
        assert score == 63

    def test_partial_when_coverage_below_min(self):
        label, score = classify_allele(96.0, 70.0, min_identity=95.0, min_coverage=98.0)
        assert label == "partial"
        assert score == 18

    def test_partial_identity_at_min_boundary(self):
        label, score = classify_allele(95.0, 60.0, min_identity=95.0)
        assert label == "partial"
        assert score == 18

    def test_missing_low_identity_with_high_coverage(self):
        label, score = classify_allele(50.0, 100.0, min_identity=95.0)
        assert label == "missing"
        assert score == 0

    def test_missing_low_coverage_below_50(self):
        label, score = classify_allele(99.0, 30.0, min_identity=95.0)
        assert label == "missing"
        assert score == 0

    def test_missing_zero_zero(self):
        assert classify_allele(0.0, 0.0) == ("missing", 0)

    def test_exact_threshold_blocked_by_coverage(self):
        # identity qualifies (>=99.99) but coverage < 99.9 → not exact
        label, _ = classify_allele(100.0, 99.0, min_identity=95.0)
        assert label == "novel"

    def test_novel_threshold_at_min_boundaries(self):
        label, score = classify_allele(95.0, 98.0)
        assert label == "novel"
        assert score == 63

    def test_custom_min_coverage_above_default(self):
        label, _ = classify_allele(97.0, 99.0, min_identity=95.0, min_coverage=99.5)
        assert label == "partial"
