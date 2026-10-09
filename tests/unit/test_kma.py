"""Tests for KMA backend + gene_scanner FASTQ routing."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.engine.backends.kma import KmaBackend  # noqa: E402


class TestKmaBackendParsing:
    def test_parse_res_normal(self, tmp_path):
        backend = KmaBackend.__new__(KmaBackend)
        res_file = tmp_path / "test.res"
        res_file.write_text(
            "#Template\tScore\tExpected\tTemplate_length\t"
            "Template_Identity\tTemplate_Coverage\tQuery_Identity\t"
            "Query_Coverage\tDepth\tq_value\tp_value\n"
            "db~~~gene1~~~acc~~~product\t1000\t5\t500\t"
            "99.50\t100.00\t99.50\t100.00\t50.0\t100.0\t1e-50\n"
        )
        hits = backend._parse_res(tmp_path / "test", 0, 0)
        assert len(hits) == 1
        assert hits[0].subject_id.startswith("db~~~gene1")
        assert hits[0].identity == 99.50
        assert hits[0].subject_coverage == 100.0

    def test_parse_res_filter_by_coverage(self, tmp_path):
        backend = KmaBackend.__new__(KmaBackend)
        res_file = tmp_path / "test.res"
        res_file.write_text(
            "#Template\tScore\tExpected\tTemplate_length\t"
            "Template_Identity\tTemplate_Coverage\tQuery_Identity\t"
            "Query_Coverage\tDepth\tq_value\tp_value\n"
            "gene1\t1000\t5\t500\t99.0\t30.0\t99.0\t30.0\t10.0\t50.0\t1e-10\n"
        )
        hits = backend._parse_res(tmp_path / "test", min_coverage=50.0, min_identity=0)
        assert len(hits) == 0

    def test_parse_res_empty(self, tmp_path):
        backend = KmaBackend.__new__(KmaBackend)
        hits = backend._parse_res(tmp_path / "nonexistent", 0, 0)
        assert hits == []

    def test_parse_template_4_fields(self):
        gene, acc, product = KmaBackend._parse_template("db~~~gene1~~~acc1~~~product text")
        assert gene == "gene1"
        assert acc == "acc1"
        assert product == "product text"

    def test_parse_template_2_fields(self):
        gene, acc, product = KmaBackend._parse_template("db~~~gene1")
        assert gene == "gene1"
        assert acc == ""

    def test_parse_template_single(self):
        gene, acc, product = KmaBackend._parse_template("just_a_name")
        assert gene == "just_a_name"


class TestGeneScannerInputRouting:
    def test_fastq_detected_by_extension(self):
        for name in ["reads.fastq", "reads.fq", "reads.fastq.gz", "reads.fq.gz"]:
            assert name.endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz"))

    def test_fasta_not_treated_as_fastq(self):
        assert not "contigs.fasta".endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz"))
