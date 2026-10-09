"""Contract tests for the cgMLST reference fixture
``tests/fixtures/cgmlst_reference/synthetic_5.tsv``.

This fixture is the golden reference for the projection tests in todo 7
(``analysis/cgmlst_projection.py``). It carries 5 hand-written cgMLST profiles
over 10 loci with **known, hand-computed pairwise Hamming distances** so todo 7
can assert deterministic nearest-neighbour + verdict numbers WITHOUT depending
on a real ``gmlst`` run.

The distance matrix below is the single source of truth for the golden numbers
— todo 7's tests should import ``EXPECTED_DISTANCES`` from here rather than
re-deriving them, so any intentional change to the fixture propagates through
one place.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.cgmlst_types import CgmlstProfile  # noqa: E402
from bacmap.core.utils import parse_cgmlst_profiles  # noqa: E402

FIXTURE = _PROJECT_ROOT / "tests" / "fixtures" / "cgmlst_reference" / "synthetic_5.tsv"

# Expected sample ids in fixture order.
EXPECTED_IDS = ["REF-001", "REF-002", "REF-003", "REF-004", "REF-005"]

# Locus schema of the synthetic scheme.
EXPECTED_LOCI = [f"L{i}" for i in range(1, 11)]

# --- Golden pairwise Hamming distance matrix -------------------------------
# Hand-computed (EnteroBase HierCC convention: a locus is counted only when
# BOTH profiles have a non-None called allele; every cell in this fixture is
# called, so the matrix is the raw count of differing loci).
#
# Relationship summary (the design intent of this fixture):
#   * REF-001 <-> REF-002 == 1   (near-identical; only L5 differs)
#   * REF-003 is intermediate; closest to REF-002 (dist 2)
#   * REF-004 is farther; closest to REF-003 (dist 3)
#   * REF-005 is maximally distant from every other sample (dist 8; differs at
#     L1..L8, identical at L9..L10)
#
#                REF-001 REF-002 REF-003 REF-004 REF-005
#   REF-001:        0       1       3       6       8
#   REF-002:        1       0       2       5       8
#   REF-003:        3       2       0       3       8
#   REF-004:        6       5       3       0       8
#   REF-005:        8       8       8       8       0
# Full symmetric matrix (both (a,b) and (b,a) encoded) so todo 7 can index
# with any ordered pair without normalising direction.
EXPECTED_DISTANCES: dict[tuple[str, str], int] = {
    ("REF-001", "REF-001"): 0,
    ("REF-001", "REF-002"): 1,
    ("REF-001", "REF-003"): 3,
    ("REF-001", "REF-004"): 6,
    ("REF-001", "REF-005"): 8,
    ("REF-002", "REF-001"): 1,
    ("REF-002", "REF-002"): 0,
    ("REF-002", "REF-003"): 2,
    ("REF-002", "REF-004"): 5,
    ("REF-002", "REF-005"): 8,
    ("REF-003", "REF-001"): 3,
    ("REF-003", "REF-002"): 2,
    ("REF-003", "REF-003"): 0,
    ("REF-003", "REF-004"): 3,
    ("REF-003", "REF-005"): 8,
    ("REF-004", "REF-001"): 6,
    ("REF-004", "REF-002"): 5,
    ("REF-004", "REF-003"): 3,
    ("REF-004", "REF-004"): 0,
    ("REF-004", "REF-005"): 8,
    ("REF-005", "REF-001"): 8,
    ("REF-005", "REF-002"): 8,
    ("REF-005", "REF-003"): 8,
    ("REF-005", "REF-004"): 8,
    ("REF-005", "REF-005"): 0,
}


def _hamming(a: CgmlstProfile, b: CgmlstProfile) -> int:
    """Reference Hamming impl (missing-on-either excluded, HierCC convention).

    This is the SAME definition todo 7's ``project_sample`` will use; we keep a
    private copy here so a bug in the projection module cannot silently make
    the fixture's golden numbers agree with a wrong implementation.
    """
    diff = 0
    for locus, av in a.alleles.items():
        bv = b.alleles.get(locus)
        if av is None or bv is None:
            continue
        if av != bv:
            diff += 1
    return diff


@pytest.fixture(scope="module")
def profiles() -> list[CgmlstProfile]:
    """Load the synthetic fixture once for the whole module."""
    return parse_cgmlst_profiles(FIXTURE.read_text())


class TestFixtureWellFormed:
    """The fixture must be a valid cgMLST TSV the todo-1 parser can ingest."""

    def test_fixture_file_exists(self):
        assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"

    def test_loads_five_profiles(self, profiles):
        assert len(profiles) == 5

    def test_sample_ids_in_design_order(self, profiles):
        assert [p.sample_id for p in profiles] == EXPECTED_IDS

    def test_scheme_column_is_synthetic(self, profiles):
        for p in profiles:
            assert p.scheme == "synthetic_10"

    def test_st_column_is_dash(self, profiles):
        # cgMLST schemes carry no single ST; the column is "-" by convention.
        for p in profiles:
            assert p.st_raw == "-"

    def test_ten_loci_per_profile(self, profiles):
        for p in profiles:
            assert p.n_total == 10
            assert list(p.alleles.keys()) == EXPECTED_LOCI

    def test_all_alleles_called(self, profiles):
        # No missing/novel/ambiguous markers in this fixture — the distances
        # are clean integer counts. (Marker handling is covered by the parser
        # tests in test_cgmlst_profile_parser.py.)
        for p in profiles:
            assert p.n_called == 10
            assert p.missing_loci == []
            assert p.novel_loci == []
            assert p.ambiguous_loci == []


class TestGoldenDistances:
    """The fixture's hand-computed distances must hold under the reference
    Hamming implementation. Todo 7's projection tests consume
    ``EXPECTED_DISTANCES`` as the golden source of truth."""

    def test_matrix_is_symmetric(self):
        for (a, b), d in EXPECTED_DISTANCES.items():
            if a != b:
                assert EXPECTED_DISTANCES[(b, a)] == d, f"asymmetric at {a},{b}"

    def test_computed_distances_match_golden(self, profiles):
        by_id = {p.sample_id: p for p in profiles}
        for (a_id, b_id), expected in EXPECTED_DISTANCES.items():
            a = by_id[a_id]
            b = by_id[b_id]
            got = _hamming(a, b)
            assert got == expected, f"d({a_id},{b_id}) = {got}, golden says {expected}"

    def test_ref001_ref002_near_identical(self, profiles):
        # The design intent: samples 1+2 differ at exactly one locus.
        assert _hamming(profiles[0], profiles[1]) == 1

    def test_ref005_is_outlier(self, profiles):
        # REF-005 is maximally distant from every other sample (dist 8).
        for other in profiles[:4]:
            assert _hamming(profiles[4], other) == 8

    def test_nearest_neighbour_of_ref001_is_ref002(self, profiles):
        # The nearest-neighbour ordering for REF-001 must be
        # REF-002 (1) < REF-003 (3) < REF-004 (6) < REF-005 (8).
        query = profiles[0]
        others = [p for p in profiles if p.sample_id != query.sample_id]
        ranked = sorted(others, key=lambda p: _hamming(query, p))
        assert [p.sample_id for p in ranked] == [
            "REF-002",
            "REF-003",
            "REF-004",
            "REF-005",
        ]
        assert [_hamming(query, p) for p in ranked] == [1, 3, 6, 8]
