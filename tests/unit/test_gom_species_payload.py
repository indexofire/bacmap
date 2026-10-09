"""GOM species_identification payload contract (species-id P0)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.store.genome_object_service import (  # noqa: E402
    GenomeObject,
    GenomeObjectService,
    GOMValidationError,
    ObjectType,
)

_NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)


def _species_payload(**overrides: object) -> dict:
    payload: dict = {
        "analysis_type": "species_identification",
        "method": "marker",
        "database": {"name": "species_markers", "version": "abcd1234"},
        "result": {"species": "Salmonella", "confidence": "high"},
    }
    payload.update(overrides)
    return payload


def _analysis(
    payload: dict, object_id: str = "00000000-0000-4000-8000-0000000000aa"
) -> GenomeObject:
    return GenomeObject(
        object_id=object_id,
        object_type=ObjectType.ANALYSIS,
        version=1,
        schema_version="0.1.0",
        created_at=_NOW,
        created_by="test",
        payload=payload,
        pipeline_version="species-id-p0",
        database_versions={"species_markers": "abcd1234"},
        strain_id="SAM-TYP-001",
        database_signature="species_markers@abcd1234",
    )


class TestPayloadValidation:
    def test_valid_payload_accepted(self, tmp_path):
        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            gos.create(_analysis(_species_payload()))

    def test_missing_method_rejected(self):
        payload = _species_payload()
        del payload["method"]
        with pytest.raises(GOMValidationError, match="method"):
            _analysis(payload)

    def test_missing_database_rejected(self):
        payload = _species_payload()
        del payload["database"]
        with pytest.raises(GOMValidationError, match="database"):
            _analysis(payload)

    def test_missing_result_rejected(self):
        payload = _species_payload()
        del payload["result"]
        with pytest.raises(GOMValidationError, match="result"):
            _analysis(payload)

    def test_result_missing_species_rejected(self):
        payload = _species_payload()
        payload["result"] = {"confidence": "high"}
        with pytest.raises(GOMValidationError, match="species"):
            _analysis(payload)

    def test_result_missing_confidence_rejected(self):
        payload = _species_payload()
        payload["result"] = {"species": "Salmonella"}
        with pytest.raises(GOMValidationError, match="confidence"):
            _analysis(payload)

    def test_unknown_method_rejected(self):
        with pytest.raises(GOMValidationError, match="method"):
            _analysis(_species_payload(method="psychic"))

    @pytest.mark.parametrize(
        "method",
        ["marker", "panel", "skani_gtdb", "mash_refseq", "sourmash", "gtdbtk", "kraken2"],
    )
    def test_all_methods_accepted(self, method):
        _analysis(_species_payload(method=method))

    def test_cgmlst_payload_validation_unaffected(self):
        payload = {"analysis_type": "cgmlst_profile", "scheme": "senterica_2"}
        with pytest.raises(GOMValidationError, match="n_loci"):
            _analysis(payload)


class TestEventType:
    def test_species_identified_event_lifecycle(self, tmp_path):
        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            obj = gos.create(_analysis(_species_payload()))
            gos.log_event(
                obj.object_id,
                "species_identified",
                {"method": "marker", "species": "Salmonella"},
            )
            events = gos.list_events(obj.object_id)
            assert any(e.event_type == "species_identified" for e in events)


class TestStrainQuery:
    def test_list_species_identifications_by_strain(self, tmp_path):
        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            gos.create(_analysis(_species_payload()))
            gos.create(
                _analysis(
                    _species_payload(
                        method="skani_gtdb",
                        result={"species": "Salmonella", "confidence": "high", "ani": 98.7},
                    ),
                    object_id="00000000-0000-4000-8000-0000000000bb",
                )
            )
            gos.create(
                _analysis(
                    {"analysis_type": "cgmlst_profile", "scheme": "x", "n_loci": 1},
                    object_id="00000000-0000-4000-8000-0000000000cc",
                )
            )

            found = gos.list_species_identifications("SAM-TYP-001")
            methods = sorted(o.payload["method"] for o in found)
            assert methods == ["marker", "skani_gtdb"]

    def test_other_strain_excluded(self, tmp_path):
        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            gos.create(_analysis(_species_payload()))
            assert gos.list_species_identifications("SAM-OTHER-999") == []
