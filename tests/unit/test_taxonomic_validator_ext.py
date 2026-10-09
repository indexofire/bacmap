"""Extends test_taxonomic_validator with subprocess / validate_genome coverage.

These tests are intentionally additive — the existing test_taxonomic_validator.py
covers TaxonomyResult.to_dict, summary formatting, _build_interpretation core
paths, and config env-var handling.  This module focuses on _run_checkm2 /
_run_gtdbtk / _find_tool / validate_genome with all subprocess boundaries
mocked.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis import taxonomic_validator as tv  # noqa: E402
from bacmap.core.analysis.species_identifier import SpeciesIdResult  # noqa: E402
from bacmap.core.analysis.taxonomic_validator import (  # noqa: E402
    TaxonomyResult,
    _build_interpretation,
    _find_tool,
    _run_checkm2,
    _run_gtdbtk,
    validate_genome,
)


class TestFindTool:
    def test_returns_none_when_not_found(self, monkeypatch):
        monkeypatch.setattr(tv, "pixi_path", lambda: "/nonexistent/path/bin")
        assert _find_tool("definitely_missing_tool_xyz") is None

    def test_returns_path_when_found(self, monkeypatch, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_bin = bin_dir / "mytool"
        fake_bin.write_text("#!/bin/sh\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr(tv, "pixi_path", lambda: f"{bin_dir}:{bin_dir}")
        out = _find_tool("mytool")
        assert out is not None
        assert Path(out).name == "mytool"


class TestRunCheckm2:
    def test_returns_none_when_no_db_configured(self, monkeypatch):
        monkeypatch.setattr(tv, "CHECKM2_DB", None)
        out = _run_checkm2("/some/contigs.fasta", Path("/tmp/out"))
        assert out == (None, None)

    def test_returns_none_when_tool_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: None)
        out = _run_checkm2("/some/contigs.fasta", tmp_path / "out")
        assert out == (None, None)

    def test_parses_tsv_into_completeness_contamination(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/checkm2")

        def fake_run(cmd, **kw):
            tsv = out_dir / "checkm2_results.tsv"
            tsv.write_text("Name\tCompleteness\tContamination\nsample1\t98.5\t1.2\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        completeness, contamination = _run_checkm2("/c.fasta", out_dir)
        assert completeness == 98.5
        assert contamination == 1.2

    def test_returns_none_when_subprocess_fails_with_timeout(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/checkm2")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("cmd", 600)),
        )
        assert _run_checkm2("/c.fasta", out_dir) == (None, None)

    def test_returns_none_when_subprocess_filenotfound(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/checkm2")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("nope")),
        )
        assert _run_checkm2("/c.fasta", out_dir) == (None, None)

    def test_returns_none_when_tsv_missing(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/checkm2")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "", ""),
        )
        assert _run_checkm2("/c.fasta", out_dir) == (None, None)

    def test_returns_none_when_tsv_only_has_header(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/checkm2")

        def fake_run(cmd, **kw):
            (out_dir / "checkm2_results.tsv").write_text("Name\tCompleteness\tContamination\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert _run_checkm2("/c.fasta", out_dir) == (None, None)

    def test_returns_none_on_malformed_numeric_values(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setattr(tv, "CHECKM2_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/checkm2")

        def fake_run(cmd, **kw):
            (out_dir / "checkm2_results.tsv").write_text(
                "Name\tCompleteness\tContamination\nsample\tnot_a_number\talso_bad\n"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        completeness, contamination = _run_checkm2("/c.fasta", out_dir)
        assert completeness is None
        assert contamination is None


class TestRunGtdbtk:
    def test_returns_empty_when_no_db_configured(self, monkeypatch):
        monkeypatch.setattr(tv, "GTDB_DB", None)
        assert _run_gtdbtk("/c.fasta", Path("/tmp/out")) == ""

    def test_returns_empty_when_tool_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tv, "GTDB_DB", tmp_path / "db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: None)
        assert _run_gtdbtk("/c.fasta", tmp_path / "out") == ""

    def test_writes_genome_under_genome_dir_then_parses_summary(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        contigs = tmp_path / "contigs.fasta"
        contigs.write_text(">ctg\nACGT\n")
        monkeypatch.setattr(tv, "GTDB_DB", tmp_path / "gtdb_db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/gtdbtk")

        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            gtdb_out = out_dir / "gtdb_output"
            gtdb_out.mkdir(parents=True, exist_ok=True)
            (gtdb_out / "gtdbtk.bac120.summary.tsv").write_text(
                "user_genome\tclassification\nquery.fasta\ts__Salmonella enterica\n"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = _run_gtdbtk(str(contigs), out_dir)
        assert result == "s__Salmonella enterica"
        assert (out_dir / "gtdb_genomes" / "query.fasta").exists()
        assert (out_dir / "gtdb_genomes" / "query.fasta").read_text() == ">ctg\nACGT\n"
        assert "classify_wf" in captured["cmd"]
        assert "--cpus" in captured["cmd"]

    def test_falls_back_to_ar122_summary(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        contigs = tmp_path / "contigs.fasta"
        contigs.write_text(">c\nACGT\n")
        monkeypatch.setattr(tv, "GTDB_DB", tmp_path / "gtdb_db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/gtdbtk")

        def fake_run(cmd, **kw):
            gtdb_out = out_dir / "gtdb_output"
            gtdb_out.mkdir(parents=True, exist_ok=True)
            (gtdb_out / "gtdbtk.ar122.summary.tsv").write_text(
                "user_genome\tclassification\nquery.fasta\ts__Methanobacterium\n"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert _run_gtdbtk(str(contigs), out_dir) == "s__Methanobacterium"

    def test_returns_empty_when_subprocess_times_out(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        contigs = tmp_path / "contigs.fasta"
        contigs.write_text(">c\nACGT\n")
        monkeypatch.setattr(tv, "GTDB_DB", tmp_path / "gtdb_db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/gtdbtk")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("cmd", 3600)),
        )
        assert _run_gtdbtk(str(contigs), out_dir) == ""

    def test_returns_empty_when_no_summary_file(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        contigs = tmp_path / "contigs.fasta"
        contigs.write_text(">c\nACGT\n")
        monkeypatch.setattr(tv, "GTDB_DB", tmp_path / "gtdb_db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/gtdbtk")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "", ""),
        )
        assert _run_gtdbtk(str(contigs), out_dir) == ""

    def test_returns_empty_when_summary_only_has_header(self, monkeypatch, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        contigs = tmp_path / "contigs.fasta"
        contigs.write_text(">c\nACGT\n")
        monkeypatch.setattr(tv, "GTDB_DB", tmp_path / "gtdb_db")
        monkeypatch.setattr(tv, "_find_tool", lambda name: "/fake/gtdbtk")

        def fake_run(cmd, **kw):
            gtdb_out = out_dir / "gtdb_output"
            gtdb_out.mkdir(parents=True, exist_ok=True)
            (gtdb_out / "gtdbtk.bac120.summary.tsv").write_text("user_genome\tclassification\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert _run_gtdbtk(str(contigs), out_dir) == ""


class TestBuildInterpretationExtended:
    def test_check_quality_band_between_50_and_90(self):
        r = TaxonomyResult(
            completeness=70.0,
            contamination=2.0,
        )
        out = _build_interpretation(r)
        assert "CHECK" in out
        assert "70.0" in out

    def test_pass_when_completeness_exactly_90(self):
        r = TaxonomyResult(completeness=90.0, contamination=5.0)
        assert "PASS" in _build_interpretation(r)

    def test_pass_when_contamination_exactly_5(self):
        r = TaxonomyResult(completeness=95.0, contamination=5.0)
        assert "PASS" in _build_interpretation(r)

    def test_check_when_contamination_above_5(self):
        r = TaxonomyResult(completeness=95.0, contamination=6.0)
        out = _build_interpretation(r)
        assert "CHECK" in out
        assert "6.0" in out

    def test_agreement_with_slash_separated_species(self):
        r = TaxonomyResult(
            completeness=95.0,
            contamination=2.0,
            gtdb_taxonomy="s__Shigella flexneri",
            marker_gene_species="Shigella/EIEC",
        )
        out = _build_interpretation(r)
        assert "agree" in out


class TestValidateGenomeSimpleMode:
    def test_writes_validation_json_and_uses_marker_result(self, tmp_path, monkeypatch):
        contigs = tmp_path / "sample" / "assembly" / "contigs.fasta"
        contigs.parent.mkdir(parents=True)
        contigs.write_text(">ctg\nACGT\n")

        marker = SpeciesIdResult()
        marker.species = "Salmonella"
        marker.confidence = "high"
        marker.detected_markers = [
            {"gene": "invA", "identity": 99.0, "coverage": 100.0, "contig": "ctg1"}
        ]

        monkeypatch.setattr(
            "bacmap.core.analysis.species_identifier.identify",
            lambda *a, **kw: marker,
        )
        result = validate_genome(str(contigs), mode="simple")
        assert isinstance(result, TaxonomyResult)
        assert result.mode == "simple"
        assert result.marker_gene_species == "Salmonella"
        assert result.marker_gene_confidence == "high"
        assert result.marker_gene_markers == marker.detected_markers
        assert "Marker gene: Salmonella" in result.interpretation

        out_dir = tmp_path / "sample" / "taxonomy"
        assert (out_dir / "validation.json").exists()

    def test_uses_explicit_output_dir_when_provided(self, tmp_path, monkeypatch):
        contigs = tmp_path / "ctgs.fasta"
        contigs.write_text(">c\nACGT\n")
        monkeypatch.setattr(
            "bacmap.core.analysis.species_identifier.identify",
            lambda *a, **kw: SpeciesIdResult(),
        )
        out_dir = tmp_path / "custom_tax"
        validate_genome(str(contigs), mode="simple", output_dir=out_dir)
        assert (out_dir / "validation.json").exists()


class TestValidateGenomeStandardMode:
    def test_combines_marker_checkm2_gtdbtk(self, tmp_path, monkeypatch):
        contigs = tmp_path / "ctgs.fasta"
        contigs.write_text(">c\nACGT\n")

        marker = SpeciesIdResult()
        marker.species = "Salmonella"
        marker.confidence = "high"

        monkeypatch.setattr(
            "bacmap.core.analysis.species_identifier.identify",
            lambda *a, **kw: marker,
        )
        monkeypatch.setattr(tv, "_run_checkm2", lambda *a, **kw: (95.0, 1.5))
        monkeypatch.setattr(tv, "_run_gtdbtk", lambda *a, **kw: "s__Salmonella enterica")

        result = validate_genome(str(contigs), mode="standard", output_dir=tmp_path / "tax")
        assert result.mode == "standard"
        assert result.completeness == 95.0
        assert result.contamination == 1.5
        assert result.gtdb_taxonomy == "s__Salmonella enterica"
        assert "PASS" in result.interpretation
        assert "agree" in result.interpretation

    def test_writes_validation_json_in_standard_mode(self, tmp_path, monkeypatch):
        contigs = tmp_path / "ctgs.fasta"
        contigs.write_text(">c\nACGT\n")

        monkeypatch.setattr(
            "bacmap.core.analysis.species_identifier.identify",
            lambda *a, **kw: SpeciesIdResult(),
        )
        monkeypatch.setattr(tv, "_run_checkm2", lambda *a, **kw: (None, None))
        monkeypatch.setattr(tv, "_run_gtdbtk", lambda *a, **kw: "")

        out_dir = tmp_path / "tax"
        validate_genome(str(contigs), mode="standard", output_dir=out_dir)
        assert (out_dir / "validation.json").exists()
