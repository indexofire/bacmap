"""Unit tests for bacmap.tools — service-backed handlers.

Covers: query_metadata, add_metadata, query_lab_results, add_lab_result.

Each test builds a real tmp SQLite DB via StrainMetadataService /
LabResultService and monkeypatches tools.services._DEFAULT_DB_PATH to it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap import tools  # noqa: E402
from bacmap.store.lab_results import LabResultService  # noqa: E402
from bacmap.store.strain_metadata import StrainMetadataService  # noqa: E402
from bacmap.tools import services as tools_services  # noqa: E402


def _parse(result: str) -> dict:
    return json.loads(result)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_db(tmp_path: Path, monkeypatch) -> Path:
    """A real tmp SQLite DB with metadata + lab results, set as tools.services._DEFAULT_DB_PATH."""
    db_path = tmp_path / "test.sqlite"

    with StrainMetadataService(db_path) as svc:
        svc.upsert(
            "SAM-001",
            {
                "patient_name": "Alice",
                "province": "Beijing",
                "outbreak_id": "OB-2024-001",
                "isolation_date": "2024-01-15",
                "sample_source": "stool",
            },
        )
        svc.upsert(
            "SAM-002",
            {
                "patient_name": "Bob",
                "province": "Shanghai",
                "outbreak_id": "OB-2024-002",
                "isolation_date": "2024-03-01",
                "sample_source": "food",
            },
        )

    with LabResultService(db_path) as svc:
        svc.add(
            "SAM-001",
            "ast",
            "ampicillin",
            result="16",
            interpretation="R",
            method="broth_microdilution",
        )
        svc.add(
            "SAM-001",
            "serology",
            "O antigen",
            result="O4",
            interpretation="O:4",
            method="antiserum",
        )
        svc.add(
            "SAM-002",
            "ast",
            "ciprofloxacin",
            result="0.5",
            interpretation="S",
            method="broth_microdilution",
        )

    monkeypatch.setattr(tools_services, "_DEFAULT_DB_PATH", db_path)
    return db_path


# ===========================================================================
# query_metadata
# ===========================================================================


class TestQueryMetadata:
    def test_db_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(tools_services, "_DEFAULT_DB_PATH", tmp_path / "no.sqlite")
        r = _parse(tools.query_metadata({}))
        assert "Database not found" in r["error"]

    def test_get_single_strain(self, populated_db):
        r = _parse(tools.query_metadata({"strain_id": "SAM-001"}))
        assert r["strain_id"] == "SAM-001"
        assert r["province"] == "Beijing"
        assert r["patient_name"] == "Alice"

    def test_strain_not_found(self, populated_db):
        r = _parse(tools.query_metadata({"strain_id": "NOPE"}))
        assert "error" in r
        assert "not found" in r["error"]

    def test_list_all(self, populated_db):
        r = _parse(tools.query_metadata({}))
        assert r["count"] == 2
        ids = {x["strain_id"] for x in r["results"]}
        assert ids == {"SAM-001", "SAM-002"}

    def test_search_by_province(self, populated_db):
        r = _parse(tools.query_metadata({"province": "Beijing"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-001"

    def test_search_by_outbreak(self, populated_db):
        r = _parse(tools.query_metadata({"outbreak_id": "OB-2024-002"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-002"

    def test_search_by_date_range(self, populated_db):
        r = _parse(
            tools.query_metadata(
                {"isolation_date_from": "2024-02-01", "isolation_date_to": "2024-04-01"}
            )
        )
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-002"

    def test_search_by_sample_source(self, populated_db):
        r = _parse(tools.query_metadata({"sample_source": "food"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-002"


# ===========================================================================
# add_metadata
# ===========================================================================


class TestAddMetadata:
    def test_db_can_be_created(self, tmp_path: Path, monkeypatch):
        # add_metadata does NOT pre-check DB existence (unlike query_metadata).
        # It opens StrainMetadataService which creates the DB on demand.
        fresh_db = tmp_path / "fresh.sqlite"
        monkeypatch.setattr(tools_services, "_DEFAULT_DB_PATH", fresh_db)
        r = _parse(
            tools.add_metadata(
                {
                    "strain_id": "SAM-NEW",
                    "data": {"province": "Guangdong", "patient_name": "Carol"},
                }
            )
        )
        assert r["status"] == "saved"
        assert r["strain_id"] == "SAM-NEW"
        assert r["data"]["province"] == "Guangdong"
        assert fresh_db.exists()

    def test_update_existing(self, populated_db):
        r = _parse(
            tools.add_metadata(
                {
                    "strain_id": "SAM-001",
                    "data": {"province": "Shenzhen"},
                }
            )
        )
        assert r["status"] == "saved"
        assert r["data"]["province"] == "Shenzhen"
        # Verify the update persisted.
        with StrainMetadataService(populated_db) as svc:
            meta = svc.get("SAM-001")
            assert meta.province == "Shenzhen"

    def test_missing_strain_id(self, populated_db):
        r = _parse(tools.add_metadata({"data": {"province": "X"}}))
        assert "strain_id" in r["error"]

    def test_missing_data(self, populated_db):
        r = _parse(tools.add_metadata({"strain_id": "SAM-001"}))
        assert "data" in r["error"]

    def test_invalid_data_type(self, populated_db):
        r = _parse(tools.add_metadata({"strain_id": "SAM-001", "data": "not a dict"}))
        assert "data" in r["error"]


# ===========================================================================
# query_lab_results
# ===========================================================================


class TestQueryLabResults:
    def test_db_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(tools_services, "_DEFAULT_DB_PATH", tmp_path / "no.sqlite")
        r = _parse(tools.query_lab_results({}))
        assert "Database not found" in r["error"]

    def test_query_by_sample_id(self, populated_db):
        r = _parse(tools.query_lab_results({"sample_id": "SAM-001"}))
        assert r["count"] == 2
        cats = {x["category"] for x in r["results"]}
        assert cats == {"ast", "serology"}

    def test_query_by_sample_id_filtered_category(self, populated_db):
        r = _parse(tools.query_lab_results({"sample_id": "SAM-001", "category": "ast"}))
        assert r["count"] == 1
        assert r["results"][0]["test_name"] == "ampicillin"

    def test_search_by_category(self, populated_db):
        r = _parse(tools.query_lab_results({"category": "ast"}))
        assert r["count"] == 2  # SAM-001 ast + SAM-002 ast

    def test_search_by_interpretation(self, populated_db):
        r = _parse(tools.query_lab_results({"interpretation": "R"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-001"

    def test_search_by_test_name(self, populated_db):
        r = _parse(tools.query_lab_results({"test_name": "ciprofloxacin"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-002"

    def test_search_no_filters_returns_limited(self, populated_db):
        r = _parse(tools.query_lab_results({}))
        # No filter → svc.search(limit=200) returns all 3 lab rows.
        assert r["count"] == 3


# ===========================================================================
# add_lab_result
# ===========================================================================


class TestAddLabResult:
    def test_happy_path_with_optional_fields(self, tmp_path: Path, monkeypatch):
        db = tmp_path / "lab.sqlite"
        with LabResultService(db):
            pass  # create schema
        monkeypatch.setattr(tools_services, "_DEFAULT_DB_PATH", db)

        r = _parse(
            tools.add_lab_result(
                {
                    "strain_id": "SAM-X",
                    "category": "ast",
                    "test_name": "gentamicin",
                    "result": "8",
                    "interpretation": "I",
                    "method": "broth_microdilution",
                    "unit": "ug/mL",
                }
            )
        )
        assert r["status"] == "saved"
        assert r["strain_id"] == "SAM-X"
        assert r["test_name"] == "gentamicin"
        assert r["result"] == "8"
        assert "id" in r

    def test_add_to_populated_db(self, populated_db):
        r = _parse(
            tools.add_lab_result(
                {
                    "strain_id": "SAM-001",
                    "category": "biochemical",
                    "test_name": "oxidase",
                    "result": "negative",
                }
            )
        )
        assert r["status"] == "saved"
        assert r["category"] == "biochemical"

    def test_missing_required_fields(self, populated_db):
        # All four of strain_id, category, test_name, result are required.
        r = _parse(tools.add_lab_result({"strain_id": "SAM-001"}))
        assert "required" in r["error"]

        r = _parse(
            tools.add_lab_result(
                {
                    "strain_id": "SAM-001",
                    "category": "ast",
                    "test_name": "amp",  # missing result
                }
            )
        )
        assert "required" in r["error"]
