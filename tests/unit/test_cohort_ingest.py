"""Tests for cohort-level SNP result ingestion into GOM."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from bacmap.store.genome_object_service import (
    GenomeObject,
    GenomeObjectService,
    ObjectType,
)

COHORT_STRAIN_ID = "cohort:salmonella-snp"
SNP_PIPELINE_VERSION = "snp-pipeline-v0.3"


def _make_snp_summary(n_samples: int = 3) -> dict:
    samples = [f"SAM-{i:03d}" for i in range(1, n_samples + 1)]
    distances = {}
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            key = f"{samples[i]}|{samples[j]}"
            distances[key] = (i + 1) * 100 + j
    return {
        "tree_newick": f"({samples[0]}:0.01,{samples[1]}:0.02,{samples[2]}:0.03);",
        "n_snp_sites": 50000,
        "n_samples": n_samples,
        "samples": samples,
        "pairwise_distances": distances,
        "missing_rate": 0.03,
    }


def _create_cohort_object(
    gos: GenomeObjectService,
    snp_data: dict,
    version: int = 1,
    pipeline_version: str = SNP_PIPELINE_VERSION,
) -> str:
    object_id = str(uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    obj = GenomeObject(
        object_id=object_id,
        object_type=ObjectType.ANALYSIS,
        version=version,
        schema_version="0.1.0",
        created_at=now,
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
        pipeline_version=pipeline_version,
        database_versions={"reference": "NC_003197.2"},
        tool_versions={"bwa": "0.7.17", "iqtree": "3.1.2"},
        organism="Salmonella enterica",
        strain_id=COHORT_STRAIN_ID,
    )
    gos.create(obj)
    return object_id


class TestCohortSNPIngest:
    def test_create_cohort_object(self, tmp_db_path):
        snp_data = _make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, snp_data)
            obj = gos.read(oid, 1)
            assert obj.object_type == ObjectType.ANALYSIS
            assert obj.strain_id == COHORT_STRAIN_ID
            assert obj.organism == "Salmonella enterica"
            assert obj.pipeline_version == SNP_PIPELINE_VERSION
            assert obj.payload["analysis_type"] == "snp_cohort"
            assert obj.payload["n_samples"] == 3
            assert obj.payload["n_snp_sites"] == 50000
            assert "SAM-001|SAM-002" in obj.payload["pairwise_distances"]
            assert "tree_newick" in obj.payload

    def test_cohort_dedup_by_strain_id(self, tmp_db_path):
        snp_data = _make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            _create_cohort_object(gos, snp_data)
            cohort_objs = [
                o for o in gos.list_by_type(ObjectType.ANALYSIS) if o.strain_id == COHORT_STRAIN_ID
            ]
            assert len(cohort_objs) == 1

    def test_snp_finished_event(self, tmp_db_path):
        snp_data = _make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, snp_data)
            gos.log_event(
                oid,
                "snp_finished",
                {
                    "n_samples": snp_data["n_samples"],
                    "n_snp_sites": snp_data["n_snp_sites"],
                },
            )
            events = gos.list_events(oid)
            snp_events = [e for e in events if e.event_type == "snp_finished"]
            assert len(snp_events) == 1
            assert snp_events[0].event_payload["n_samples"] == 3
            assert snp_events[0].event_payload["n_snp_sites"] == 50000

    def test_link_sample_to_cohort(self, tmp_db_path):
        snp_data = _make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            cohort_oid = _create_cohort_object(gos, snp_data)

            sample_oid = str(uuid4())
            now = datetime.now(UTC).replace(tzinfo=None)
            gos.create(
                GenomeObject(
                    object_id=sample_oid,
                    object_type=ObjectType.ANALYSIS,
                    version=1,
                    schema_version="0.1.0",
                    created_at=now,
                    created_by="salmonella-pipeline",
                    payload={"strain_id": "SAM-001"},
                    pipeline_version="salmonella-workflow-v0.1",
                    database_versions={"card": "2026-Apr-3"},
                    organism="Salmonella enterica",
                    strain_id="SAM-001",
                )
            )

            gos.log_event(
                sample_oid,
                "snp_finished",
                {
                    "cohort_object_id": cohort_oid,
                    "strain_id": "SAM-001",
                },
            )

            events = gos.list_events(sample_oid)
            snp_evts = [e for e in events if e.event_type == "snp_finished"]
            assert len(snp_evts) == 1
            assert snp_evts[0].event_payload["cohort_object_id"] == cohort_oid

    def test_cohort_versioning(self, tmp_db_path):
        snp_data = _make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, snp_data, version=1)

            snp_data_v2 = _make_snp_summary()
            snp_data_v2["n_snp_sites"] = 60000
            gos.create_new_version(
                oid,
                {
                    "analysis_type": "snp_cohort",
                    "samples": snp_data_v2["samples"],
                    "n_samples": snp_data_v2["n_samples"],
                    "n_snp_sites": 60000,
                    "missing_rate": snp_data_v2["missing_rate"],
                    "tree_newick": snp_data_v2["tree_newick"],
                    "pairwise_distances": snp_data_v2["pairwise_distances"],
                },
                pipeline_version="snp-pipeline-v0.4",
                database_versions={"reference": "NC_003197.2"},
            )

            assert gos.get_latest_version(oid) == 2
            v1 = gos.read(oid, 1)
            v2 = gos.read(oid, 2)
            assert v1.payload["n_snp_sites"] == 50000
            assert v2.payload["n_snp_sites"] == 60000
            assert v1.pipeline_version == SNP_PIPELINE_VERSION
            assert v2.pipeline_version == "snp-pipeline-v0.4"

    def test_cohort_file_artifacts(self, tmp_db_path, tmp_path):
        import hashlib

        snp_data = _make_snp_summary()
        treefile = tmp_path / "core.treefile"
        treefile.write_text(snp_data["tree_newick"])
        sha = hashlib.sha256(treefile.read_bytes()).hexdigest()
        size = treefile.stat().st_size

        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, snp_data)
            gos.register_file_artifact(
                object_id=oid,
                version=1,
                file_type="snp_tree_newick",
                file_path=treefile,
                sha256=sha,
                size_bytes=size,
            )
            artifacts = gos.list_file_artifacts(oid, 1)
            assert len(artifacts) == 1
            assert artifacts[0].file_type == "snp_tree_newick"
            assert artifacts[0].sha256 == sha

    def test_cohort_query_by_strain_id(self, tmp_db_path):
        snp_data = _make_snp_summary()
        with GenomeObjectService(tmp_db_path) as gos:
            _create_cohort_object(gos, snp_data)

            for o in gos.list_by_type(ObjectType.ANALYSIS):
                if o.strain_id == COHORT_STRAIN_ID:
                    assert o.payload["analysis_type"] == "snp_cohort"
                    assert o.payload["n_samples"] == 3
                    return
            pytest.fail("Cohort object not found by strain_id query")

    def test_tree_newick_roundtrip(self, tmp_db_path):
        complex_newick = "((A:0.1,B:0.2)100:0.3,(C:0.4,D:0.5)95:0.6);"
        snp_data = _make_snp_summary()
        snp_data["tree_newick"] = complex_newick
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, snp_data)
            obj = gos.read(oid, 1)
            assert obj.payload["tree_newick"] == complex_newick

    def test_pairwise_distances_integrity(self, tmp_db_path):
        n = 5
        snp_data = _make_snp_summary(n)
        with GenomeObjectService(tmp_db_path) as gos:
            oid = _create_cohort_object(gos, snp_data)
            obj = gos.read(oid, 1)
            distances = obj.payload["pairwise_distances"]
            expected_pairs = n * (n - 1) // 2
            assert len(distances) == expected_pairs
