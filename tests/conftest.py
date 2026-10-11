from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_gom.sqlite"


@pytest.fixture
def now_utc() -> datetime:
    return datetime(2026, 6, 27, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_object_id() -> str:
    return "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def fixed_artifact_id() -> str:
    return "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def fixed_event_id() -> str:
    return "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def sample_database_versions() -> dict[str, str]:
    return {
        "amrfinderplus_db": "2024-01-15.1",
        "card": "3.3.0",
        "pubmlst_schema": "2026-06-01",
    }


@pytest.fixture
def sample_tool_versions() -> dict[str, str]:
    return {
        "spades": "3.15.4",
        "sistr": "1.1.0",
        "snippy": "4.6.0",
    }


@pytest.fixture
def sample_pipeline_version() -> str:
    return "abc123def456"


@pytest.fixture
def sample_amr_payload(
    sample_database_versions: dict[str, str],
    sample_tool_versions: dict[str, str],
) -> dict:
    """完整的 AMR 分析结果 payload（含 Composite Triplet）。

    参考 project.md §5.2 Composite Triplet Schema。
    """
    return {
        "strain_id": "SH2024-001",
        "organism": "Salmonella",
        "amr_findings": [
            {
                "gene": "blaCTX-M-15",
                "gene_attributes": {
                    "mutation_site": "Promoter -281G>A",
                    "coverage": 99.8,
                    "identity": 100.0,
                },
                "relation": "confers_resistance_to",
                "relation_conditions": {
                    "mic": "≥64 μg/mL",
                    "method": "in_silico_prediction",
                    "evidence_pmid": "12345678",
                },
                "drug": "Cefotaxime",
                "drug_attributes": {
                    "class": "β-lactam/3rd-gen cephalosporin",
                },
            },
            {
                "gene": "blaTEM-1",
                "gene_attributes": {
                    "coverage": 100.0,
                    "identity": 99.5,
                },
                "relation": "confers_resistance_to",
                "relation_conditions": {
                    "mic": "≥32 μg/mL",
                    "method": "in_silico_prediction",
                },
                "drug": "Ampicillin",
                "drug_attributes": {
                    "class": "β-lactam/penicillin",
                },
            },
        ],
        "mlst": {
            "scheme": "salmonella",
            "st": 19,
            "alleles": {
                "aroC": "2",
                "dnaN": "7",
                "hemD": "12",
                "hisD": "9",
                "purE": "5",
                "sucA": "9",
                "thrA": "3",
            },
        },
        "serotype": {
            "serovar": "Typhimurium",
            "antigenic_formula": "1,4,[5],12:i:1,2",
            "method": "SISTR + SeqSero2",
        },
    }


@pytest.fixture
def sample_genome_object(
    fixed_object_id: str,
    now_utc: datetime,
    sample_amr_payload: dict,
    sample_pipeline_version: str,
    sample_database_versions: dict[str, str],
    sample_tool_versions: dict[str, str],
):
    """完整的、合法的 GenomeObject 实例（分析结果）。

    需要 import 在测试内部，避免在 conftest 顶部 import 未实现的模块导致 collect 失败。
    """
    from bacmap.store.genome_object_service import GenomeObject, ObjectType

    return GenomeObject(
        object_id=fixed_object_id.replace("0001", "0002"),
        object_type=ObjectType.ANALYSIS,
        version=1,
        schema_version="0.1.0",
        created_at=now_utc,
        created_by="test_user",
        payload=sample_amr_payload,
        pipeline_version=sample_pipeline_version,
        database_versions=sample_database_versions,
        tool_versions=sample_tool_versions,
        organism="Salmonella",
        strain_id="SH2024-001",
        database_signature="abc123",
    )


@pytest.fixture
def sample_sample_object(
    fixed_object_id: str,
    now_utc: datetime,
):
    """完整的、合法的 Sample GenomeObject 实例。"""
    from bacmap.store.genome_object_service import GenomeObject, ObjectType

    return GenomeObject(
        object_id=fixed_object_id,
        object_type=ObjectType.SAMPLE,
        version=1,
        schema_version="0.1.0",
        created_at=now_utc,
        created_by="test_user",
        payload={
            "strain_id": "SH2024-001",
            "organism": "Salmonella",
            "collection_date": "2024-06-15",
            "source": "food",
            "isolation_site": "stool",
        },
        organism="Salmonella",
        strain_id="SH2024-001",
    )


@pytest.fixture(scope="session")
def gold_standard_csv_path() -> Path:
    return Path(__file__).parent / "fixtures" / "gold_standard" / "salmonella" / "gold_standard.csv"


def _load_gold_standard_csv(csv_path: Path) -> list[dict[str, str]]:
    """加载 gold standard CSV；数据缺失时 skip 而非 error。

    tests/fixtures/gold_standard 是指向本地数据目录的符号链接（4.1GB 基因组
    数据，不入库）——fresh clone 上不存在属正常，依赖它的验证测试应跳过。
    """
    import csv

    if not csv_path.is_file():
        pytest.skip(f"gold standard data not present (local-only symlink): {csv_path}")
    with csv_path.open() as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def gold_standard_set(gold_standard_csv_path: Path) -> list[dict[str, str]]:
    """加载 Salmonella Gold standard 样本集（project.md §12.3 分析验证）。

    返回 list of dicts（每株一行）。分析验证测试用此 fixture 做 AMR/MLST/
    血清型准确率基准对比。字段定义见
    ``tests/fixtures/gold_standard/salmonella/data_dictionary.md``。
    """
    return _load_gold_standard_csv(gold_standard_csv_path)


@pytest.fixture(scope="session")
def salmonella_gold_standard(gold_standard_set):
    return [s for s in gold_standard_set if s["species"] == "Salmonella enterica"]


@pytest.fixture(scope="session")
def negative_control(gold_standard_set):
    return [s for s in gold_standard_set if s["species"] != "Salmonella enterica"]
