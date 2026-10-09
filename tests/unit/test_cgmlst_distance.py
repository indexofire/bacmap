"""Tests for analysis.cgmlst_distance -- Hamming matrix + MST/NJ tree builder.

Covers the spec's golden-distance case (3 profiles with hand-computed pairwise
distances), the EnteroBase HierCC missing-exclusion rule, the all-missing
edge case, and Newick validity for both the neighbour-joining (default) and
minimum-spanning-tree methods. Distance golden numbers are computed by hand
in the comments, NOT produced by the implementation under test.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest
from Bio.Phylo import parse as parse_newick

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.cgmlst_distance import (  # noqa: E402
    DistanceMatrix,
    build_tree,
    distance_matrix,
)
from bacmap.core.analysis.cgmlst_types import CgmlstProfile  # noqa: E402


def _profile(sample_id: str, alleles: dict[str, int | None]) -> CgmlstProfile:
    """Build a minimal CgmlstProfile for distance testing.

    Only ``alleles`` matters for distance computation; the locus-classification
    lists are left empty because the distance function reads only ``alleles``.
    """
    n_called = sum(1 for v in alleles.values() if v is not None)
    return CgmlstProfile(
        sample_id=sample_id,
        scheme="test_scheme",
        st_raw="-",
        alleles=dict(alleles),
        n_called=n_called,
        n_total=len(alleles),
    )


def _is_parseable(newick: str) -> bool:
    """Return True iff Bio.Phylo can parse at least one tree from newick."""
    try:
        trees = list(parse_newick(StringIO(newick), "newick"))
    except Exception:
        return False
    return len(trees) >= 1


# ---------------------------------------------------------------------------
# distance_matrix
# ---------------------------------------------------------------------------


class TestDistanceMatrix:
    def test_three_profiles_known_distances(self):
        # Golden numbers (computed by hand):
        #   alleles:    l1   l2   l3   l4
        #   A           1    4    7    10
        #   B           1    5    7    11
        #   C           1    6    8    10
        #
        #   A-B: l1 same, l2 diff, l3 same, l4 diff       -> 2
        #   A-C: l1 same, l2 diff, l3 diff, l4 same       -> 2
        #   B-C: l1 same, l2 diff, l3 diff, l4 diff       -> 3
        a = _profile("A", {"l1": 1, "l2": 4, "l3": 7, "l4": 10})
        b = _profile("B", {"l1": 1, "l2": 5, "l3": 7, "l4": 11})
        c = _profile("C", {"l1": 1, "l2": 6, "l3": 8, "l4": 10})

        m = distance_matrix([a, b, c])

        assert m.samples == ["A", "B", "C"]
        # golden pairwise
        assert m.distances["A"]["B"] == 2
        assert m.distances["A"]["C"] == 2
        assert m.distances["B"]["C"] == 3
        # symmetry
        assert m.distances["B"]["A"] == 2
        assert m.distances["C"]["A"] == 2
        assert m.distances["C"]["B"] == 3
        # zero diagonal
        for s in m.samples:
            assert m.distances[s][s] == 0

    def test_missing_excluded_from_comparison(self):
        # EnteroBase HierCC rule: a locus missing on EITHER side is excluded.
        #   alleles:    l1    l2     l3     l4
        #   A           1     None   7      10
        #   B           1     5      None   11
        # Comparable (both called): l1 (same), l4 (differs) -> 1.
        # l2 missing on A, l3 missing on B -> both excluded.
        a = _profile("A", {"l1": 1, "l2": None, "l3": 7, "l4": 10})
        b = _profile("B", {"l1": 1, "l2": 5, "l3": None, "l4": 11})
        m = distance_matrix([a, b])
        assert m.distances["A"]["B"] == 1

    def test_all_missing_profiles_give_all_zero_matrix(self):
        a = _profile("A", {"l1": None, "l2": None})
        b = _profile("B", {"l1": None, "l2": None})
        c = _profile("C", {"l1": None, "l2": None})
        m = distance_matrix([a, b, c])
        assert m.samples == ["A", "B", "C"]
        for s1 in m.samples:
            for s2 in m.samples:
                assert m.distances[s1][s2] == 0

    def test_identical_profiles_zero_distance(self):
        alleles = {"l1": 1, "l2": 2, "l3": 3}
        a = _profile("A", alleles)
        b = _profile("B", alleles)
        m = distance_matrix([a, b])
        assert m.distances["A"]["B"] == 0
        assert m.distances["B"]["A"] == 0

    def test_single_profile_returns_self_zero_matrix(self):
        a = _profile("A", {"l1": 1, "l2": 2})
        m = distance_matrix([a])
        assert m.samples == ["A"]
        assert m.distances == {"A": {"A": 0}}

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="at least one profile"):
            distance_matrix([])

    def test_profiles_not_mutated(self):
        alleles_a = {"l1": 1, "l2": 2}
        alleles_b = {"l1": 1, "l2": 99}
        a = _profile("A", alleles_a)
        b = _profile("B", alleles_b)
        _ = distance_matrix([a, b])
        # Caller-side dicts and the dataclass's alleles dict must be untouched.
        assert alleles_a == {"l1": 1, "l2": 2}
        assert alleles_b == {"l1": 1, "l2": 99}
        assert a.alleles == {"l1": 1, "l2": 2}
        assert b.alleles == {"l1": 1, "l2": 99}

    def test_real_sample_ids_with_hyphens(self):
        # Real bacmap sample IDs contain hyphens; ensure they survive as keys.
        a = _profile("SAM-TYP-001", {"l1": 1, "l2": 2})
        b = _profile("SAM-TYP-002", {"l1": 1, "l2": 3})
        m = distance_matrix([a, b])
        assert m.distances["SAM-TYP-001"]["SAM-TYP-002"] == 1
        assert m.distances["SAM-TYP-002"]["SAM-TYP-001"] == 1


# ---------------------------------------------------------------------------
# build_tree
# ---------------------------------------------------------------------------


def _three_sample_matrix() -> DistanceMatrix:
    """Matrix with golden distances A-B=2, A-C=2, B-C=3 (see TestDistanceMatrix)."""
    a = _profile("A", {"l1": 1, "l2": 4, "l3": 7, "l4": 10})
    b = _profile("B", {"l1": 1, "l2": 5, "l3": 7, "l4": 11})
    c = _profile("C", {"l1": 1, "l2": 6, "l3": 8, "l4": 10})
    return distance_matrix([a, b, c])


class TestBuildTree:
    def test_nj_valid_newick_three_samples(self):
        m = _three_sample_matrix()
        newick = build_tree(m, method="nj")
        assert newick.endswith(";")
        assert _is_parseable(newick)
        # Every sample name must appear in the rendered tree.
        for name in m.samples:
            assert name in newick

    def test_mst_valid_newick_three_samples(self):
        m = _three_sample_matrix()
        newick = build_tree(m, method="mst")
        assert newick.endswith(";")
        assert _is_parseable(newick)
        for name in m.samples:
            assert name in newick

    def test_default_method_is_nj(self):
        m = _three_sample_matrix()
        assert build_tree(m) == build_tree(m, method="nj")

    def test_nj_two_samples_split_distance_evenly(self):
        # Single-locus difference: d=1, NJ terminal join splits evenly -> 0.5.
        a = _profile("A", {"l1": 1})
        b = _profile("B", {"l1": 2})
        m = distance_matrix([a, b])
        newick = build_tree(m, method="nj")
        assert _is_parseable(newick)
        assert "A" in newick and "B" in newick
        assert "0.5" in newick

    def test_mst_two_samples_uses_full_distance(self):
        # MST over 2 samples has one edge with weight = full Hamming distance.
        a = _profile("A", {"l1": 1, "l2": 1, "l3": 1})
        b = _profile("B", {"l1": 1, "l2": 2, "l3": 3})
        m = distance_matrix([a, b])
        newick = build_tree(m, method="mst")
        assert _is_parseable(newick)
        # d(A,B)=2 -> MST edge weight 2 appears in branch length.
        assert "A" in newick and "B" in newick
        assert ":2" in newick

    def test_single_sample_returns_trivial_newick(self):
        a = _profile("LONE", {"l1": 1})
        m = distance_matrix([a])
        newick = build_tree(m)
        assert newick == "LONE;"
        assert _is_parseable(newick)

    def test_single_sample_works_for_both_methods(self):
        a = _profile("LONE", {"l1": 1})
        m = distance_matrix([a])
        for method in ("nj", "mst"):
            assert _is_parseable(build_tree(m, method=method))

    def test_all_missing_matrix_still_builds_tree(self):
        # Zero-matrix must still yield a valid (if flat) tree for both methods.
        a = _profile("A", {"l1": None, "l2": None})
        b = _profile("B", {"l1": None, "l2": None})
        c = _profile("C", {"l1": None, "l2": None})
        m = distance_matrix([a, b, c])
        for method in ("nj", "mst"):
            newick = build_tree(m, method=method)
            assert _is_parseable(newick), f"{method}: {newick!r}"
            for name in ("A", "B", "C"):
                assert name in newick

    def test_unknown_method_raises(self):
        m = _three_sample_matrix()
        with pytest.raises(ValueError, match="unknown tree method"):
            build_tree(m, method="bogus")

    def test_empty_matrix_raises(self):
        empty = DistanceMatrix(samples=[], distances={})
        with pytest.raises(ValueError, match="non-empty DistanceMatrix"):
            build_tree(empty)

    def test_nj_tree_clades_match_input_sample_set(self):
        # The set of leaf + named-internal names in the parsed tree must be
        # exactly the input sample set (no fabrication, no drops).
        m = _three_sample_matrix()
        newick = build_tree(m, method="nj")
        tree = next(parse_newick(StringIO(newick), "newick"))
        all_names = {c.name for c in tree.find_clades() if c.name}
        assert all_names == set(m.samples)

    def test_mst_tree_clades_match_input_sample_set(self):
        m = _three_sample_matrix()
        newick = build_tree(m, method="mst")
        tree = next(parse_newick(StringIO(newick), "newick"))
        all_names = {c.name for c in tree.find_clades() if c.name}
        assert all_names == set(m.samples)
