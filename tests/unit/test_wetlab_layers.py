"""四层湿实验存储（v1.10.52）：specimen / isolate / library / lab。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.store.isolates import IsolateService
from bacmap.store.lab_results import LabResultService
from bacmap.store.library_metadata import LibraryMetadataService
from bacmap.store.specimen_metadata import SpecimenMetadataService
from bacmap.store.specimens import SpecimenService


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "bacmap.sqlite"
    with SpecimenService(path) as specimens:
        specimens.ensure("SP-1")
    with IsolateService(path) as isolates:
        isolates.ensure("ISO-1", specimen_id="SP-1")
    return path


def test_specimen_metadata_merges_and_requires_specimen(db: Path):
    with SpecimenMetadataService(db) as svc:
        svc.upsert("SP-1", {"patient_name": "张三"})
        merged = svc.upsert("SP-1", {"collection_date": "2026-10-01"})
        assert merged == {"patient_name": "张三", "collection_date": "2026-10-01"}
        assert svc.get("SP-1") == merged
        with pytest.raises(KeyError):
            svc.upsert("NOPE", {"x": "y"})


def test_library_metadata_merges_and_keeps_links(db: Path):
    with LibraryMetadataService(db) as svc:
        svc.upsert("LIB-1", {"platform": "ilm"}, specimen_id="SP-1", isolate_id="ISO-1")
        merged = svc.upsert("LIB-1", {"run": "R1"}, specimen_id="SP-1", isolate_id="ISO-1")
        assert merged["data"] == {"platform": "ilm", "run": "R1"}
        row = svc.get("LIB-1")
        assert row is not None
        assert row["specimen_id"] == "SP-1" and row["isolate_id"] == "ISO-1"


def test_lab_result_subject_supports_specimen(db: Path):
    with LabResultService(db) as svc:
        svc.add(
            "SP-1",
            "mngs",
            "blaCTX-M",
            "positive",
            subject_type="specimen",
            subject_id="SP-1",
        )
        rows = svc.get_by_subject("specimen", "SP-1")
        assert rows and rows[0].subject_type == "specimen"
        assert rows[0].subject_id == "SP-1"
        assert svc.get_by_strain("SP-1") == []  # 不再把样本结果混入菌株结果


def test_delete_specimen_cleans_specimen_layers(db: Path):
    from bacmap.workflow.samples_registry import delete_specimen

    with SpecimenMetadataService(db) as svc:
        svc.upsert("SP-1", {"patient_name": "张三"})
    with LabResultService(db) as svc:
        svc.add(
            "SP-1", "mngs", "blaCTX-M", "positive",
            subject_type="specimen", subject_id="SP-1",
        )
    result = delete_specimen(db.parent.parent, "SP-1", force=True)
    assert result["deleted"] is True
    with SpecimenMetadataService(db) as svc:
        assert svc.get("SP-1") is None
    with LabResultService(db) as svc:
        assert svc.get_by_subject("specimen", "SP-1") == []
