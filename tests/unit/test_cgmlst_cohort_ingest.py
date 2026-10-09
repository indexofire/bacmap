"""Tests for cohort-level cgMLST result ingestion into GOM (todo 13).

Mirrors ``tests/unit/test_cohort_ingest.py`` fixture pattern: a
``_make_cgmlst_summary`` builder + ``_create_cohort_object`` helper +
``TestCohortCgmlstIngest`` class covering creation / dedup / versioning /
query / event logging / file artifacts. The cgMLST variant exercises the
``cgmlst_cohort`` validator added in todo 2 (scheme + n_loci +
allele_distances required).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from bacmap.store.genome_object_service import (
    GenomeObject,
    GenomeObjectService,
    GOMValidationError,
    ObjectType,
)

COHORT_STRAIN_ID = "cohort:salmonella-cgmlst"
CGMLST_PIPELINE_VERSION = "cgmlst-pipeline-v0.1"
CGMLST_SCHEME = "senterica_2"


def _make_cgmlst_summary(n_samples: int = 3) -> dict:
    samples = [f"SAM-{i:03d}" for i in range(1, n_samples + 1)]
    allele_distances: dict[str, int] = {}
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            key = f"{samples[i]}|{samples[j]}"
            allele_distances[key] = (i + 1) * 10 + j
    return {
        "samples": samples,
        "n_samples": n_samples,
        "scheme": CGMLST_SCHEME,
        "n_loci": 3002,
        "allele_distances": allele_distances,
        "tree_newick": f"({samples[0]}:0.01,{samples[1]}:0.02,{samples[2]}:0.03);",
        "missing_rate": 0.012,
        "thresholds_applied": {"outbreak_allele_dist": 10, "related_allele_dist": 100},
        "group": "salmonella",
        "organism": "Salmonella enterica",
    }


def _create_cohort_object(
    gos: GenomeObjectService,
    cgmlst_data: dict,
    version: int = 1,
    pipeline_version: str = CGMLST_PIPELINE_VERSION,
) -> str:
    object_id = str(uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    obj = GenomeObject(
        object_id=object_id,
        object_type=ObjectType.ANALYSIS,
        version=version,
        schema_version="0.1.0",
        created_at=now,
        created_by="cgmlst-pipeline",
        payload={
            "analysis_type": "cgmlst_cohort",
            "group": cgmlst_data["group"],
            "scheme": cgmlst_data["scheme"],
            "n_loci": cgmlst_data["n_loci"],
            "samples": cgmlst_data["samples"],
            "n_samples": cgmlst_data["n_samples"],
            "allele_distances": cgmlst_data["allele_distances"],
            "tree_newick": cgmlst_data["tree_newick"],
            "missing_rate": cgmlst_data["missing_rate"],
            "thresholds_applied": cgmlst_data["thresholds_applied"],
        },
        pipeline_version=pipeline_version,
        database_versions={"cgmlst_scheme": f"{CGMLST_SCHEME}@abcd1234ef56"},
        tool_versions={"gmlst": "0.1.1"},
        organism="Salmonella enterica",
        strain_id=COHORT_STRAIN_ID,
    )
    gos.create(obj)
    return object_id


class TestCohortCgmlstIngest:
    def test_create_cohort_object(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, cgmlst_data)
            obj = gos.read(oid, 1)
            assert obj.object_type == ObjectType.ANALYSIS
            assert obj.strain_id == COHORT_STRAIN_ID
            assert obj.organism == "Salmonella enterica"
            assert obj.pipeline_version == CGMLST_PIPELINE_VERSION
            assert obj.payload["analysis_type"] == "cgmlst_cohort"
            assert obj.payload["scheme"] == CGMLST_SCHEME
            assert obj.payload["n_loci"] == 3002
            assert obj.payload["n_samples"] == 3
            assert "SAM-001|SAM-002" in obj.payload["allele_distances"]
            assert "tree_newick" in obj.payload
            assert obj.payload["allele_distances"]["SAM-001|SAM-002"] == 11

    def test_cohort_dedup_by_strain_id(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            _create_cohort_object(gos, cgmlst_data)
            cohort_objs = [
                o for o in gos.list_by_type(ObjectType.ANALYSIS) if o.strain_id == COHORT_STRAIN_ID
            ]
            assert len(cohort_objs) == 1

    def test_mlst_finished_event(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, cgmlst_data)
            gos.log_event(
                oid,
                "mlst_finished",
                {
                    "group": "salmonella",
                    "scheme": cgmlst_data["scheme"],
                    "n_samples": cgmlst_data["n_samples"],
                    "n_loci": cgmlst_data["n_loci"],
                },
            )
            events = gos.list_events(oid)
            mlst_events = [e for e in events if e.event_type == "mlst_finished"]
            assert len(mlst_events) == 1
            assert mlst_events[0].event_payload["scheme"] == CGMLST_SCHEME
            assert mlst_events[0].event_payload["n_loci"] == 3002

    def test_cohort_versioning(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, cgmlst_data, version=1)

            cgmlst_data_v2 = _make_cgmlst_summary()
            cgmlst_data_v2["n_loci"] = 3005
            gos.create_new_version(
                oid,
                {
                    "analysis_type": "cgmlst_cohort",
                    "group": cgmlst_data_v2["group"],
                    "scheme": cgmlst_data_v2["scheme"],
                    "n_loci": 3005,
                    "samples": cgmlst_data_v2["samples"],
                    "n_samples": cgmlst_data_v2["n_samples"],
                    "allele_distances": cgmlst_data_v2["allele_distances"],
                    "tree_newick": cgmlst_data_v2["tree_newick"],
                    "missing_rate": cgmlst_data_v2["missing_rate"],
                    "thresholds_applied": cgmlst_data_v2["thresholds_applied"],
                },
                pipeline_version="cgmlst-pipeline-v0.2",
                database_versions={"cgmlst_scheme": f"{CGMLST_SCHEME}@newhash0000"},
            )

            assert gos.get_latest_version(oid) == 2
            v1 = gos.read(oid, 1)
            v2 = gos.read(oid, 2)
            assert v1.payload["n_loci"] == 3002
            assert v2.payload["n_loci"] == 3005
            assert v1.pipeline_version == CGMLST_PIPELINE_VERSION
            assert v2.pipeline_version == "cgmlst-pipeline-v0.2"

    def test_cohort_file_artifacts(self, tmp_db_path, tmp_path):
        cgmlst_data = _make_cgmlst_summary()
        treefile = tmp_path / "core.treefile"
        treefile.write_text(cgmlst_data["tree_newick"])
        sha = hashlib.sha256(treefile.read_bytes()).hexdigest()
        size = treefile.stat().st_size

        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, cgmlst_data)
            gos.register_file_artifact(
                object_id=oid,
                version=1,
                file_type="cgmlst_tree_newick",
                file_path=treefile,
                sha256=sha,
                size_bytes=size,
            )
            artifacts = gos.list_file_artifacts(oid, 1)
            assert len(artifacts) == 1
            assert artifacts[0].file_type == "cgmlst_tree_newick"
            assert artifacts[0].sha256 == sha

    def test_cohort_query_by_strain_id(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            _create_cohort_object(gos, cgmlst_data)

            for o in gos.list_by_type(ObjectType.ANALYSIS):
                if o.strain_id == COHORT_STRAIN_ID:
                    assert o.payload["analysis_type"] == "cgmlst_cohort"
                    assert o.payload["n_samples"] == 3
                    assert o.payload["scheme"] == CGMLST_SCHEME
                    return
            pytest.fail("cgMLST cohort object not found by strain_id query")

    def test_tree_newick_roundtrip(self, tmp_db_path):
        complex_newick = "((A:0.1,B:0.2)100:0.3,(C:0.4,D:0.5)95:0.6);"
        cgmlst_data = _make_cgmlst_summary()
        cgmlst_data["tree_newick"] = complex_newick
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, cgmlst_data)
            obj = gos.read(oid, 1)
            assert obj.payload["tree_newick"] == complex_newick

    def test_allele_distances_integrity(self, tmp_db_path):
        n = 5
        cgmlst_data = _make_cgmlst_summary(n)
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, cgmlst_data)
            obj = gos.read(oid, 1)
            distances = obj.payload["allele_distances"]
            expected_pairs = n * (n - 1) // 2
            assert len(distances) == expected_pairs

    def test_validator_rejects_missing_scheme(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        payload = {
            "analysis_type": "cgmlst_cohort",
            "group": cgmlst_data["group"],
            "n_loci": cgmlst_data["n_loci"],
            "samples": cgmlst_data["samples"],
            "n_samples": cgmlst_data["n_samples"],
            "allele_distances": cgmlst_data["allele_distances"],
        }
        with GenomeObjectService(tmp_db_path) as gos:
            with pytest.raises(GOMValidationError):
                gos.create(
                    GenomeObject(
                        object_id=str(uuid4()),
                        object_type=ObjectType.ANALYSIS,
                        version=1,
                        schema_version="0.1.0",
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                        created_by="cgmlst-pipeline",
                        payload=payload,
                        pipeline_version=CGMLST_PIPELINE_VERSION,
                        database_versions={"cgmlst_scheme": "unversioned"},
                        tool_versions={"gmlst": "0.1.1"},
                        organism="Salmonella enterica",
                        strain_id=COHORT_STRAIN_ID,
                    )
                )

    def test_validator_rejects_missing_allele_distances(self, tmp_db_path):
        cgmlst_data = _make_cgmlst_summary()
        payload = {
            "analysis_type": "cgmlst_cohort",
            "group": cgmlst_data["group"],
            "scheme": cgmlst_data["scheme"],
            "n_loci": cgmlst_data["n_loci"],
            "samples": cgmlst_data["samples"],
            "n_samples": cgmlst_data["n_samples"],
        }
        with GenomeObjectService(tmp_db_path) as gos:
            with pytest.raises(GOMValidationError):
                gos.create(
                    GenomeObject(
                        object_id=str(uuid4()),
                        object_type=ObjectType.ANALYSIS,
                        version=1,
                        schema_version="0.1.0",
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                        created_by="cgmlst-pipeline",
                        payload=payload,
                        pipeline_version=CGMLST_PIPELINE_VERSION,
                        database_versions={"cgmlst_scheme": "unversioned"},
                        tool_versions={"gmlst": "0.1.1"},
                        organism="Salmonella enterica",
                        strain_id=COHORT_STRAIN_ID,
                    )
                )
