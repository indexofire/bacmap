"""Tests for StrainMetadataService and LabResultService."""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.store.lab_results import LabResultService
from bacmap.store.strain_metadata import StrainMetadataService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_meta.sqlite"


# ===========================================================================
# StrainMetadataService Tests
# ===========================================================================


class TestStrainMetadataCRUD:
    def test_upsert_new(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            meta = svc.upsert(
                "SAM-001",
                {
                    "patient_name": "张三",
                    "patient_age": 35,
                    "province": "北京",
                    "isolation_date": "2024-03-10",
                },
            )
            assert meta.strain_id == "SAM-001"
            assert meta.patient_name == "张三"
            assert meta.patient_age == 35
            assert meta.province == "北京"

    def test_upsert_update(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"patient_name": "张三", "province": "北京"})
            svc.upsert("SAM-001", {"patient_name": "李四"})
            meta = svc.get("SAM-001")
            assert meta.patient_name == "李四"
            assert meta.province == "北京"

    def test_get_nonexistent(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            assert svc.get("NONEXIST") is None

    def test_delete(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"patient_name": "张三"})
            assert svc.delete("SAM-001") is True
            assert svc.get("SAM-001") is None
            assert svc.delete("SAM-001") is False

    def test_sample_id_defaults_to_strain_id(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            meta = svc.upsert("SAM-001", {"patient_name": "张三"})
            assert meta.sample_id == "SAM-001"


class TestStrainMetadataExtra:
    def test_extra_json_stored(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert(
                "SAM-001",
                {
                    "patient_name": "张三",
                    "case_type": "暴发",
                    "report_status": "已报",
                },
            )
            meta = svc.get("SAM-001")
            assert meta.extra["case_type"] == "暴发"
            assert meta.extra["report_status"] == "已报"

    def test_extra_json_update_merged(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"custom_a": "value_a"})
            svc.upsert("SAM-001", {"custom_b": "value_b", "patient_name": "李四"})
            meta = svc.get("SAM-001")
            assert meta.extra["custom_a"] == "value_a"
            assert meta.extra["custom_b"] == "value_b"

    def test_core_not_in_extra(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"province": "北京", "custom_field": "xxx"})
            meta = svc.get("SAM-001")
            assert meta.province == "北京"
            assert "province" not in meta.extra
            assert meta.extra["custom_field"] == "xxx"


class TestStrainMetadataSearch:
    def test_search_by_province(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"province": "北京", "isolation_date": "2024-01-01"})
            svc.upsert("SAM-002", {"province": "上海", "isolation_date": "2024-02-01"})
            svc.upsert("SAM-003", {"province": "北京", "isolation_date": "2024-03-01"})
            results = svc.search(province="北京")
            assert len(results) == 2
            assert all(r.province == "北京" for r in results)

    def test_search_by_outbreak(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"outbreak_id": "OB-2024-001"})
            svc.upsert("SAM-002", {"outbreak_id": "OB-2024-001"})
            svc.upsert("SAM-003", {"outbreak_id": "OB-2024-002"})
            results = svc.search(outbreak_id="OB-2024-001")
            assert len(results) == 2

    def test_search_by_date_range(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"isolation_date": "2024-01-15"})
            svc.upsert("SAM-002", {"isolation_date": "2024-03-20"})
            svc.upsert("SAM-003", {"isolation_date": "2024-06-01"})
            results = svc.search(isolation_date_from="2024-03-01", isolation_date_to="2024-05-01")
            assert len(results) == 1
            assert results[0].strain_id == "SAM-002"

    def test_search_by_extra(self, db_path: Path):
        with StrainMetadataService(db_path) as svc:
            svc.upsert("SAM-001", {"report_status": "已报"})
            svc.upsert("SAM-002", {"report_status": "草稿"})
            results = svc.search(extra={"report_status": "已报"})
            assert len(results) == 1
            assert results[0].strain_id == "SAM-001"


class TestStrainMetadataImport:
    def test_import_tsv(self, db_path: Path, tmp_path: Path):
        tsv = tmp_path / "meta.tsv"
        tsv.write_text(
            "strain_id\tpatient_name\tprovince\tisolation_date\n"
            "SAM-001\t张三\t北京\t2024-01-01\n"
            "SAM-002\t李四\t上海\t2024-02-01\n"
        )
        with StrainMetadataService(db_path) as svc:
            count = svc.import_tsv(tsv)
            assert count == 2
            assert svc.get("SAM-001").patient_name == "张三"
            assert svc.get("SAM-002").province == "上海"


# ===========================================================================
# LabResultService Tests
# ===========================================================================


class TestLabResultCRUD:
    def test_add_single(self, db_path: Path):
        with LabResultService(db_path) as svc:
            lr = svc.add(
                "SAM-001",
                "ast",
                "氨苄西林",
                result="16",
                unit="ug/mL",
                interpretation="R",
                method="broth_microdilution",
            )
            assert lr.strain_id == "SAM-001"
            assert lr.category == "ast"
            assert lr.test_name == "氨苄西林"
            assert lr.result == "16"
            assert lr.interpretation == "R"

    def test_add_batch(self, db_path: Path):
        with LabResultService(db_path) as svc:
            results = svc.add_batch(
                "SAM-001",
                "ast",
                [
                    {"test_name": "氨苄西林", "result": "16", "interpretation": "R"},
                    {"test_name": "环丙沙星", "result": "0.5", "interpretation": "S"},
                    {"test_name": "头孢曲松", "result": "2", "interpretation": "I"},
                ],
            )
            assert len(results) == 3
            all_results = svc.get_by_strain("SAM-001")
            assert len(all_results) == 3

    def test_get_by_strain_filtered(self, db_path: Path):
        with LabResultService(db_path) as svc:
            svc.add("SAM-001", "ast", "氨苄西林", result="16")
            svc.add("SAM-001", "serology", "O抗原", result="O4")
            svc.add("SAM-001", "biochemical", "氧化酶", result="阴性")
            ast_only = svc.get_by_strain("SAM-001", category="ast")
            assert len(ast_only) == 1
            all_results = svc.get_by_strain("SAM-001")
            assert len(all_results) == 3

    def test_delete(self, db_path: Path):
        with LabResultService(db_path) as svc:
            lr = svc.add("SAM-001", "ast", "氨苄西林", result="16")
            assert svc.delete(lr.id) is True
            assert svc.get_by_id(lr.id) is None

    def test_delete_by_strain(self, db_path: Path):
        with LabResultService(db_path) as svc:
            svc.add("SAM-001", "ast", "氨苄西林", result="16")
            svc.add("SAM-001", "serology", "O抗原", result="O4")
            count = svc.delete_by_strain("SAM-001", category="ast")
            assert count == 1
            remaining = svc.get_by_strain("SAM-001")
            assert len(remaining) == 1


class TestLabResultSearch:
    def test_search_by_category(self, db_path: Path):
        with LabResultService(db_path) as svc:
            svc.add("SAM-001", "ast", "氨苄西林", result="16", interpretation="R")
            svc.add("SAM-002", "ast", "氨苄西林", result="4", interpretation="I")
            svc.add("SAM-001", "serology", "O抗原", result="O4")
            results = svc.search(category="ast")
            assert len(results) == 2

    def test_search_resistant(self, db_path: Path):
        with LabResultService(db_path) as svc:
            svc.add("SAM-001", "ast", "氨苄西林", result="16", interpretation="R")
            svc.add("SAM-002", "ast", "氨苄西林", result="4", interpretation="S")
            svc.add("SAM-003", "ast", "氨苄西林", result="8", interpretation="R")
            resistant = svc.search(interpretation="R", test_name="氨苄西林")
            assert len(resistant) == 2

    def test_search_by_strain_ids(self, db_path: Path):
        with LabResultService(db_path) as svc:
            svc.add("SAM-001", "ast", "氨苄西林", result="16")
            svc.add("SAM-002", "ast", "氨苄西林", result="4")
            svc.add("SAM-003", "ast", "氨苄西林", result="8")
            results = svc.search(strain_ids=["SAM-001", "SAM-003"])
            assert len(results) == 2


class TestLabResultExtra:
    def test_extra_stored(self, db_path: Path):
        with LabResultService(db_path) as svc:
            lr = svc.add(
                "SAM-001",
                "ast",
                "氨苄西林",
                result="16",
                interpretation="R",
                zone_diameter="6",
                control_strain="ATCC 25922",
            )
            assert lr.extra["zone_diameter"] == "6"
            assert lr.extra["control_strain"] == "ATCC 25922"


class TestLabResultImport:
    def test_import_tsv(self, db_path: Path, tmp_path: Path):
        tsv = tmp_path / "lab.tsv"
        tsv.write_text(
            "strain_id\tcategory\ttest_name\tresult\tinterpretation\tmethod\n"
            "SAM-001\tast\t氨苄西林\t16\tR\tbroth_microdilution\n"
            "SAM-001\tast\t环丙沙星\t0.5\tS\tbroth_microdilution\n"
            "SAM-001\tserology\tO抗原\tO4\t\tantiserum\n"
        )
        with LabResultService(db_path) as svc:
            count = svc.import_tsv(tsv)
            assert count == 3
            ast = svc.get_by_strain("SAM-001", category="ast")
            assert len(ast) == 2
            sero = svc.get_by_strain("SAM-001", category="serology")
            assert len(sero) == 1


# ===========================================================================
# Integration: metadata + lab_results + GOM
# ===========================================================================


class TestIntegration:
    def test_three_table_join(self, db_path: Path):
        with StrainMetadataService(db_path) as meta_svc, LabResultService(db_path) as lab_svc:
            meta_svc.upsert(
                "SAM-001",
                {
                    "patient_name": "张三",
                    "province": "北京",
                    "isolation_date": "2024-03-10",
                },
            )
            lab_svc.add(
                "SAM-001",
                "serology",
                "O抗原",
                result="O4",
                interpretation="O:4",
                method="antiserum",
            )
            lab_svc.add(
                "SAM-001",
                "ast",
                "氨苄西林",
                result="16",
                interpretation="R",
                method="broth_microdilution",
            )

            meta = meta_svc.get("SAM-001")
            labs = lab_svc.get_by_strain("SAM-001")

            assert meta.patient_name == "张三"
            assert len(labs) == 2
            sero = [lr for lr in labs if lr.category == "serology"][0]
            assert sero.result == "O4"
