"""记录类任务（v1.7）：元数据 / 化验结果 / 知识库导入与审核——写操作仍只经任务层。

ADR-07 不变式：这些写入只能通过任务提交（CLI/Web/内部 API 都不能直写 store）。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.tasks.records import (
    KnowledgeImport,
    LabResultRecord,
    MetadataRecord,
    RecordKind,
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
