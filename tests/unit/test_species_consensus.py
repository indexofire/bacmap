"""Multi-method species identification consensus and arbitration."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.species_consensus import compare  # noqa: E402
from bacmap.store.genome_object_service import (  # noqa: E402
    GenomeObject,
    GenomeObjectService,
    ObjectType,
)

_NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
_SEQ = iter(range(1, 100))


def _add(gos: GenomeObjectService, method: str, species: str, confidence: str = "high") -> None:
    n = next(_SEQ)
    gos.create(
        GenomeObject(
            object_id=f"0000000n-0000-4000-8000-{n:012d}",
            object_type=ObjectType.ANALYSIS,
            version=1,
            schema_version="0.1.0",
            created_at=_NOW,
            created_by="test",
            payload={
                "analysis_type": "species_identification",
                "method": method,
                "database": {"name": f"db_{method}", "version": "v1"},
                "result": {"species": species, "confidence": confidence},
            },
            pipeline_version="t",
            database_versions={f"db_{method}": "v1"},
            strain_id="SAM-1",
        )
    )


def _gos(tmp_path):
    return GenomeObjectService(tmp_path / "gom.sqlite")


class TestCompare:
    def test_no_methods(self, tmp_path):
        with _gos(tmp_path) as gos:
            c = compare("SAM-1", gos)
        assert c.methods == []
        assert c.resolved_species is None
        assert c.agreement == "empty"

    def test_single_method_resolves_directly(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Salmonella")
            c = compare("SAM-1", gos)
        assert c.resolved_species == "Salmonella"
        assert c.agreement == "single"
        assert not c.needs_review

    def test_two_methods_match(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Salmonella")
            _add(gos, "skani_gtdb", "Salmonella", confidence="high")
            c = compare("SAM-1", gos)
        assert c.resolved_species == "Salmonella"
        assert c.agreement == "match"
        assert not c.needs_review

    def test_shigella_vs_ecoli_expected_divergence(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Shigella/EIEC")
            _add(gos, "skani_gtdb", "E.coli")
            c = compare("SAM-1", gos)
        assert c.agreement == "expected_divergence"
        assert c.resolved_species == "E.coli"
        assert not c.needs_review

    def test_dec_vs_ecoli_expected_divergence(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "DEC")
            _add(gos, "gtdbtk", "Escherichia coli")
            c = compare("SAM-1", gos)
        assert c.agreement == "expected_divergence"
        assert c.resolved_species == "Escherichia coli"

    def test_higher_layer_wins_low_layer_conflict(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Salmonella")
            _add(gos, "gtdbtk", "Listeria monocytogenes")
            c = compare("SAM-1", gos)
        assert c.agreement == "conflict"
        assert c.resolved_species == "Listeria monocytogenes"
        assert c.basis == "gtdbtk"
        assert not c.needs_review

    def test_same_layer_conflict_needs_review(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "skani_gtdb", "Salmonella")
            _add(gos, "sourmash", "Vibrio cholerae")
            c = compare("SAM-1", gos)
        assert c.agreement == "conflict"
        assert c.needs_review is True

    def test_three_methods_majority_match(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Salmonella")
            _add(gos, "skani_gtdb", "Salmonella")
            _add(gos, "sourmash", "Salmonella")
            c = compare("SAM-1", gos)
        assert c.agreement == "match"
        assert c.resolved_species == "Salmonella"

    def test_methods_listed_with_metadata(self, tmp_path):
        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Salmonella", confidence="high")
            c = compare("SAM-1", gos)
        assert len(c.methods) == 1
        assert c.methods[0].method == "marker"
        assert c.methods[0].species == "Salmonella"


class TestVerifierIntegration:
    def test_verifier_accepts_consensus(self, tmp_path):
        from bacmap.core.verify.deterministic_verifier import DeterministicVerifier

        with _gos(tmp_path) as gos:
            _add(gos, "marker", "Salmonella")
            _add(gos, "skani_gtdb", "Salmonella")
            c = compare("SAM-1", gos)
        result = DeterministicVerifier().verify_species_consensus(c)
        assert result.passed
        assert "match" in result.message

    def test_verifier_flags_same_layer_conflict(self, tmp_path):
        from bacmap.core.verify.deterministic_verifier import DeterministicVerifier

        with _gos(tmp_path) as gos:
            _add(gos, "skani_gtdb", "Salmonella")
            _add(gos, "sourmash", "Vibrio cholerae")
            c = compare("SAM-1", gos)
        result = DeterministicVerifier().verify_species_consensus(c)
        assert not result.passed
        assert result.details["needs_human_review"] is True
