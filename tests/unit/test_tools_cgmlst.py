"""Unit tests for the bio_cgmlst (cgmlst_traceback) LLM tool handler.

Covers:
  * happy path -- payload-from-GOM + mocked project_sample -> JSON assertion
    on verdict + nearest list;
  * missing sample -> error JSON with the documented "run bio_analyze_pathogen"
    hint;
  * handler registered in ``_TOOL_REGISTRY`` and via ``register()`` (count check).

The handler is a thin orchestration layer over ``_load_cgmlst_profile_payload``,
``_load_reference_profiles``, ``_load_species_thresholds`` and
``project_sample``; the projection, parsing and threshold-loading paths each
have their own dedicated test modules (test_cgmlst_projection.py,
test_cgmlst_profile_parser.py, etc.). Here we monkeypatch the four helpers so
the test exercises only the handler's control flow + JSON serialisation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap import tools  # noqa: E402
from bacmap.core.analysis.cgmlst_projection import (  # noqa: E402
    CgmlstThresholds,
    NearestMatch,
    ProjectionResult,
    Verdict,
)
from bacmap.tools import services as tools_services  # noqa: E402
from bacmap.tools.registry import _TOOL_REGISTRY  # noqa: E402


def _parse(result: str) -> dict[str, Any]:
    return json.loads(result)


# A GOM-style cgmlst_profile payload (shape mirrors _build_cgmlst_payload in
# scripts/ingest_results.py). Alleles use int|None per the parser contract.
HAPPY_PAYLOAD: dict[str, Any] = {
    "analysis_type": "cgmlst_profile",
    "sample_id": "SAM-TEST-001",
    "scheme": "senterica_2",
    "st_raw": "-",
    "alleles": {"L1": 1, "L2": 2, "L3": None},
    "n_called": 2,
    "n_total": 3,
    "missing_loci": ["L3"],
    "novel_loci": [],
    "ambiguous_loci": [],
}


# A deterministic ProjectionResult the mocked project_sample returns.
HAPPY_RESULT = ProjectionResult(
    sample_id="SAM-TEST-001",
    nearest=[
        NearestMatch(sample_id="REF-001", distance=2),
        NearestMatch(sample_id="REF-002", distance=5),
    ],
    verdict=Verdict.OUTBREAK,
    threshold_used=CgmlstThresholds(
        outbreak_allele_dist=10, related_allele_dist=50, clonal_allele_dist=3
    ),
    species="Salmonella",
    caveats=[],
    n_comparable_loci=10,
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCgmlstTracebackHappyPath:
    @pytest.fixture(autouse=True)
    def _stub_helpers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tools_services,
            "_load_cgmlst_profile_payload",
            lambda sample_id: {**HAPPY_PAYLOAD, "_from_gom": True},
        )
        # Non-empty list sentinel -- the handler only checks `not reference`
        # before calling project_sample, which we also stub.
        monkeypatch.setattr(
            tools_services,
            "_load_reference_profiles",
            lambda species: [object()],
        )
        monkeypatch.setattr(
            tools_services,
            "_load_species_thresholds",
            lambda species: CgmlstThresholds(outbreak_allele_dist=10, related_allele_dist=50),
        )
        monkeypatch.setattr(tools_services, "project_sample", lambda *a, **kw: HAPPY_RESULT)

    def test_returns_json_with_verdict_and_nearest(self):
        r = _parse(tools.cgmlst_traceback({"sample_id": "SAM-TEST-001"}))

        assert r["sample_id"] == "SAM-TEST-001"
        assert r["verdict"] == "outbreak"
        assert r["species"] == "Salmonella"
        assert r["n_comparable_loci"] == 10
        assert r["nearest"] == [
            {"sample_id": "REF-001", "distance": 2},
            {"sample_id": "REF-002", "distance": 5},
        ]

    def test_threshold_used_is_serialised(self):
        r = _parse(tools.cgmlst_traceback({"sample_id": "SAM-TEST-001"}))
        assert r["threshold_used"] == {
            "outbreak_allele_dist": 10,
            "related_allele_dist": 50,
            "clonal_allele_dist": 3,
        }

    def test_source_flag_is_gom_when_payload_from_gom(self):
        r = _parse(tools.cgmlst_traceback({"sample_id": "SAM-TEST-001"}))
        assert r["source"] == "gom"

    def test_source_flag_is_disk_when_payload_from_tsv(self, monkeypatch):
        monkeypatch.setattr(
            tools_services,
            "_load_cgmlst_profile_payload",
            lambda sample_id: {**HAPPY_PAYLOAD, "_from_gom": False},
        )
        r = _parse(tools.cgmlst_traceback({"sample_id": "SAM-TEST-001"}))
        assert r["source"] == "disk"

    def test_missing_sample_id_arg_returns_error(self):
        r = _parse(tools.cgmlst_traceback({}))
        assert "sample_id is required" in r["error"]


# ---------------------------------------------------------------------------
# Missing sample -> error JSON
# ---------------------------------------------------------------------------


class TestCgmlstTracebackMissingSample:
    def test_no_db_no_tsv_returns_error_with_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(tools_services, "_DEFAULT_DB_PATH", tmp_path / "missing.sqlite")
        monkeypatch.setattr(tools_services, "_RESULTS_DIR", tmp_path / "no_results")

        r = _parse(tools.cgmlst_traceback({"sample_id": "SAM-GHOST"}))

        assert "error" in r
        assert "no cgmlst profile for SAM-GHOST" in r["error"]
        assert "bio_analyze_pathogen" in r["error"]

    def test_unknown_scheme_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            tools_services,
            "_load_cgmlst_profile_payload",
            lambda sample_id: {
                "analysis_type": "cgmlst_profile",
                "sample_id": "SAM-X",
                "scheme": "unrecognised_scheme",
                "alleles": {},
                "n_called": 0,
                "n_total": 0,
                "missing_loci": [],
                "novel_loci": [],
                "ambiguous_loci": [],
                "_from_gom": True,
            },
        )

        r = _parse(tools.cgmlst_traceback({"sample_id": "SAM-X"}))

        assert "unknown cgmlst scheme" in r["error"]
        assert "unrecognised_scheme" in r["error"]


# ---------------------------------------------------------------------------
# Registration count check
# ---------------------------------------------------------------------------


class TestCgmlstTracebackRegistration:
    def test_bio_cgmlst_tuple_in_registry(self):
        matches = [t for t in _TOOL_REGISTRY if t[0] == "bio_cgmlst"]
        assert len(matches) == 1, "bio_cgmlst should appear exactly once"
        _, schema, handler = matches[0]
        assert schema["name"] == "bio_cgmlst"
        assert callable(handler)
        assert handler is tools_services.cgmlst_traceback

    def test_registry_grew_by_one_vs_snp_tree_baseline(self):
        names = [t[0] for t in _TOOL_REGISTRY]
        assert "bio_snp_tree" in names  # baseline predecessor
        assert "bio_cgmlst" in names
        # Documented repo count after adding bio_cgmlst (was 24, now 25).
        # v1.4.5 去 vpa_serotype；v1.4.7 去 validate_taxonomy/species_compare/db_setup/db_status
        # v1.4.12 加 bio_inspect_dataset（沙箱数据集登记查看）
        assert len(_TOOL_REGISTRY) == 26

    def test_schema_has_required_sample_id(self):
        schema = next(s for n, s, _ in _TOOL_REGISTRY if n == "bio_cgmlst")
        assert schema["parameters"]["required"] == ["sample_id"]
        assert "sample_id" in schema["parameters"]["properties"]
