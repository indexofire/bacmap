"""存储层审计修复的回归测试（部分更新 / 空集过滤 / 空白标识符）。"""

from __future__ import annotations

from pathlib import Path

from bacmap.store.knowledge import KnowledgeStore
from bacmap.store.lab_results import LabResultService
from bacmap.store.strain_metadata import StrainMetadataService


class TestMetadataPartialUpdate:
    def test_partial_update_preserves_sample_id(self, tmp_path: Path):
        db = tmp_path / "meta.sqlite"
        with StrainMetadataService(db) as svc:
            svc.upsert("SAM-001", {"sample_id": "S-100", "patient_name": "张三"})
            assert svc.get("SAM-001").sample_id == "S-100"

            # 部分更新未带 sample_id：不得被 strain_id 覆盖
            svc.upsert("SAM-001", {"patient_name": "李四"})
            meta = svc.get("SAM-001")
            assert meta.sample_id == "S-100"
            assert meta.patient_name == "李四"

    def test_insert_defaults_sample_id_to_strain_id(self, tmp_path: Path):
        db = tmp_path / "meta.sqlite"
        with StrainMetadataService(db) as svc:
            svc.upsert("SAM-002", {"patient_name": "王五"})
            assert svc.get("SAM-002").sample_id == "SAM-002"

    def test_explicit_sample_id_update_is_honored(self, tmp_path: Path):
        db = tmp_path / "meta.sqlite"
        with StrainMetadataService(db) as svc:
            svc.upsert("SAM-003", {"sample_id": "S-1"})
            svc.upsert("SAM-003", {"sample_id": "S-2"})
            assert svc.get("SAM-003").sample_id == "S-2"


class TestLabResultsBatch:
    def test_add_batch_does_not_mutate_caller(self, tmp_path: Path):
        db = tmp_path / "lab.sqlite"
        with LabResultService(db) as svc:
            rows = [{"test_name": "AST", "result": "R", "interpretation": "耐药"}]
            svc.add_batch("SAM-1", "antibiogram", rows)
            # 调用方 dict 保持原样（不得被 pop 掉 test_name/result）
            assert rows == [{"test_name": "AST", "result": "R", "interpretation": "耐药"}]

    def test_search_explicit_empty_strain_ids_returns_nothing(self, tmp_path: Path):
        db = tmp_path / "lab.sqlite"
        with LabResultService(db) as svc:
            svc.add("SAM-1", "antibiogram", "AST", "R")
            assert svc.search(strain_ids=[]) == []
            # None 仍表示不过滤
            assert len(svc.search(strain_ids=None)) == 1
            assert len(svc.search(strain_ids=["SAM-1"])) == 1


class TestKnowledgeCitations:
    def test_whitespace_identifier_excluded(self, tmp_path: Path):
        ks = KnowledgeStore(tmp_path / "knowledge.sqlite")
        kid = ks.import_candidate(
            {
                "kind": "literature",
                "title": "空白标识符条目",
                "authors": "A",
                "year": 2024,
                "source": "S",
                "identifier": "   ",
                "content": "内容",
            },
            imported_by="tester",
        )
        ks.approve(kid, approver="curator")
        # 纯空白标识符不得进入可引用集合（否则引用门会接受空引用）
        assert ks.known_citations() == []
