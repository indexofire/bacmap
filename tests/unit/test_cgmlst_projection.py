"""Tests for analysis.cgmlst_projection -- nearest-neighbour Hamming projection
+ per-species threshold verdict.

Golden distance numbers come from the
``tests/fixtures/cgmlst_reference/synthetic_5.tsv`` contract (see
``test_cgmlst_reference_fixture.py`` for the hand-computed full pairwise
matrix). They are restated here as the projection's expected output rather than
imported from the sibling test module, so this module stays self-contained and
deterministic.

Synthetic fixture pairwise matrix (single source of truth)::

                   REF-001 REF-002 REF-003 REF-004 REF-005
     REF-001:        0       1       3       6       8
     REF-002:        1       0       2       5       8
     REF-003:        3       2       0       3       8
     REF-004:        6       5       3       0       8
     REF-005:        8       8       8       8       0
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.cgmlst_projection import (  # noqa: E402
    CgmlstThresholds,
    NearestMatch,
    ProjectionResult,
    Verdict,
    load_thresholds_from_config,
    project_sample,
)
from bacmap.core.analysis.cgmlst_types import CgmlstProfile  # noqa: E402
from bacmap.core.utils import parse_cgmlst_profiles  # noqa: E402

FIXTURE = _PROJECT_ROOT / "tests" / "fixtures" / "cgmlst_reference" / "synthetic_5.tsv"
CONFIG = Path(__file__).resolve().parents[1] / "fixtures" / "workflow_config.yaml"

# Salmonella thresholds (mirrors config.yaml cgmlst.thresholds.salmonella;
# restated here so the verdict tests do not depend on disk I/O).
SALMONELLA = CgmlstThresholds(outbreak_allele_dist=10, related_allele_dist=50, clonal_allele_dist=3)


def _profile(sample_id: str, alleles: dict[str, int | None]) -> CgmlstProfile:
    """Build a minimal CgmlstProfile for projection testing."""
    n_called = sum(1 for v in alleles.values() if v is not None)
    return CgmlstProfile(
        sample_id=sample_id,
        scheme="synthetic_10",
        st_raw="-",
        alleles=dict(alleles),
        n_called=n_called,
        n_total=len(alleles),
    )


@pytest.fixture(scope="module")
def refs() -> list[CgmlstProfile]:
    """The 5 fixed reference profiles from the synthetic fixture."""
    return parse_cgmlst_profiles(FIXTURE.read_text())


def _by_id(profiles: list[CgmlstProfile]) -> dict[str, CgmlstProfile]:
    return {p.sample_id: p for p in profiles}


# ---------------------------------------------------------------------------
# Nearest-neighbour ordering against the golden fixture
# ---------------------------------------------------------------------------


class TestNearestOrdering:
    def test_ref001_nearest_is_ref002_ascending(self, refs):
        query = _by_id(refs)["REF-001"]
        others = [p for p in refs if p.sample_id != "REF-001"]

        result = project_sample(query, others, SALMONELLA, species="Salmonella")

        # Golden: REF-002(1) < REF-003(3) < REF-004(6) < REF-005(8).
        assert [m.sample_id for m in result.nearest] == [
            "REF-002",
            "REF-003",
            "REF-004",
            "REF-005",
        ]
        assert [m.distance for m in result.nearest] == [1, 3, 6, 8]

    def test_ref003_tiebreak_is_deterministic_alphabetical(self, refs):
        # REF-003's distances: REF-001=3, REF-002=2, REF-004=3, REF-005=8.
        # Two references tie at distance 3 (REF-001, REF-004); the stable
        # (distance, sample_id) ordering must place REF-001 before REF-004.
        query = _by_id(refs)["REF-003"]
        others = [p for p in refs if p.sample_id != "REF-003"]

        result = project_sample(query, others, SALMONELLA, species="Salmonella")

        assert [m.sample_id for m in result.nearest] == [
            "REF-002",
            "REF-001",
            "REF-004",
            "REF-005",
        ]
        assert [m.distance for m in result.nearest] == [2, 3, 3, 8]

    def test_min_distance_drives_verdict(self, refs):
        # min_dist for REF-001 is 1 (against REF-002).
        query = _by_id(refs)["REF-001"]
        others = [p for p in refs if p.sample_id != "REF-001"]
        result = project_sample(query, others, SALMONELLA, species="Salmonella")
        assert result.nearest[0].distance == 1

    def test_n_comparable_loci_against_nearest(self, refs):
        # Every locus is called on both sides in this fixture, so for query
        # REF-003 vs nearest REF-002 the comparable count is the full 10.
        query = _by_id(refs)["REF-003"]
        others = [p for p in refs if p.sample_id != "REF-003"]
        result = project_sample(query, others, SALMONELLA, species="Salmonella")
        assert result.nearest[0].sample_id == "REF-002"
        assert result.n_comparable_loci == 10

    def test_top_n_truncates_nearest_list(self, refs):
        query = _by_id(refs)["REF-001"]
        others = [p for p in refs if p.sample_id != "REF-001"]
        result = project_sample(query, others, SALMONELLA, species="Salmonella", top_n=2)
        assert len(result.nearest) == 2
        assert [m.sample_id for m in result.nearest] == ["REF-002", "REF-003"]

    def test_top_n_default_is_ten(self, refs):
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Salmonella")
        # Fewer than 10 references -> nearest is the whole library, not padded.
        assert len(result.nearest) == 4

    def test_query_self_in_reference_is_distance_zero(self, refs):
        # If the query is accidentally part of the library it appears at 0.
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, list(refs), SALMONELLA, species="Salmonella")
        assert result.nearest[0].sample_id == "REF-001"
        assert result.nearest[0].distance == 0

    def test_profiles_are_not_mutated(self, refs):
        query = _by_id(refs)["REF-001"]
        query_alleles_before = dict(query.alleles)
        others = [p for p in refs if p.sample_id != "REF-001"]
        others_before = [dict(p.alleles) for p in others]

        _ = project_sample(query, others, SALMONELLA, species="Salmonella")

        assert query.alleles == query_alleles_before
        for p, before in zip(others, others_before, strict=True):
            assert p.alleles == before


# ---------------------------------------------------------------------------
# Verdict tiering
# ---------------------------------------------------------------------------


class TestVerdictTiers:
    def test_outbreak_when_min_dist_le_outbreak_threshold(self, refs):
        # min_dist=1 <= outbreak=10 -> OUTBREAK.
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Salmonella")
        assert result.verdict is Verdict.OUTBREAK

    def test_outbreak_boundary_is_inclusive(self, refs):
        # Construct a query exactly at the outbreak boundary.
        # REF-001 differs from REF-002 at exactly L5 -> distance 1.
        # Use outbreak=1; min_dist=1 <= 1 -> OUTBREAK (inclusive <=).
        query = _by_id(refs)["REF-001"]
        thresholds = CgmlstThresholds(outbreak_allele_dist=1, related_allele_dist=50)
        result = project_sample(query, refs[1:], thresholds, species="Salmonella")
        assert result.verdict is Verdict.OUTBREAK

    def test_related_when_between_outbreak_and_related(self, refs):
        query = _by_id(refs)["REF-003"]
        others = [p for p in refs if p.sample_id != "REF-003"]  # min_dist=2
        thresholds = CgmlstThresholds(outbreak_allele_dist=0, related_allele_dist=3)
        result = project_sample(query, others, thresholds, species="Salmonella")
        assert result.verdict is Verdict.RELATED

    def test_unrelated_when_above_related_threshold(self, refs):
        # query=REF-003 min_dist=2; outbreak=0, related=1 -> 2 > 1 -> UNRELATED.
        query = _by_id(refs)["REF-003"]
        others = [p for p in refs if p.sample_id != "REF-003"]
        thresholds = CgmlstThresholds(outbreak_allele_dist=0, related_allele_dist=1)
        result = project_sample(query, others, thresholds, species="Salmonella")
        assert result.verdict is Verdict.UNRELATED

    def test_ref005_outlier_is_unrelated_under_salmonella(self, refs):
        # REF-005 is distance 8 from every other sample. Under Salmonella
        # thresholds (outbreak=10) 8 <= 10 -> actually OUTBREAK. So to assert
        # UNRELATED against the real config we must use a sub-8 related band.
        query = _by_id(refs)["REF-005"]
        others = [p for p in refs if p.sample_id != "REF-005"]  # min_dist=8
        tight = CgmlstThresholds(outbreak_allele_dist=2, related_allele_dist=5)
        result = project_sample(query, others, tight, species="Salmonella")
        assert result.verdict is Verdict.UNRELATED

    def test_undetermined_when_all_thresholds_none(self, refs):
        # V. parahaemolyticus case: no published numeric threshold.
        query = _by_id(refs)["REF-001"]
        none_thresholds = CgmlstThresholds(outbreak_allele_dist=None, related_allele_dist=None)
        result = project_sample(query, refs[1:], none_thresholds, species="V.parahaemolyticus")
        assert result.verdict is Verdict.UNDETERMINED
        # The nearest list is still populated -- projection is independent of
        # the verdict tier.
        assert result.nearest[0].sample_id == "REF-002"
        assert result.nearest[0].distance == 1

    def test_threshold_used_is_echoed_on_result(self, refs):
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Salmonella")
        assert result.threshold_used is SALMONELLA


# ---------------------------------------------------------------------------
# Caveats
# ---------------------------------------------------------------------------


class TestCaveats:
    def test_s_sonnei_caveat_present(self, refs):
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Shigella sonnei")
        assert any("S. sonnei" in c and "SNV" in c for c in result.caveats)

    def test_s_sonnei_caveat_present_for_short_form(self, refs):
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="S. sonnei")
        assert any("sonnei" in c.lower() for c in result.caveats)

    def test_no_sonnei_caveat_for_other_shigella(self, refs):
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Shigella flexneri")
        assert not any("sonnei" in c.lower() for c in result.caveats)

    def test_vpara_no_threshold_caveat(self, refs):
        # Thresholds both None -> UNDETERMINED + the Vpara no-threshold caveat.
        query = _by_id(refs)["REF-001"]
        none_thresholds = CgmlstThresholds(outbreak_allele_dist=None, related_allele_dist=None)
        result = project_sample(query, refs[1:], none_thresholds, species="V.parahaemolyticus")
        assert result.verdict is Verdict.UNDETERMINED
        assert any("no published cgMLST outbreak threshold" in c for c in result.caveats)

    def test_no_caveat_when_clean_outbreak(self, refs):
        # Salmonella, valid thresholds, query not S. sonnei, full call -> no
        # caveat expected.
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Salmonella")
        assert result.caveats == []


# ---------------------------------------------------------------------------
# Edge cases / failure modes
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_reference_raises_value_error(self, refs):
        query = _by_id(refs)["REF-001"]
        with pytest.raises(ValueError, match="at least one reference"):
            project_sample(query, [], SALMONELLA, species="Salmonella")

    def test_zero_called_loci_is_undetermined(self, refs):
        # Query with every locus None -> every distance is 0 (nothing
        # comparable) which would falsely flag OUTBREAK; must be UNDETERMINED.
        query = _profile(
            "QUERY-EMPTY",
            {f"L{i}": None for i in range(1, 11)},
        )
        result = project_sample(query, refs[1:], SALMONELLA, species="Salmonella")
        assert result.verdict is Verdict.UNDETERMINED
        assert any("0 called loci" in c for c in result.caveats)
        # n_comparable_loci against the (distance-zero) nearest is 0.
        assert result.n_comparable_loci == 0
        # And every reported distance is 0 (no comparable loci anywhere).
        assert all(m.distance == 0 for m in result.nearest)

    def test_zero_called_loci_undetermined_even_with_thresholds(self, refs):
        query = _profile("QUERY-EMPTY", {f"L{i}": None for i in range(1, 11)})
        # Even very tight real thresholds cannot rescue an empty profile.
        tight = CgmlstThresholds(outbreak_allele_dist=0, related_allele_dist=0)
        result = project_sample(query, refs[1:], tight, species="Salmonella")
        assert result.verdict is Verdict.UNDETERMINED

    def test_partial_missing_excluded_from_distance(self, refs):
        # EnteroBase HierCC: a locus missing on either side is excluded.
        # REF-001 has all-1 alleles. Make a query identical except L1=None and
        # L2=99. Only L2 is comparable-and-differing on the REF-001/REF-002
        # axis -> distance to REF-001 is 1 (just L2), distance to REF-002 is 2
        # (L2 and L5 differ among comparable loci).
        alleles = dict(_by_id(refs)["REF-001"].alleles)
        alleles["L1"] = None
        alleles["L2"] = 99
        query = _profile("QUERY-PARTIAL", alleles)

        result = project_sample(query, refs, SALMONELLA, species="Salmonella")
        by_id = {m.sample_id: m for m in result.nearest}
        assert by_id["REF-001"].distance == 1  # only L2 differs
        assert by_id["REF-002"].distance == 2  # L2 and L5 differ


# ---------------------------------------------------------------------------
# load_thresholds_from_config (real config.yaml)
# ---------------------------------------------------------------------------


class TestLoadThresholdsFromConfig:
    def test_salmonella_thresholds_match_config(self):
        t = load_thresholds_from_config(CONFIG, "Salmonella")
        assert t.outbreak_allele_dist == 10
        assert t.related_allele_dist == 50
        assert t.clonal_allele_dist == 3

    def test_ecoli_short_form(self):
        t = load_thresholds_from_config(CONFIG, "E.coli")
        assert t.outbreak_allele_dist == 5
        assert t.related_allele_dist == 50
        assert t.clonal_allele_dist is None

    def test_ecoli_full_latin_name(self):
        t = load_thresholds_from_config(CONFIG, "Escherichia coli")
        assert t.outbreak_allele_dist == 5

    def test_shigella(self):
        t = load_thresholds_from_config(CONFIG, "Shigella")
        assert t.outbreak_allele_dist == 5
        assert t.related_allele_dist == 50

    def test_vparahaemolyticus_short_form_is_all_none(self):
        t = load_thresholds_from_config(CONFIG, "V.parahaemolyticus")
        assert t.outbreak_allele_dist is None
        assert t.related_allele_dist is None
        assert t.clonal_allele_dist is None

    def test_vparahaemolyticus_full_latin_name(self):
        t = load_thresholds_from_config(CONFIG, "Vibrio parahaemolyticus")
        assert t.outbreak_allele_dist is None

    def test_case_insensitive(self):
        assert load_thresholds_from_config(CONFIG, "SALMONELLA").outbreak_allele_dist == 10

    def test_unknown_species_raises(self):
        with pytest.raises(ValueError, match="no cgmlst.thresholds"):
            load_thresholds_from_config(CONFIG, "Listeria")

    def test_missing_config_file_raises(self, tmp_path):
        missing = tmp_path / "nope.yaml"
        with pytest.raises(ValueError, match="config file not found"):
            load_thresholds_from_config(missing, "Salmonella")

    def test_malformed_threshold_value_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "cgmlst:\n  thresholds:\n    SAL:\n"
            "      outbreak_allele_dist: ten\n"
            "      related_allele_dist: 50\n"
        )
        with pytest.raises(ValueError, match="must be int or null"):
            load_thresholds_from_config(bad, "Salmonella")

    def test_missing_threshold_block_raises(self, tmp_path):
        bare = tmp_path / "bare.yaml"
        bare.write_text("threads: 8\n")
        with pytest.raises(ValueError, match="no cgmlst.thresholds"):
            load_thresholds_from_config(bare, "Salmonella")

    def test_round_trip_with_project_sample_vpara(self, refs):
        # End-to-end: load real Vpara thresholds (both None) and project.
        # Verdict must be UNDETERMINED with the no-threshold caveat.
        thresholds = load_thresholds_from_config(CONFIG, "V.parahaemolyticus")
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], thresholds, species="V.parahaemolyticus")
        assert result.verdict is Verdict.UNDETERMINED
        assert any("no published cgMLST outbreak threshold" in c for c in result.caveats)


# ---------------------------------------------------------------------------
# Dataclass shape / serialization sanity
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_verdict_is_strenum_string(self, refs):
        # StrEnum -> str(member) == the value; useful for the bio_cgmlst tool's
        # JSON serialization (todo 10).
        query = _by_id(refs)["REF-001"]
        result = project_sample(query, refs[1:], SALMONELLA, species="Salmonella")
        assert str(result.verdict) == "outbreak"
        assert result.verdict == Verdict.OUTBREAK

    def test_nearest_match_is_frozen_value_object(self):
        m = NearestMatch(sample_id="X", distance=4)
        assert m.sample_id == "X"
        assert m.distance == 4
        with pytest.raises(Exception):
            m.distance = 5  # type: ignore[misc]  # frozen dataclass

    def test_default_projection_result_is_undetermined(self):
        r = ProjectionResult(sample_id="empty")
        assert r.verdict is Verdict.UNDETERMINED
        assert r.nearest == []
        assert r.caveats == []
        assert r.threshold_used is None
        assert r.n_comparable_loci == 0
