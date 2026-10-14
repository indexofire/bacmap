"""TDD 起源测试：Genome Object Service。

所有测试预期失败（NotImplementedError），直到 Sprint 1 实现完整 GOS。
覆盖 project.md §5（GOM）+ §4.4-4.6（事件/版本/Immutable）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bacmap.store.genome_object_service import (
    CompositeTriplet,
    GenomeObject,
    GenomeObjectService,
    GOMImmutableError,
    GOMNotFoundError,
    GOMValidationError,
    ObjectType,
    new_artifact_id,
    new_event_id,
    new_object_id,
)


class TestGenomeObjectSchema:
    def test_create_minimal_genome_object(self, sample_sample_object):
        assert sample_sample_object.object_type == ObjectType.SAMPLE
        assert sample_sample_object.version == 1
        assert sample_sample_object.schema_version == "0.1.0"

    def test_all_object_types_in_enum(self):
        expected = {"sample", "analysis", "report", "workflow", "plugin", "knowledge", "task"}
        actual = {t.value for t in ObjectType}
        assert actual == expected

    @pytest.mark.parametrize("invalid_type", ["", "unknown", "Sample", "ANALYSIS", "metagenome"])
    def test_invalid_object_type_rejected(self, invalid_type, fixed_object_id, now_utc):
        with pytest.raises((ValueError, GOMValidationError)):
            GenomeObject(
                object_id=fixed_object_id,
                object_type=invalid_type,  # type: ignore[arg-type]
                version=1,
                schema_version="0.1.0",
                created_at=now_utc,
                created_by="test_user",
            )

    @pytest.mark.parametrize("invalid_version", [0, -1, -100])
    def test_version_must_be_positive(self, invalid_version, fixed_object_id, now_utc):
        with pytest.raises((ValueError, GOMValidationError)):
            GenomeObject(
                object_id=fixed_object_id,
                object_type=ObjectType.SAMPLE,
                version=invalid_version,
                schema_version="0.1.0",
                created_at=now_utc,
                created_by="test_user",
            )

    @pytest.mark.parametrize("invalid_semver", ["", "v1", "1", "1.0", "v1.0.0", "abc"])
    def test_schema_version_must_be_semver(self, invalid_semver, fixed_object_id, now_utc):
        with pytest.raises((ValueError, GOMValidationError)):
            GenomeObject(
                object_id=fixed_object_id,
                object_type=ObjectType.SAMPLE,
                version=1,
                schema_version=invalid_semver,
                created_at=now_utc,
                created_by="test_user",
            )

    def test_missing_required_field_object_id(self, now_utc):
        with pytest.raises((TypeError, GOMValidationError)):
            GenomeObject(  # type: ignore[call-arg]
                object_type=ObjectType.SAMPLE,
                version=1,
                schema_version="0.1.0",
                created_at=now_utc,
                created_by="test_user",
            )

    def test_genome_object_is_frozen(self, sample_sample_object):
        with pytest.raises((AttributeError, Exception)):
            sample_sample_object.version = 2  # type: ignore[misc]


class TestCompositeTripletSchema:
    def test_create_amr_triplet(self):
        triplet = CompositeTriplet(
            subject="blaCTX-M-15",
            relation="confers_resistance_to",
            object="Cefotaxime",
            subject_attributes={"mutation_site": "Promoter -281G>A", "coverage": 99.8},
            relation_conditions={"mic": "≥64 μg/mL", "method": "in_silico_prediction"},
            object_attributes={"class": "β-lactam/3rd-gen cephalosporin"},
        )
        assert triplet.subject == "blaCTX-M-15"
        assert triplet.object == "Cefotaxime"

    def test_triplet_requires_subject(self):
        with pytest.raises((TypeError, ValueError, GOMValidationError)):
            CompositeTriplet(relation="confers_resistance_to", object="Cefotaxime")  # type: ignore[call-arg]

    def test_triplet_requires_relation(self):
        with pytest.raises((TypeError, ValueError, GOMValidationError)):
            CompositeTriplet(subject="blaCTX-M-15", object="Cefotaxime")  # type: ignore[call-arg]

    def test_triplet_requires_object(self):
        with pytest.raises((TypeError, ValueError, GOMValidationError)):
            CompositeTriplet(subject="blaCTX-M-15", relation="confers_resistance_to")  # type: ignore[call-arg]

    def test_triplet_attributes_optional(self):
        triplet = CompositeTriplet(
            subject="blaTEM-1", relation="confers_resistance_to", object="Ampicillin"
        )
        assert triplet.subject_attributes == {}
        assert triplet.relation_conditions == {}

    def test_amr_payload_uses_triplet_format(self, sample_amr_payload):
        findings = sample_amr_payload["amr_findings"]
        assert len(findings) >= 1
        for finding in findings:
            assert {"gene", "relation", "drug"} <= set(finding.keys())
            assert isinstance(finding.get("gene_attributes", {}), dict)
            assert isinstance(finding.get("relation_conditions", {}), dict)
            assert isinstance(finding.get("drug_attributes", {}), dict)


class TestEvidenceChain:
    def test_analysis_has_evidence_chain(self, sample_genome_object):
        assert sample_genome_object.strain_id is not None
        assert sample_genome_object.pipeline_version is not None
        assert sample_genome_object.database_versions != {}

    def test_analysis_missing_pipeline_version_rejected(
        self, fixed_object_id, now_utc, sample_amr_payload, sample_database_versions
    ):
        with pytest.raises(GOMValidationError):
            GenomeObject(
                object_id=fixed_object_id,
                object_type=ObjectType.ANALYSIS,
                version=1,
                schema_version="0.1.0",
                created_at=now_utc,
                created_by="test_user",
                payload=sample_amr_payload,
                pipeline_version=None,
                database_versions=sample_database_versions,
                organism="Salmonella",
                strain_id="SH2024-001",
            )

    def test_analysis_missing_database_versions_rejected(
        self, fixed_object_id, now_utc, sample_amr_payload, sample_pipeline_version
    ):
        with pytest.raises(GOMValidationError):
            GenomeObject(
                object_id=fixed_object_id,
                object_type=ObjectType.ANALYSIS,
                version=1,
                schema_version="0.1.0",
                created_at=now_utc,
                created_by="test_user",
                payload=sample_amr_payload,
                pipeline_version=sample_pipeline_version,
                database_versions={},
                organism="Salmonella",
                strain_id="SH2024-001",
            )

    def test_sample_does_not_require_evidence_chain(self, sample_sample_object):
        assert sample_sample_object.pipeline_version is None
        assert sample_sample_object.database_versions == {}

    def test_database_versions_recorded(self, sample_genome_object, sample_database_versions):
        assert sample_genome_object.database_versions["amrfinderplus_db"] == "2024-01-15.1"
        assert sample_genome_object.database_versions["card"] == "3.3.0"

    def test_tool_versions_recorded(self, sample_genome_object, sample_tool_versions):
        assert sample_genome_object.tool_versions["spades"] == "3.15.4"


class TestGenomeObjectServiceCRUD:
    def test_init_creates_database_file(self, tmp_db_path):
        GenomeObjectService(tmp_db_path)
        assert tmp_db_path.exists()

    def test_init_creates_required_tables(self, tmp_db_path):
        import sqlite3

        svc = GenomeObjectService(tmp_db_path)
        svc.close()
        with sqlite3.connect(tmp_db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "genome_objects" in tables
        assert "genome_objects_fts" in tables
        assert "events" in tables
        assert "file_artifacts" in tables

    def test_init_sets_wal_mode(self, tmp_db_path):
        import sqlite3

        svc = GenomeObjectService(tmp_db_path)
        svc.close()
        with sqlite3.connect(tmp_db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_create_and_read_roundtrip(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            created = svc.create(sample_sample_object)
            assert created.object_id == sample_sample_object.object_id
            read_back = svc.read(sample_sample_object.object_id, version=1)
            assert read_back.object_id == sample_sample_object.object_id
            assert read_back.object_type == ObjectType.SAMPLE
            assert read_back.payload["strain_id"] == "SH2024-001"

    def test_read_nonexistent_raises(self, tmp_db_path, fixed_object_id):
        with GenomeObjectService(tmp_db_path) as svc:
            with pytest.raises(GOMNotFoundError):
                svc.read("nonexistent-id", version=1)

    def test_read_nonexistent_version_raises(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            with pytest.raises(GOMNotFoundError):
                svc.read(sample_sample_object.object_id, version=99)

    def test_list_by_type(self, tmp_db_path, sample_sample_object, sample_genome_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.create(sample_genome_object)
            samples = svc.list_by_type(ObjectType.SAMPLE)
            analyses = svc.list_by_type(ObjectType.ANALYSIS)
            assert len(samples) == 1
            assert len(analyses) == 1
            assert samples[0].object_type == ObjectType.SAMPLE
            assert analyses[0].object_type == ObjectType.ANALYSIS

    def test_list_by_organism(self, tmp_db_path, sample_sample_object, sample_genome_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.create(sample_genome_object)
            salmonella = svc.list_by_organism("Salmonella")
            assert len(salmonella) == 2
            for obj in salmonella:
                assert obj.organism == "Salmonella"

    def test_list_pagination(self, tmp_db_path, sample_sample_object, fixed_object_id, now_utc):
        with GenomeObjectService(tmp_db_path) as svc:
            for i in range(10):
                obj = GenomeObject(
                    object_id=f"{fixed_object_id[:-1]}{i}",
                    object_type=ObjectType.SAMPLE,
                    version=1,
                    schema_version="0.1.0",
                    created_at=now_utc,
                    created_by="test_user",
                    payload={"strain_id": f"SH-{i}"},
                    organism="Salmonella",
                    strain_id=f"SH-{i}",
                )
                svc.create(obj)
            page1 = svc.list_by_type(ObjectType.SAMPLE, limit=5, offset=0)
            page2 = svc.list_by_type(ObjectType.SAMPLE, limit=5, offset=5)
            assert len(page1) == 5
            assert len(page2) == 5


class TestVersioning:
    def test_create_new_version(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            v2 = svc.create_new_version(
                sample_sample_object.object_id,
                payload={"strain_id": "SH2024-001", "updated": True},
            )
            assert v2.version == 2
            assert v2.object_id == sample_sample_object.object_id
            assert v2.payload["updated"] is True

    def test_old_version_preserved_after_new(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.create_new_version(
                sample_sample_object.object_id,
                payload={"strain_id": "SH2024-001", "updated": True},
            )
            v1 = svc.read(sample_sample_object.object_id, version=1)
            v2 = svc.read(sample_sample_object.object_id, version=2)
            assert "updated" not in v1.payload
            assert v2.payload["updated"] is True

    def test_same_version_overwrite_rejected(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            with pytest.raises(GOMImmutableError):
                svc.create(sample_sample_object)

    def test_get_latest_version(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            assert svc.get_latest_version(sample_sample_object.object_id) == 1
            svc.create_new_version(sample_sample_object.object_id, payload={})
            assert svc.get_latest_version(sample_sample_object.object_id) == 2
            svc.create_new_version(sample_sample_object.object_id, payload={})
            assert svc.get_latest_version(sample_sample_object.object_id) == 3

    def test_list_all_versions(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.create_new_version(sample_sample_object.object_id, payload={"v": 2})
            svc.create_new_version(sample_sample_object.object_id, payload={"v": 3})
            versions = svc.list_versions(sample_sample_object.object_id)
            assert len(versions) == 3
            assert [v.version for v in versions] == [1, 2, 3]

    def test_create_new_version_nonexistent_raises(self, tmp_db_path, fixed_object_id):
        with GenomeObjectService(tmp_db_path) as svc:
            with pytest.raises(GOMNotFoundError):
                svc.create_new_version("nonexistent-id", payload={})

    def test_delete_always_rejected(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            with pytest.raises(GOMImmutableError):
                svc.delete(sample_sample_object.object_id, version=1)

    def test_new_version_inherits_metadata(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            v2 = svc.create_new_version(
                sample_sample_object.object_id,
                payload={"new": True},
            )
            assert v2.object_type == sample_sample_object.object_type
            assert v2.schema_version == sample_sample_object.schema_version
            assert v2.created_by == sample_sample_object.created_by
            assert v2.organism == sample_sample_object.organism
            assert v2.strain_id == sample_sample_object.strain_id


class TestFileArtifacts:
    def test_register_file_artifact(self, tmp_db_path, sample_sample_object, tmp_path):
        fastq = tmp_path / "sample_R1.fastq.gz"
        fastq.write_bytes(b"@SEQ\nACGT\n+\n!!!!")
        import hashlib

        sha = hashlib.sha256(fastq.read_bytes()).hexdigest()

        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            artifact = svc.register_file_artifact(
                object_id=sample_sample_object.object_id,
                version=1,
                file_type="fastq",
                file_path=fastq,
                sha256=sha,
                size_bytes=fastq.stat().st_size,
            )
            assert artifact.file_type == "fastq"
            assert artifact.sha256 == sha

    def test_sha256_required(self, tmp_db_path, sample_sample_object, tmp_path):
        fastq = tmp_path / "sample_R1.fastq.gz"
        fastq.write_bytes(b"dummy")

        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            with pytest.raises((ValueError, GOMValidationError)):
                svc.register_file_artifact(
                    object_id=sample_sample_object.object_id,
                    version=1,
                    file_type="fastq",
                    file_path=fastq,
                    sha256="",
                    size_bytes=100,
                )

    def test_sha256_mismatch_rejected(self, tmp_db_path, sample_sample_object, tmp_path):
        fastq = tmp_path / "sample_R1.fastq.gz"
        fastq.write_bytes(b"dummy")

        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            with pytest.raises(GOMValidationError):
                svc.register_file_artifact(
                    object_id=sample_sample_object.object_id,
                    version=1,
                    file_type="fastq",
                    file_path=fastq,
                    sha256="0" * 64,
                    size_bytes=100,
                )

    def test_list_artifacts_by_object(self, tmp_db_path, sample_sample_object, tmp_path):
        f1 = tmp_path / "R1.fastq.gz"
        f2 = tmp_path / "R2.fastq.gz"
        f1.write_bytes(b"r1")
        f2.write_bytes(b"r2")
        import hashlib

        sha1 = hashlib.sha256(f1.read_bytes()).hexdigest()
        sha2 = hashlib.sha256(f2.read_bytes()).hexdigest()

        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.register_file_artifact(sample_sample_object.object_id, 1, "fastq_r1", f1, sha1, 2)
            svc.register_file_artifact(sample_sample_object.object_id, 1, "fastq_r2", f2, sha2, 2)
            artifacts = svc.list_file_artifacts(sample_sample_object.object_id)
            assert len(artifacts) == 2

    def test_register_artifact_nonexistent_object_raises(
        self, tmp_db_path, tmp_path, fixed_object_id
    ):
        f = tmp_path / "x.txt"
        f.write_bytes(b"x")
        import hashlib

        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        with GenomeObjectService(tmp_db_path) as svc:
            with pytest.raises(GOMNotFoundError):
                svc.register_file_artifact(fixed_object_id, 1, "text", f, sha, 1)


class TestEventsLog:
    def test_log_event(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            event = svc.log_event(
                sample_sample_object.object_id,
                "uploaded",
                {"filename": "sample.fastq.gz", "size_bytes": 1024000},
            )
            assert event.event_type == "uploaded"
            assert event.event_payload["filename"] == "sample.fastq.gz"

    def test_list_events_chronological(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.log_event(sample_sample_object.object_id, "uploaded", {"step": 1})
            svc.log_event(sample_sample_object.object_id, "qc_finished", {"step": 2})
            svc.log_event(sample_sample_object.object_id, "assembly_finished", {"step": 3})
            events = svc.list_events(sample_sample_object.object_id)
            assert len(events) == 3
            assert events[0].event_type == "uploaded"
            assert events[2].event_type == "assembly_finished"

    def test_list_events_since_filter(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            svc.log_event(sample_sample_object.object_id, "uploaded", {})
            cutoff = datetime.now(UTC)
            svc.log_event(sample_sample_object.object_id, "qc_finished", {})
            recent = svc.list_events(sample_sample_object.object_id, since=cutoff)
            assert len(recent) == 1
            assert recent[0].event_type == "qc_finished"

    def test_invalid_event_type_rejected(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            with pytest.raises((ValueError, GOMValidationError)):
                svc.log_event(
                    sample_sample_object.object_id,
                    "totally_invalid_type",  # type: ignore[arg-type]
                    {},
                )

    def test_event_records_standard_pipeline_lifecycle(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as svc:
            svc.create(sample_sample_object)
            for evt in [
                "uploaded",
                "qc_finished",
                "assembly_finished",
                "annotation_finished",
                "amr_finished",
                "report_generated",
            ]:
                svc.log_event(sample_sample_object.object_id, evt, {})  # type: ignore[arg-type]
            events = svc.list_events(sample_sample_object.object_id)
            assert len(events) == 6
            assert [e.event_type for e in events] == [
                "uploaded",
                "qc_finished",
                "assembly_finished",
                "annotation_finished",
                "amr_finished",
                "report_generated",
            ]


class TestFactoryFunctions:
    def test_new_object_id_is_uuid_v4(self):
        oid = new_object_id()
        assert len(oid) == 36
        assert oid[14] == "4"
        assert oid[19] in {"8", "9", "a", "b"}

    def test_new_object_id_unique(self):
        ids = {new_object_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_new_artifact_id_is_uuid_v4(self):
        aid = new_artifact_id()
        assert len(aid) == 36

    def test_new_event_id_is_uuid_v4(self):
        eid = new_event_id()
        assert len(eid) == 36


class TestSearchFtsAlignment:
    """FTS5 rowid 必须显式对齐 genome_objects.rowid（search 依赖该不变量）。"""

    def test_fts_rowid_matches_base_rowid(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as gos:
            gos.create(sample_sample_object)
            base = {r[0] for r in gos._conn.execute("SELECT rowid FROM genome_objects")}
            fts = {r[0] for r in gos._conn.execute("SELECT rowid FROM genome_objects_fts")}
            assert base == fts != set()

    def test_search_finds_by_strain_id(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as gos:
            gos.create(sample_sample_object)
            hits = gos.search("SH2024-001")
        assert [h.object_id for h in hits] == [sample_sample_object.object_id]

    def test_search_ignores_non_matching_term(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as gos:
            gos.create(sample_sample_object)
            assert gos.search("nonexistenttermzzz") == []

    def test_search_blank_query_returns_empty(self, tmp_db_path, sample_sample_object):
        with GenomeObjectService(tmp_db_path) as gos:
            gos.create(sample_sample_object)
            assert gos.search("   ") == []
