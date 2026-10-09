"""Tests for taxonomic_validator — dual-mode species identification."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.taxonomic_validator import (  # noqa: E402
    TaxonomyResult,
    _build_interpretation,
)


class TestTaxonomyResult:
    def test_to_dict_has_all_fields(self):
        r = TaxonomyResult(mode="simple", marker_gene_species="Salmonella")
        d = r.to_dict()
        assert d["mode"] == "simple"
        assert d["marker_gene_species"] == "Salmonella"
        assert "completeness" in d
        assert "gtdb_taxonomy" in d

    def test_summary_simple_mode(self):
        r = TaxonomyResult(mode="simple", marker_gene_species="Salmonella")
        assert "Salmonella" in r.summary

    def test_summary_standard_mode(self):
        r = TaxonomyResult(
            mode="standard",
            marker_gene_species="Salmonella",
            completeness=98.5,
            contamination=1.2,
            gtdb_taxonomy="s__Salmonella enterica",
        )
        s = r.summary
        assert "98.5" in s
        assert "1.2" in s
        assert "Salmonella enterica" in s


class TestInterpretationBuilder:
    def test_pass_quality(self):
        r = TaxonomyResult(
            completeness=95.0,
            contamination=2.0,
            gtdb_taxonomy="s__Salmonella enterica",
            marker_gene_species="Salmonella",
        )
        interp = _build_interpretation(r)
        assert "PASS" in interp
        assert "agree" in interp

    def test_low_completeness_warning(self):
        r = TaxonomyResult(completeness=40.0, contamination=0.5)
        interp = _build_interpretation(r)
        assert "WARNING" in interp

    def test_discrepancy_detected(self):
        r = TaxonomyResult(
            completeness=95.0,
            contamination=2.0,
            gtdb_taxonomy="s__Escherichia coli",
            marker_gene_species="Salmonella",
        )
        interp = _build_interpretation(r)
        assert "DISCREPANCY" in interp

    def test_no_databases_available(self):
        r = TaxonomyResult(mode="standard")
        interp = _build_interpretation(r)
        assert "not available" in interp


class TestConfigIntegration:
    def test_checkm2_db_env_var(self, monkeypatch):
        import importlib

        monkeypatch.setenv("CHECKM2DB", "/fake/checkm2/db")
        import bacmap.config

        importlib.reload(bacmap.config)
        assert bacmap.config.CHECKM2_DB is not None
        importlib.reload(bacmap.config)

    def test_gtdb_db_env_var(self, monkeypatch):
        import importlib

        monkeypatch.setenv("GTDBDB", "/fake/gtdb/db")
        import bacmap.config

        importlib.reload(bacmap.config)
        assert bacmap.config.GTDB_DB is not None
        importlib.reload(bacmap.config)

    def test_no_env_vars_returns_none(self, monkeypatch):
        monkeypatch.delenv("CHECKM2DB", raising=False)
        monkeypatch.delenv("GTDBDB", raising=False)
        import importlib

        import bacmap.config

        importlib.reload(bacmap.config)
        assert bacmap.config.CHECKM2_DB is None
        assert bacmap.config.GTDB_DB is None
        importlib.reload(bacmap.config)
