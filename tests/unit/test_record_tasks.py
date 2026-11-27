"""记录类任务（v1.7）：元数据 / 化验结果 / 知识库导入与审核——写操作仍只经任务层。

ADR-07 不变式：这些写入只能通过任务提交（CLI/Web/内部 API 都不能直写 store）。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.tasks.records import (
    BatchRecord,
    KnowledgeImport,
    LabResultRecord,
    MetadataRecord,
    RecordKind,
    SpecimenAssign,
    parse_record,
)
from bacmap.tasks.spec import TaskState, TaskType


def _wait(engine, tid, timeout: float = 60.0):
    deadline = time.time() + timeout
    st = engine.status(tid)
    while time.time() < deadline and st.state == TaskState.RUNNING:
        time.sleep(0.2)
        st = engine.status(tid)
    return st


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    e = eng.DbosTaskEngine(tmp_path)
    yield e
    eng.shutdown_dbos()


class TestRecordModels:
    def test_metadata_requires_ids_and_known_fields_pass(self):
        m = MetadataRecord(
            kind=RecordKind.METADATA, strain_id="S1", sample_id="S1",
            fields={"province": "Guangdong", "sample_source": "food"},
        )
        assert parse_record(m.model_dump()).kind == RecordKind.METADATA

    def test_unknown_field_rejected(self):
        with pytest.raises(ValueError):
            MetadataRecord.model_validate(
                {"kind": "metadata", "strain_id": "S1", "sample_id": "S1", "fields": {"nope": 1}}
            )

    def test_lab_requires_core_fields(self):
        with pytest.raises(ValueError):
            LabResultRecord(kind=RecordKind.LAB_RESULT, strain_id="S1", category="", test_name="", result="")

    def test_knowledge_import_requires_title(self):
        with pytest.raises(ValueError):
            KnowledgeImport(kind=RecordKind.KNOWLEDGE_IMPORT, title="")

    def test_specimen_assign_requires_target(self):
        with pytest.raises(ValueError):
            SpecimenAssign(specimen_id="A03-SN-001")
        model = parse_record(
            {"kind": "specimen_assign", "specimen_id": "A03-SN-001", "isolates": ["ISO-1"]}
        )
        assert isinstance(model, SpecimenAssign)

    def test_batch_requires_rows_and_parses_nested_kinds(self):
        with pytest.raises(ValueError):
            BatchRecord(rows=[])
        model = parse_record(
            {
                "kind": "batch",
                "rows": [
                    {
                        "kind": "metadata",
                        "strain_id": "S1",
                        "fields": {"province": "Guangdong"},
                        "extra": {"custom_lab_field": "x"},
                    },
                    {
                        "kind": "lab_result",
                        "strain_id": "S1",
                        "category": "mic",
                        "test_name": "meropenem",
                        "result": "0.25",
                        "extra": {"panel": "A"},
                    },
                ],
            }
        )
        assert isinstance(model, BatchRecord) and len(model.rows) == 2

    def test_discriminated_parsing(self):
        model = parse_record(
            {"kind": "knowledge_import", "title": "T", "content": "c", "identifier": "PMID:1"}
        )
        assert model.kind == RecordKind.KNOWLEDGE_IMPORT
        assert isinstance(model, KnowledgeImport)
        with pytest.raises(ValueError, match="kind"):
            parse_record({"kind": "nope"})


class TestRecordWorkflow:
    def test_metadata_written_and_task_succeeds(self, engine):
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "metadata",
                "strain_id": "S1",
                "sample_id": "S1",
                "fields": {"province": "Guangdong", "sample_source": "food"},
            },
            "cli:ann",
        )
        st = _wait(engine, tid)
        assert st.state is TaskState.SUCCEEDED, st.message
        from bacmap.store.strain_metadata import StrainMetadataService

        meta = StrainMetadataService(engine.home / "data" / "bacmap.sqlite").get("S1")
        assert meta is not None and meta.province == "Guangdong"

    def test_specimen_assign_written(self, engine):
        cfg = engine.home / "workflows" / "bacmap" / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "samples.tsv").write_text(
            "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform\tchecksum\n"
            "DS-1\tSAL\t\t\t\ta.fasta\tISO-1\tunknown\t\n",
            encoding="utf-8",
        )
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "specimen_assign",
                "specimen_id": "A03-SN-001",
                "datasets": ["DS-1"],
            },
            "mcp:agent",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        with IsolateService(db) as isolates:
            assert isolates.get("ISO-1")["specimen_id"] == "A03-SN-001"
        with SpecimenService(db) as specimens:
            assert specimens.get("A03-SN-001") is not None

    def test_lab_result_written(self, engine):
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "lab_result",
                "strain_id": "S1",
                "category": "mic",
                "test_name": "meropenem",
                "result": "0.25",
                "unit": "mg/L",
            },
            "web:lab",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        from bacmap.store.lab_results import LabResultService

        rows = LabResultService(engine.home / "data" / "bacmap.sqlite").get_by_strain(
            "S1", "mic"
        )
        assert rows and rows[0].result == "0.25"

    def test_batch_record_writes_specimen_and_library_layers(self, engine):
        cfg = engine.home / "workflows" / "bacmap" / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "samples.tsv").write_text(
            "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
            "\tchecksum\tspecimen\n"
            "LIB-1\tSAL\t\t\t\ta.fasta\tISO-1\tilm\t\tSP-1\n",
            encoding="utf-8",
        )
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-1")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-1", specimen_id="SP-1")
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "batch",
                "rows": [
                    {
                        "kind": "specimen_metadata",
                        "specimen_id": "SP-1",
                        "data": {"patient_name": "张三", "collection_date": "2026-10-01"},
                    },
                    {
                        "kind": "library_metadata",
                        "library_id": "LIB-1",
                        "data": {"platform": "illumina"},
                    },
                    {
                        "kind": "lab_result",
                        "strain_id": "SP-1",
                        "subject_type": "specimen",
                        "subject_id": "SP-1",
                        "category": "mngs",
                        "test_name": "blaCTX-M",
                        "result": "positive",
                    },
                ],
            },
            "cli:import",
        )
        st = _wait(engine, tid)
        assert st.state is TaskState.SUCCEEDED, st.message
        from bacmap.store.lab_results import LabResultService
        from bacmap.store.library_metadata import LibraryMetadataService
        from bacmap.store.specimen_metadata import SpecimenMetadataService

        specimen = SpecimenMetadataService(db).get("SP-1")
        assert specimen is not None and specimen["patient_name"] == "张三"
        library = LibraryMetadataService(db).get("LIB-1")
        assert library is not None and library["data"]["platform"] == "illumina"
        assert library["isolate_id"] == "ISO-1"
        labs = LabResultService(db).get_by_subject("specimen", "SP-1")
        assert labs and labs[0].result == "positive"

    def test_batch_record_writes_metadata_lab_and_extra(self, engine):
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "batch",
                "rows": [
                    {
                        "kind": "metadata",
                        "strain_id": "S1",
                        "fields": {"province": "Guangdong"},
                        "extra": {"custom_field": "kept"},
                    },
                    {
                        "kind": "lab_result",
                        "strain_id": "S1",
                        "category": "mic",
                        "test_name": "meropenem",
                        "result": "0.25",
                        "extra": {"panel": "A"},
                    },
                ],
            },
            "cli:import",
        )
        st = _wait(engine, tid)
        assert st.state is TaskState.SUCCEEDED, st.message
        from bacmap.store.lab_results import LabResultService
        from bacmap.store.strain_metadata import StrainMetadataService

        db = engine.home / "data" / "bacmap.sqlite"
        meta = StrainMetadataService(db).get("S1")
        assert meta is not None and meta.province == "Guangdong"
        assert meta.extra["custom_field"] == "kept"
        lab = LabResultService(db).get_by_strain("S1")
        assert lab and lab[0].result == "0.25" and lab[0].extra["panel"] == "A"




    def test_specimen_and_isolate_create_with_owner(self, engine):
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "specimen_create",
                "specimen_id": "SP-NEW",
                "origin": "manual",
                "note": "new",
                "owner_user_id": "alice",
            },
            "web:reviewer",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with SpecimenService(db) as store:
            row = store.get("SP-NEW")
            assert row is not None and row["owner_user_id"] == "alice"
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "isolate_create",
                "isolate_id": "ISO-NEW",
                "specimen_id": "SP-NEW",
                "owner_user_id": "alice",
            },
            "web:reviewer",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with IsolateService(db) as store:
            row = store.get("ISO-NEW")
            assert row is not None and row["specimen_id"] == "SP-NEW"

    def test_owner_claim_only_touches_unowned_entities(self, engine):
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-OWN")
            specimens.ensure("SP-OTHER", owner_user_id="bob")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-OWN", specimen_id="SP-OWN")
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "specimen_metadata",
                "specimen_id": "SP-OWN",
                "data": {"province": "广东"},
                "owner_user_id": "alice",
            },
            "web:reviewer",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with SpecimenService(db) as specimens:
            assert specimens.get("SP-OWN")["owner_user_id"] == "alice"
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "specimen_metadata",
                "specimen_id": "SP-OTHER",
                "data": {"province": "广西"},
                "owner_user_id": "alice",
            },
            "web:reviewer",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with SpecimenService(db) as specimens:
            assert specimens.get("SP-OTHER")["owner_user_id"] == "bob"
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "metadata",
                "strain_id": "ISO-OWN",
                "sample_id": "SP-OWN",
                "fields": {"province": "广东"},
                "owner_user_id": "alice",
            },
            "web:reviewer",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with IsolateService(db) as isolates:
            assert isolates.get("ISO-OWN")["owner_user_id"] == "alice"

    def test_metadata_replace_and_delete(self, engine):
        db = engine.home / "data" / "bacmap.sqlite"
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "metadata",
                "strain_id": "S1",
                "sample_id": "S1",
                "fields": {"province": "Guangdong"},
                "extra": {"custom": "old"},
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "metadata",
                "strain_id": "S1",
                "sample_id": "S1",
                "fields": {"city": "Shenzhen"},
                "extra": {},
                "replace": True,
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        from bacmap.store.strain_metadata import StrainMetadataService

        with StrainMetadataService(db) as store:
            meta = store.get("S1")
            assert meta is not None
            assert meta.city == "Shenzhen"
            assert meta.province in ("", None)
            assert meta.extra == {}
            tid = engine.submit(
                TaskType.RECORD,
                {"kind": "metadata_delete", "strain_id": "S1"},
                "web:edit",
            )
            assert _wait(engine, tid).state is TaskState.SUCCEEDED
            assert store.get("S1") is None

    def test_specimen_metadata_replace_and_delete(self, engine):
        from bacmap.store.specimen_metadata import SpecimenMetadataService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-EDIT")
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "specimen_metadata",
                "specimen_id": "SP-EDIT",
                "data": {"patient_name": "张三", "province": "广东"},
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "specimen_metadata",
                "specimen_id": "SP-EDIT",
                "data": {"province": "广西"},
                "replace": True,
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with SpecimenMetadataService(db) as store:
            assert store.get("SP-EDIT") == {"province": "广西"}
            tid = engine.submit(
                TaskType.RECORD,
                {
                    "kind": "specimen_metadata_delete",
                    "specimen_id": "SP-EDIT",
                },
                "web:edit",
            )
            assert _wait(engine, tid).state is TaskState.SUCCEEDED
            assert store.get("SP-EDIT") is None

    def test_library_metadata_replace_and_delete(self, engine):
        cfg = engine.home / "workflows" / "bacmap" / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "samples.tsv").write_text(
            "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
            "\tchecksum\tspecimen\n"
            "LIB-EDIT\tSAL\t\t\t\ta.fasta\tISO-EDIT\tilm\t\tSP-EDIT\n",
            encoding="utf-8",
        )
        from bacmap.store.isolates import IsolateService
        from bacmap.store.library_metadata import LibraryMetadataService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-EDIT")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-EDIT", specimen_id="SP-EDIT")
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "library_metadata",
                "library_id": "LIB-EDIT",
                "data": {"platform": "illumina", "run_id": "R1"},
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "library_metadata",
                "library_id": "LIB-EDIT",
                "data": {"run_id": "R2"},
                "replace": True,
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        with LibraryMetadataService(db) as store:
            row = store.get("LIB-EDIT")
            assert row is not None and row["data"] == {"run_id": "R2"}
            tid = engine.submit(
                TaskType.RECORD,
                {"kind": "library_metadata_delete", "library_id": "LIB-EDIT"},
                "web:edit",
            )
            assert _wait(engine, tid).state is TaskState.SUCCEEDED
            assert store.get("LIB-EDIT") is None

    def test_lab_result_update_and_delete(self, engine):
        db = engine.home / "data" / "bacmap.sqlite"
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "lab_result",
                "strain_id": "S1",
                "category": "mic",
                "test_name": "meropenem",
                "result": "0.25",
            },
            "web:edit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        from bacmap.store.lab_results import LabResultService

        with LabResultService(db) as store:
            row = store.get_by_strain("S1", "mic")[0]
            tid = engine.submit(
                TaskType.RECORD,
                {
                    "kind": "lab_result_update",
                    "result_id": row.id,
                    "result": "1.0",
                    "notes": "rechecked",
                    "extra": {"panel": "B"},
                },
                "web:edit",
            )
            assert _wait(engine, tid).state is TaskState.SUCCEEDED
            updated = store.get_by_id(row.id)
            assert updated is not None
            assert updated.result == "1.0" and updated.notes == "rechecked"
            assert updated.extra == {"panel": "B"}
            tid = engine.submit(
                TaskType.RECORD,
                {"kind": "lab_result_delete", "result_id": row.id},
                "web:edit",
            )
            assert _wait(engine, tid).state is TaskState.SUCCEEDED
            assert store.get_by_id(row.id) is None

    def test_knowledge_import_then_approve(self, engine):
        tid = engine.submit(
            TaskType.RECORD,
            {
                "kind": "knowledge_import",
                "title": "Outbreak paper",
                "content": "cluster",
                "identifier": "PMID:123",
            },
            "cli:lit",
        )
        assert _wait(engine, tid).state is TaskState.SUCCEEDED
        from bacmap.store.knowledge import KnowledgeStore

        store = KnowledgeStore(engine.home / "data" / "knowledge.sqlite")
        hits = store.search("outbreak")
        assert hits and hits[0]["approved_by"] is None  # 入暂存，未人审

        tid2 = engine.submit(
            TaskType.RECORD,
            {"kind": "knowledge_approve", "entry_id": int(hits[0]["id"])},
            "cli:ann",
        )
        assert _wait(engine, tid2).state is TaskState.SUCCEEDED
        assert store.known_citations() == ["PMID:123"]

    def test_invalid_payload_rejected_at_submit(self, engine):
        with pytest.raises(ValueError, match="invalid record"):
            engine.submit(TaskType.RECORD, {"kind": "metadata"}, "cli")
        with pytest.raises(ValueError):
            engine.submit(TaskType.RECORD, {"kind": "bogus"}, "cli")

    def test_unknown_knowledge_entry_fails_task(self, engine):
        tid = engine.submit(
            TaskType.RECORD, {"kind": "knowledge_approve", "entry_id": 9999}, "cli"
        )
        st = _wait(engine, tid)
        assert st.state is TaskState.FAILED and "9999" in (st.message or "")


class TestNoDirectWriteBypass:
    def test_record_task_is_not_plannable(self):
        from bacmap.tasks.params import PlannableTask

        assert "record" not in str(PlannableTask)
        with pytest.raises(ValueError):
            from pydantic import TypeAdapter

            TypeAdapter(PlannableTask).validate_python({"task_type": "record"})


class TestKnowledgeApprovalOnce:
    def test_second_approval_task_fails_without_overwriting(self, engine):
        from bacmap.store.knowledge import KnowledgeStore

        store = KnowledgeStore(engine.home / "data" / "knowledge.sqlite")
        eid = store.import_candidate({"title": "t", "identifier": "PMID:12345678"}, "a")
        first = engine.submit(
            TaskType.RECORD, {"kind": "knowledge_approve", "entry_id": eid}, "reviewer-1"
        )
        _wait(engine, first)
        second = engine.submit(
            TaskType.RECORD, {"kind": "knowledge_approve", "entry_id": eid}, "reviewer-2"
        )
        st = _wait(engine, second)
        assert st.state.value == "failed"
        assert "already approved" in (st.message or "")
        assert store.get(eid)["approved_by"] == "reviewer-1"
