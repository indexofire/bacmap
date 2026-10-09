"""bio_species_compare Hermes tool (species-id P0)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.store.genome_object_service import (  # noqa: E402
    GenomeObject,
    GenomeObjectService,
    ObjectType,
)
from bacmap.tools import services as tool_services  # noqa: E402

_NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
_SEQ = iter(range(1, 100))


def _add(gos: GenomeObjectService, method: str, species: str) -> None:
    n = next(_SEQ)
    gos.create(
        GenomeObject(
            object_id=f"0000000c-0000-4000-8000-{n:012d}",
            object_type=ObjectType.ANALYSIS,
            version=1,
            schema_version="0.1.0",
            created_at=_NOW,
            created_by="t",
            payload={
                "analysis_type": "species_identification",
                "method": method,
                "database": {"name": f"db_{method}", "version": "v1"},
                "result": {"species": species, "confidence": "high"},
            },
            pipeline_version="t",
            database_versions={f"db_{method}": "v1"},
            strain_id="SAM-9",
        )
    )


class TestSpeciesCompareHandler:
    def test_multi_method_matrix(self, tmp_path, monkeypatch):
        db = tmp_path / "gom.sqlite"
        with GenomeObjectService(db) as gos:
            _add(gos, "marker", "Salmonella")
            _add(gos, "skani_gtdb", "Salmonella")
        monkeypatch.setattr(tool_services, "_DEFAULT_DB_PATH", db)
        out = tool_services.species_compare({"strain_id": "SAM-9"})
        assert "marker" in out and "skani_gtdb" in out
        assert "match" in out
        assert "SAM-9" in out

    def test_empty_strain_reported(self, tmp_path, monkeypatch):
        db = tmp_path / "gom.sqlite"
        GenomeObjectService(db).close()
        monkeypatch.setattr(tool_services, "_DEFAULT_DB_PATH", db)
        out = tool_services.species_compare({"strain_id": "SAM-NONE"})
        assert "SAM-NONE" in out
        assert "no species identification" in out or "empty" in out

    def test_needs_review_surfaced(self, tmp_path, monkeypatch):
        db = tmp_path / "gom.sqlite"
        with GenomeObjectService(db) as gos:
            _add(gos, "skani_gtdb", "Salmonella")
            _add(gos, "sourmash", "Vibrio cholerae")
        monkeypatch.setattr(tool_services, "_DEFAULT_DB_PATH", db)
        out = tool_services.species_compare({"strain_id": "SAM-9"})
        assert "NEEDS_REVIEW" in out or "needs_review" in out
