"""Tests for cgMLST ANALYSIS payload validation in GenomeObject.

Covers plan todo 2 acceptance criteria for the cgmlst_profile (per-sample)
and cgmlst_cohort (cohort-level) analysis types. Mirrors the fixture pattern
in tests/unit/test_cohort_ingest.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from bacmap.store.genome_object_service import (
    GenomeObject,
    GenomeObjectService,
    GOMValidationError,
    ObjectType,
)

CGMLST_PIPELINE_VERSION = "cgmlst-pipeline-v0.1"
SNP_PIPELINE_VERSION = "snp-pipeline-v0.3"
SNP_COHORT_STRAIN_ID = "cohort:salmonella-snp"
CGMLST_COHORT_STRAIN_ID = "cohort:salmonella-cgmlst"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_cgmlst_profile_payload(*, omit: tuple[str, ...] = ()) -> dict:
    payload: dict = {
        "analysis_type": "cgmlst_profile",
        "sample_id": "SAM-TYP-001",
        "scheme": "senterica_2",
        "n_loci": 3002,
        "alleles": {"SE-1": 1, "SE-2": 2},
        "n_called": 2,
        "n_total": 3002,
        "missing_loci": [],
        "novel_loci": [],
        "ambiguous_loci": [],
    }
    for key in omit:
        payload.pop(key)
    return payload


def _make_cgmlst_cohort_payload(*, omit: tuple[str, ...] = ()) -> dict:
    payload: dict = {
        "analysis_type": "cgmlst_cohort",
        "samples": ["SAM-001", "SAM-002", "SAM-003"],
        "n_samples": 3,
        "scheme": "senterica_2",
        "n_loci": 3002,
        "allele_distances": {"SAM-001|SAM-002": 7, "SAM-001|SAM-003": 42},
        "tree_newick": "(SAM-001:0.01,(SAM-002:0.02,SAM-003:0.03):0.04);",
        "missing_rate": 0.02,
        "thresholds_applied": {"outbreak_allele_dist": 10, "related_allele_dist": 20},
    }
    for key in omit:
        payload.pop(key)
    return payload


def _build_object(
    payload: dict,
    *,
    strain_id: str = "SAM-TYP-001",
    pipeline_version: str = CGMLST_PIPELINE_VERSION,
) -> GenomeObject:
    return GenomeObject(
        object_id=str(uuid4()),
        object_type=ObjectType.ANALYSIS,
        version=1,
        schema_version="0.1.0",
        created_at=_now(),
        created_by="cgmlst-pipeline",
        payload=payload,
        pipeline_version=pipeline_version,
        database_versions={"cgmlst_scheme": "senterica_2@deadbeef", "gmlst": "0.1.1"},
        organism="Salmonella enterica",
        strain_id=strain_id,
    )


class TestCgmlstProfileSchema:
    def test_cgmlst_profile_constructs(self, tmp_db_path):
        with GenomeObjectService(tmp_db_path) as gos:
            oid = gos.create(_build_object(_make_cgmlst_profile_payload())).object_id
            obj = gos.read(oid, 1)
            assert obj.payload["analysis_type"] == "cgmlst_profile"
            assert obj.payload["scheme"] == "senterica_2"
            assert obj.payload["n_loci"] == 3002
            assert obj.strain_id == "SAM-TYP-001"

    def test_cgmlst_profile_missing_scheme_raises(self):
        payload = _make_cgmlst_profile_payload(omit=("scheme",))
        with pytest.raises(GOMValidationError, match="scheme"):
            _build_object(payload)

    def test_cgmlst_profile_missing_n_loci_raises(self):
        payload = _make_cgmlst_profile_payload(omit=("n_loci",))
        with pytest.raises(GOMValidationError, match="n_loci"):
            _build_object(payload)


class TestCgmlstCohortSchema:
    def test_cgmlst_cohort_constructs(self, tmp_db_path):
        with GenomeObjectService(tmp_db_path) as gos:
            oid = gos.create(
                _build_object(
                    _make_cgmlst_cohort_payload(),
                    strain_id=CGMLST_COHORT_STRAIN_ID,
                )
            ).object_id
            obj = gos.read(oid, 1)
            assert obj.payload["analysis_type"] == "cgmlst_cohort"
            assert obj.payload["scheme"] == "senterica_2"
            assert obj.payload["n_loci"] == 3002
            assert "SAM-001|SAM-002" in obj.payload["allele_distances"]
            assert "tree_newick" in obj.payload
            assert obj.strain_id == CGMLST_COHORT_STRAIN_ID

    def test_cgmlst_cohort_missing_scheme_raises(self):
        payload = _make_cgmlst_cohort_payload(omit=("scheme",))
        with pytest.raises(GOMValidationError, match="scheme"):
            _build_object(payload, strain_id=CGMLST_COHORT_STRAIN_ID)

    def test_cgmlst_cohort_missing_n_loci_raises(self):
        payload = _make_cgmlst_cohort_payload(omit=("n_loci",))
        with pytest.raises(GOMValidationError, match="n_loci"):
            _build_object(payload, strain_id=CGMLST_COHORT_STRAIN_ID)

    def test_cgmlst_cohort_missing_allele_distances_raises(self):
        payload = _make_cgmlst_cohort_payload(omit=("allele_distances",))
        with pytest.raises(GOMValidationError, match="allele_distances"):
            _build_object(payload, strain_id=CGMLST_COHORT_STRAIN_ID)


class TestSnpCohortRegression:
    """Existing SNP cohort ANALYSIS objects must still validate after the
    cgMLST validator is wired into __post_init__ (mirrors the pattern in
    tests/unit/test_cohort_ingest.py:20-69)."""

    @staticmethod
    def _make_snp_summary(n_samples: int = 3) -> dict:
        samples = [f"SAM-{i:03d}" for i in range(1, n_samples + 1)]
        distances = {}
        for i in range(len(samples)):
            for j in range(i + 1, len(samples)):
                distances[f"{samples[i]}|{samples[j]}"] = (i + 1) * 100 + j
        return {
            "tree_newick": f"({samples[0]}:0.01,{samples[1]}:0.02,{samples[2]}:0.03);",
            "n_snp_sites": 50000,
            "n_samples": n_samples,
            "samples": samples,
            "pairwise_distances": distances,
            "missing_rate": 0.03,
        }

    def test_snp_cohort_object_still_validates(self, tmp_db_path):
        snp_data = self._make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = str(uuid4())
            gos.create(
                GenomeObject(
                    object_id=oid,
                    object_type=ObjectType.ANALYSIS,
                    version=1,
                    schema_version="0.1.0",
                    created_at=_now(),
                    created_by="snp-pipeline",
                    payload={
                        "analysis_type": "snp_cohort",
                        "samples": snp_data["samples"],
                        "n_samples": snp_data["n_samples"],
                        "n_snp_sites": snp_data["n_snp_sites"],
                        "missing_rate": snp_data["missing_rate"],
                        "tree_newick": snp_data["tree_newick"],
                        "pairwise_distances": snp_data["pairwise_distances"],
                    },
                    pipeline_version=SNP_PIPELINE_VERSION,
                    database_versions={"reference": "NC_003197.2"},
                    organism="Salmonella enterica",
                    strain_id=SNP_COHORT_STRAIN_ID,
                )
            )
            obj = gos.read(oid, 1)
            assert obj.payload["analysis_type"] == "snp_cohort"
            assert obj.payload["n_snp_sites"] == 50000
            assert "SAM-001|SAM-002" in obj.payload["pairwise_distances"]

    def test_non_cgmlst_analysis_type_without_analysis_type_key_is_noop(self, tmp_db_path):
        with GenomeObjectService(tmp_db_path) as gos:
            oid = str(uuid4())
            gos.create(
                GenomeObject(
                    object_id=oid,
                    object_type=ObjectType.ANALYSIS,
                    version=1,
                    schema_version="0.1.0",
                    created_at=_now(),
                    created_by="amr-pipeline",
                    payload={"strain_id": "SAM-001", "amr_findings": []},
                    pipeline_version="amr-pipeline-v0.2",
                    database_versions={"card": "3.3.0"},
                    organism="Salmonella enterica",
                    strain_id="SAM-001",
                )
            )
            obj = gos.read(oid, 1)
            assert obj.payload["amr_findings"] == []
