"""Tests for utils.parse_cgmlst_profile / parse_cgmlst_profiles and the
CgmlstProfile dataclass.

Covers the 6 documented gmlst allele markers (``23``, ``23*``, ``~23``,
``15?``, ``1,2``, ``-``), the single-vs-multi-sample dispatch contract, the
typing_amr-style 3-column fallback row, and the empty / header-only edge
cases mirroring the ``parse_mlst`` convention.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.cgmlst_types import CgmlstProfile  # noqa: E402
from bacmap.core.utils import (  # noqa: E402
    parse_cgmlst_profile,
    parse_cgmlst_profiles,
)

# TSV with all 6 marker classes in one row. Reused across several tests.
_HAPPY_HEADER = (
    "File\tScheme\tST\tlocus_exact\tlocus_star\tlocus_novel\t"
    "locus_partial\tlocus_ambig\tlocus_missing"
)
_HAPPY_ROW = "SAM-001\tsenterica_2\t-\t23\t23*\t~23\t15?\t1,2\t-"
_HAPPY_TSV = f"{_HAPPY_HEADER}\n{_HAPPY_ROW}"


class TestClassifyAlleleHappyPath:
    """parse_cgmlst_profile: every marker class on a single row."""

    def test_happy_path_all_markers(self):
        p = parse_cgmlst_profile(_HAPPY_TSV)
        assert p.sample_id == "SAM-001"
        assert p.scheme == "senterica_2"
        assert p.st_raw == "-"
        assert p.n_called == 2  # exact + star
        assert p.n_total == 6
        assert p.alleles == {
            "locus_exact": 23,
            "locus_star": 23,
            "locus_novel": None,
            "locus_partial": None,
            "locus_ambig": None,
            "locus_missing": None,
        }
        assert p.novel_loci == ["locus_novel"]
        assert p.ambiguous_loci == ["locus_ambig"]
        # Partial (?) and missing (-) both land in missing_loci, in column order.
        assert p.missing_loci == ["locus_partial", "locus_missing"]

    def test_star_strips_trailing_marker(self):
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusA\nSAM\tsenterica_2\t-\t99*\n")
        assert p.alleles == {"locusA": 99}
        assert p.n_called == 1

    def test_novel_marker_adds_to_novel_list(self):
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusC\nSAM\tsenterica_2\t-\t~5\n")
        assert p.alleles == {"locusC": None}
        assert p.novel_loci == ["locusC"]
        assert p.n_called == 0

    def test_partial_marker_adds_to_missing_list(self):
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusX\nSAM\tsenterica_2\t-\t15?\n")
        assert p.alleles == {"locusX": None}
        assert p.missing_loci == ["locusX"]

    def test_ambiguous_marker_adds_to_ambiguous_list(self):
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusD\nSAM\tsenterica_2\t-\t1,2\n")
        assert p.alleles == {"locusD": None}
        assert p.ambiguous_loci == ["locusD"]

    def test_dash_marker_adds_to_missing_list(self):
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusB\nS1\tsenterica_2\t-\t-\n")
        assert p.alleles == {"locusB": None}
        assert p.missing_loci == ["locusB"]
        assert p.n_called == 0
        assert p.n_total == 1


class TestAcceptanceCriterionExample:
    """The exact example from the plan's acceptance criteria."""

    def test_acceptance_example(self):
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusA\tlocusB\nS1\tsenterica_2\t-\t12\t-")
        assert p.alleles == {"locusA": 12, "locusB": None}
        assert p.n_called == 1
        assert p.n_total == 2
        assert p.missing_loci == ["locusB"]
        assert p.novel_loci == []
        assert p.ambiguous_loci == []


class TestParseCgmlstProfilesMultiSample:
    """parse_cgmlst_profiles: multi-sample dispatch and per-row parsing."""

    def test_three_rows_yields_three_profiles(self):
        tsv = (
            "File\tScheme\tST\tlocusA\tlocusB\n"
            "S1\tsenterica_2\t-\t1\t2\n"
            "S2\tsenterica_2\t-\t1\t-\n"
            "S3\tsenterica_2\t-\t~1\t3,4\n"
        )
        profiles = parse_cgmlst_profiles(tsv)
        assert len(profiles) == 3

        assert profiles[0].sample_id == "S1"
        assert profiles[0].alleles == {"locusA": 1, "locusB": 2}
        assert profiles[0].n_called == 2

        assert profiles[1].sample_id == "S2"
        assert profiles[1].alleles == {"locusA": 1, "locusB": None}
        assert profiles[1].missing_loci == ["locusB"]
        assert profiles[1].n_called == 1

        assert profiles[2].sample_id == "S3"
        assert profiles[2].novel_loci == ["locusA"]
        assert profiles[2].ambiguous_loci == ["locusB"]
        assert profiles[2].n_called == 0

    def test_shared_header_locus_order_preserved(self):
        tsv = "File\tScheme\tST\tL1\tL2\tL3\nS1\tsch\t-\t1\t2\t3\n"
        profiles = parse_cgmlst_profiles(tsv)
        assert list(profiles[0].alleles.keys()) == ["L1", "L2", "L3"]

    def test_single_row_returns_list_of_one(self):
        profiles = parse_cgmlst_profiles(_HAPPY_TSV)
        assert len(profiles) == 1
        assert profiles[0].sample_id == "SAM-001"


class TestParseCgmlstProfileMultiRowContract:
    """parse_cgmlst_profile: ≥2 data rows raises ValueError pointing to the
    multi-sample helper."""

    def test_two_rows_raises(self):
        tsv = "File\tScheme\tST\tlocusA\nS1\tsch\t-\t1\nS2\tsch\t-\t2\n"
        with pytest.raises(ValueError, match="parse_cgmlst_profiles"):
            parse_cgmlst_profile(tsv)

    def test_three_rows_raises(self):
        tsv = "File\tScheme\tST\tlocusA\nS1\tsch\t-\t1\nS2\tsch\t-\t2\nS3\tsch\t-\t3\n"
        with pytest.raises(ValueError, match="2 data rows|3 data rows"):
            parse_cgmlst_profile(tsv)


class TestFallbackAndEmpty:
    """Edge cases: 3-column fallback row, empty input, header-only."""

    def test_typing_amr_fallback_row_parses_gracefully(self):
        # Emitted by typing_amr.smk when the gmlst binary is unavailable:
        # only File/Scheme/ST columns, no locus columns.
        tsv = "File\tScheme\tST\nSAM-001\tsenterica_2\tN/A"
        p = parse_cgmlst_profile(tsv)
        assert p.sample_id == "SAM-001"
        assert p.scheme == "senterica_2"
        assert p.st_raw == "N/A"
        assert p.alleles == {}
        assert p.n_called == 0
        assert p.n_total == 0
        assert p.missing_loci == []
        assert p.novel_loci == []
        assert p.ambiguous_loci == []

    def test_fallback_row_via_profiles_helper(self):
        tsv = "File\tScheme\tST\nSAM-001\tsenterica_2\tN/A"
        profiles = parse_cgmlst_profiles(tsv)
        assert len(profiles) == 1
        assert profiles[0].n_total == 0

    def test_empty_string_returns_empty_profile(self):
        p = parse_cgmlst_profile("")
        assert p.sample_id == ""
        assert p.scheme == ""
        assert p.st_raw == "N/A"
        assert p.n_called == 0
        assert p.n_total == 0
        assert p.alleles == {}

    def test_na_string_returns_empty_profile(self):
        p = parse_cgmlst_profile("N/A")
        assert p.st_raw == "N/A"
        assert p.n_called == 0
        assert p.n_total == 0

    def test_profiles_empty_string_returns_empty_list(self):
        assert parse_cgmlst_profiles("") == []
        assert parse_cgmlst_profiles("N/A") == []

    def test_header_only_returns_empty_profile(self):
        # No data rows → parse_mlst convention: defaults, no raise.
        p = parse_cgmlst_profile("File\tScheme\tST\tlocusA\tlocusB")
        assert p.n_called == 0
        assert p.n_total == 0
        assert p.alleles == {}

    def test_profiles_header_only_returns_empty_list(self):
        assert parse_cgmlst_profiles("File\tScheme\tST\tlocusA") == []

    def test_blank_data_rows_skipped(self):
        # A trailing newline should not become a phantom empty profile.
        tsv = "File\tScheme\tST\tlocusA\nS1\tsch\t-\t1\n\n"
        profiles = parse_cgmlst_profiles(tsv)
        assert len(profiles) == 1


class TestCgmlstProfileDataclass:
    """CgmlstProfile.to_dict round-trip + defaults."""

    def test_to_dict_round_trip(self):
        p = parse_cgmlst_profile(_HAPPY_TSV)
        d = p.to_dict()
        assert d["sample_id"] == "SAM-001"
        assert d["scheme"] == "senterica_2"
        assert d["st_raw"] == "-"
        assert d["alleles"]["locus_exact"] == 23
        assert d["alleles"]["locus_novel"] is None
        assert d["n_called"] == 2
        assert d["n_total"] == 6
        assert d["missing_loci"] == ["locus_partial", "locus_missing"]
        assert d["novel_loci"] == ["locus_novel"]
        assert d["ambiguous_loci"] == ["locus_ambig"]

    def test_to_dict_is_json_serializable(self):
        import json

        d = parse_cgmlst_profile(_HAPPY_TSV).to_dict()
        # Must not raise — every value is a JSON primitive.
        s = json.dumps(d)
        assert json.loads(s)["sample_id"] == "SAM-001"

    def test_to_dict_does_not_alias_internal_state(self):
        p = parse_cgmlst_profile(_HAPPY_TSV)
        d = p.to_dict()
        d["alleles"]["locus_exact"] = 999
        d["missing_loci"].append("locus_evil")
        # Mutating the dict must not leak back into the dataclass.
        assert p.alleles["locus_exact"] == 23
        assert p.missing_loci == ["locus_partial", "locus_missing"]

    def test_empty_profile_defaults(self):
        p = CgmlstProfile(sample_id="x", scheme="y", st_raw="-")
        assert p.alleles == {}
        assert p.missing_loci == []
        assert p.novel_loci == []
        assert p.ambiguous_loci == []
        assert p.n_called == 0
        assert p.n_total == 0
