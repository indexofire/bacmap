"""Tests for analysis modules — species_identifier, failure_diagnostics, genome_annotator."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.failure_diagnostics import diagnose  # noqa: E402


class TestSpeciesIdentifierCaseSensitivity:
    def test_lowercase_gene_keys(self):
        from bacmap.core.analysis.species_identifier import _GENE_TO_SPECIES

        assert "inva" in _GENE_TO_SPECIES
        assert "INVA" not in _GENE_TO_SPECIES

    def test_case_insensitive_lookup(self):
        from bacmap.core.analysis.species_identifier import _GENE_TO_SPECIES

        test_genes = ["invA", "INVA", "InvA", "uidA", "UIDA"]
        for g in test_genes:
            lower = g.lower()
            assert lower in _GENE_TO_SPECIES, f"Gene '{g}' (lower='{lower}') not found"


class TestFailureDiagnosticsLoopLeak:
    def test_diagnose_returns_result_on_unknown_error(self):
        result = diagnose(
            stderr="some completely unknown error pattern zzz",
        )
        assert result is not None
        assert result.error_type is not None

    def test_diagnose_missing_input_adds_file_detail(self):
        result = diagnose(
            stderr="Error: Missing input files: /path/to/missing.fasta",
        )
        assert result.error_type == "missing_input"
        assert "/path/to/missing.fasta" in result.details


class TestGenomeAnnotatorParseProkkaHeader:
    def test_four_fields(self):
        from bacmap.core.analysis.genome_annotator import _parse_prokka_header

        gene, product = _parse_prokka_header("db~~~gene1~~~ACC123~~~product description")
        assert gene == "gene1"
        assert product == "product description"

    def test_three_fields(self):
        from bacmap.core.analysis.genome_annotator import _parse_prokka_header

        gene, product = _parse_prokka_header("db~~~gene1~~~ACC123")
        assert gene == "gene1"
        assert "ACC" not in gene

    def test_two_fields(self):
        from bacmap.core.analysis.genome_annotator import _parse_prokka_header

        gene, product = _parse_prokka_header("db~~~gene1")
        assert gene == "gene1"

    def test_single_field(self):
        from bacmap.core.analysis.genome_annotator import _parse_prokka_header

        gene, product = _parse_prokka_header("just_a_name")
        assert gene != ""


class TestGenomeAnnotatorLocusTag:
    def test_locus_tag_has_no_leading_underscore(self):
        from bacmap.core.analysis.genome_annotator import _make_locus_tag

        tag = _make_locus_tag("", 1)
        assert not tag.startswith("_")

    def test_locus_tag_unique_for_similar_ids(self):
        from bacmap.core.analysis.genome_annotator import _make_locus_tag

        t1 = _make_locus_tag("SAM-DEC-001", 1)
        t2 = _make_locus_tag("SAM-DEC-002", 1)
        assert t1 != t2


class TestFailureDiagnosticsAbsolutePath:
    def test_log_dir_uses_project_root(self):
        import inspect

        from bacmap.core.analysis import failure_diagnostics

        src = inspect.getsource(failure_diagnostics.diagnose_from_log)
        assert 'Path("workflows' not in src or "_PROJECT_ROOT" in src or "parents[" in src
