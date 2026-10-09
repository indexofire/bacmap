"""Unit tests for bacmap.tools — Python-only sequence handlers.

Covers: seq_stats, seq_ops, fastq_qc, seq_convert.

These handlers use Biopython (which is installed in the venv), so we feed
tiny real FASTA/FASTQ/GenBank files and let real parsing happen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap import tools  # noqa: E402
from bacmap.tools import seq as tools_seq  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result: str) -> dict:
    return json.loads(result)


# Tiny FASTA: two records, distinct GC contents.
FASTA_TWO = """\
>seq1 description one
ACGTACGTACGTACGTACGTACGTACGTACGT
>seq2
GGGGCCCCGGGGCCCCGGGGCCCCGGGGCCCC
"""


# Tiny FASTQ (4 lines per record): id, seq, plus, quals (all Q30).
FASTQ_TWO = """\
@read1
ACGTACGTACGT
+
IIIIIIIIIIII
@read2
TTTTGGGGCCCC
+
IIIIIIIIIIII
"""


# Tiny GenBank record.
GENBANK_ONE = """\
LOCUS       TEST    20 bp    DNA     linear   UNK 01-JAN-2025
DEFINITION  Test record.
ACCESSION   TEST
VERSION     TEST.1
ORIGIN
        1 acgtacgtac gtacgtacgt
//
"""


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content)
    return str(p)


# ===========================================================================
# seq_stats
# ===========================================================================


class TestSeqStats:
    def test_missing_file_returns_error(self):
        r = _parse(tools.seq_stats({"file": "/no/such/file.fa"}))
        assert "error" in r
        assert "not found" in r["error"].lower() or "File not found" in r["error"]

    def test_fasta_basic_stats(self, tmp_path):
        path = _write(tmp_path, "demo.fa", FASTA_TWO)
        r = _parse(tools.seq_stats({"file": path}))
        assert r["format"] == "fasta"
        assert r["record_count"] == 2
        assert r["total_bases"] == 64
        assert r["length"]["min"] == 32
        assert r["length"]["max"] == 32
        assert r["length"]["mean"] == 32.0
        # seq1 ACGT*8 → 16 GC of 32; seq2 GGGGCCCC*4 → 32 GC of 32 → total 48/64 = 75.0
        assert r["gc_content"] == pytest.approx(75.0, abs=0.01)
        assert r["length_histogram"]
        assert len(r["top_records_by_length"]) == 2

    def test_fasta_explicit_format_hint(self, tmp_path):
        path = _write(tmp_path, "demo.fa", FASTA_TWO)
        r = _parse(tools.seq_stats({"file": path, "format": "fasta"}))
        assert r["format"] == "fasta"
        assert r["record_count"] == 2

    def test_histogram_bins_arg(self, tmp_path):
        path = _write(tmp_path, "demo.fa", FASTA_TWO)
        r = _parse(tools.seq_stats({"file": path, "histogram_bins": 5}))
        # Both records have same length → 1 bucket regardless
        assert isinstance(r["length_histogram"], list)

    def test_fastq_includes_quality_block(self, tmp_path):
        path = _write(tmp_path, "demo.fastq", FASTQ_TWO)
        r = _parse(tools.seq_stats({"file": path}))
        assert r["format"] == "fastq"
        assert r["record_count"] == 2
        assert "quality" in r
        assert r["quality"]["mean_q"] == pytest.approx(40.0, abs=0.5)
        # All quals are 'I' = 40 → q30 fraction = 1.0
        assert r["quality"]["q30_fraction"] == 1.0
        assert r["quality"]["q20_fraction"] == 1.0
        assert isinstance(r["quality"]["per_position_mean_q"], list)

    def test_empty_fasta_returns_no_records_error(self, tmp_path):
        path = _write(tmp_path, "empty.fa", "")
        r = _parse(tools.seq_stats({"file": path}))
        assert "error" in r
        assert "No records" in r["error"]

    def test_garbage_file_returns_parse_error(self, tmp_path):
        # File has .fa ext so parser tries fasta on junk → records=[] OR exception
        path = _write(tmp_path, "junk.fa", "this is not\nfasta\n>>bad\n")
        r = _parse(tools.seq_stats({"file": path}))
        # Either we get an error string OR an empty-records error: both are
        # acceptable "graceful failure" outcomes.
        assert "error" in r

    def test_biopython_unavailable_path(self, tmp_path, monkeypatch):
        path = _write(tmp_path, "demo.fa", FASTA_TWO)
        monkeypatch.setattr(tools_seq, "_ensure_biopython", lambda: False)
        r = _parse(tools.seq_stats({"file": path}))
        assert "Biopython" in r["error"]

    def test_n50_calc_helper(self):
        # 3 contigs summing to 12; half = 6; sorted desc [5,4,3]; cumsum 5 (<6),
        # 9 (>=6) → N50 = 4.
        assert tools_seq._calc_n50([3, 4, 5]) == 4

    def test_median_helper(self):
        assert tools_seq._median([1, 3, 5]) == 3
        assert tools_seq._median([1, 2, 3, 4]) == 2.5
        assert tools_seq._median([]) == 0
        assert tools_seq._median([7]) == 7

    def test_histogram_helper(self):
        h = tools_seq._histogram([10, 20, 30], bins=2)
        assert len(h) == 2
        assert sum(b["count"] for b in h) == 3
        # All-same-values returns single bucket.
        assert tools_seq._histogram([5, 5, 5]) == [{"bin": "5", "count": 3}]
        assert tools_seq._histogram([]) == []


# ===========================================================================
# seq_ops
# ===========================================================================


class TestSeqOps:
    def test_missing_operation(self):
        r = _parse(tools.seq_ops({}))
        assert "operation" in r["error"]

    def test_unknown_operation(self):
        r = _parse(tools.seq_ops({"operation": "bogus", "sequence": "ACGT"}))
        assert "Unknown operation" in r["error"]

    # -- reverse_complement --
    def test_reverse_complement_basic(self):
        r = _parse(tools.seq_ops({"operation": "reverse_complement", "sequence": "AAAACCCGGT"}))
        assert r["input_length"] == 10
        assert r["reverse_complement"] == "ACCGGGTTTT"

    def test_reverse_complement_no_input(self):
        r = _parse(tools.seq_ops({"operation": "reverse_complement"}))
        assert "error" in r

    def test_reverse_complement_from_file(self, tmp_path):
        path = _write(tmp_path, "x.fa", FASTA_TWO)
        r = _parse(tools.seq_ops({"operation": "reverse_complement", "file": path}))
        assert r["input_length"] == 32
        # seq1 = ACGTACGT... → complement TGCATGCA → reversed ACGTACGT (palindrome)
        assert r["reverse_complement"].startswith("ACGT")

    def test_reverse_complement_specific_record_from_file(self, tmp_path):
        path = _write(tmp_path, "x.fa", FASTA_TWO)
        r = _parse(
            tools.seq_ops({"operation": "reverse_complement", "file": path, "record_id": "seq2"})
        )
        # seq2 = GGGGCCCC... → complement CCCCGGGG → reversed GGGGCCCC (palindrome)
        assert r["reverse_complement"].startswith("GGGG")

    def test_reverse_complement_missing_record_from_file(self, tmp_path):
        path = _write(tmp_path, "x.fa", FASTA_TWO)
        r = _parse(
            tools.seq_ops({"operation": "reverse_complement", "file": path, "record_id": "nope"})
        )
        assert "not found" in r["error"]

    def test_file_input_not_found(self):
        r = _parse(tools.seq_ops({"operation": "gc_content", "file": "/no/such/file.fa"}))
        assert "not found" in r["error"]

    # -- translate --
    def test_translate_basic(self):
        # ATG-AAA-TAG → MK*
        r = _parse(tools.seq_ops({"operation": "translate", "sequence": "ATGAAATAG"}))
        assert r["protein"] == "MK*"
        assert r["protein_length"] == 3
        assert r["frame"] == 0

    def test_translate_with_frame(self):
        r = _parse(tools.seq_ops({"operation": "translate", "sequence": "XATGAAATAG", "frame": 1}))
        assert r["frame"] == 1
        assert r["protein"] == "MK*"

    # -- gc_content --
    def test_gc_content_basic(self):
        r = _parse(tools.seq_ops({"operation": "gc_content", "sequence": "GGCC"}))
        assert r["length"] == 4
        assert r["gc_count"] == 4
        assert r["gc_content"] == 100.0

    def test_gc_content_empty(self):
        # _get_sequence treats empty string as "no sequence" → falls through to
        # "Provide 'sequence' or 'file'" validation error.
        r = _parse(tools.seq_ops({"operation": "gc_content", "sequence": ""}))
        assert "error" in r

    # -- gc_skew --
    def test_gc_skew_basic(self):
        r = _parse(tools.seq_ops({"operation": "gc_skew", "sequence": "GGGGCCCC", "window": 4}))
        assert r["window_size"] == 4
        assert len(r["skew_profile"]) == 2
        # First window GGGG: g=4 c=0 → skew = 1.0
        assert r["skew_profile"][0]["skew"] == 1.0
        # Second window CCCC: g=0 c=4 → skew = -1.0
        assert r["skew_profile"][1]["skew"] == -1.0

    # -- motif_search --
    def test_motif_search_basic(self):
        r = _parse(
            tools.seq_ops(
                {"operation": "motif_search", "sequence": "GAATTCGAATTC", "motif": "GAATTC"}
            )
        )
        assert r["match_count"] == 2
        assert r["positions"] == [[0, 6], [6, 12]]

    def test_motif_search_iupac(self):
        # 'R' = [AG], pattern 'GARTC' matches GAATC / GAGTC
        r = _parse(
            tools.seq_ops({"operation": "motif_search", "sequence": "GAATCGAGTC", "motif": "GARTC"})
        )
        assert r["match_count"] == 2

    def test_motif_search_missing_motif(self):
        r = _parse(tools.seq_ops({"operation": "motif_search", "sequence": "ACGT"}))
        assert "motif" in r["error"]

    # -- find_orfs --
    def test_find_orfs_basic(self):
        # ORF: ATG AAA AAA TAA = ATGAAATAA (len 9, 3 codons)
        s = "GGATCC" + "ATGAAATAA" + "GAATTC"
        r = _parse(tools.seq_ops({"operation": "find_orfs", "sequence": s, "min_orf_len": 3}))
        assert r["orf_count"] >= 1
        assert any(o["length_codons"] == 3 for o in r["orfs"])

    # -- restriction_sites --
    def test_restriction_sites_basic(self):
        # EcoRI: GAATTC — present twice in "GAATTCGAATTC".
        r = _parse(
            tools.seq_ops({"operation": "restriction_sites", "sequence": "GAATTCGAATTCNNNN"})
        )
        assert "EcoRI" in r["restriction_sites"]
        assert r["restriction_sites"]["EcoRI"]["count"] == 2

    def test_restriction_sites_none(self):
        r = _parse(tools.seq_ops({"operation": "restriction_sites", "sequence": "ACGTACGT"}))
        assert r["restriction_sites"] == {}

    # -- kmer_count --
    def test_kmer_count_default(self):
        r = _parse(tools.seq_ops({"operation": "kmer_count", "sequence": "ACGTACGT", "k": 2}))
        # 2-mers in ACGTACGT (len 8, k=2): AC, CG, GT, TA, AC, CG, GT = 7 windows
        assert r["k"] == 2
        # unique 2-mers: AC, CG, GT, TA = 4
        assert r["unique_kmers"] == 4

    def test_kmer_count_writes_output_file(self, tmp_path):
        out = tmp_path / "kmers.tsv"
        r = _parse(
            tools.seq_ops(
                {
                    "operation": "kmer_count",
                    "sequence": "ACGTACGT",
                    "k": 2,
                    "output_file": str(out),
                }
            )
        )
        assert r["unique_kmers"] == 4
        assert out.exists()
        content = out.read_text()
        assert "AC" in content


# ===========================================================================
# fastq_qc
# ===========================================================================


class TestFastqQc:
    def test_no_files_returns_error(self):
        r = _parse(tools.fastq_qc({}))
        assert "error" in r

    def test_file_not_found_marks_error_per_file(self):
        r = _parse(tools.fastq_qc({"files": ["/no/such.fastq"]}))
        assert r["files"][0]["error"] == "not found"

    def test_basic_fastq(self, tmp_path):
        path = _write(tmp_path, "r.fastq", FASTQ_TWO)
        r = _parse(tools.fastq_qc({"files": [path]}))
        assert len(r["files"]) == 1
        fr = r["files"][0]
        assert fr["reads_sampled"] == 2
        assert fr["length_min"] == 12
        assert fr["length_max"] == 12
        assert fr["length_mean"] == 12.0
        assert fr["duplication_rate"] == 0.0
        # summary
        assert r["summary"]["overall_mean_q"] == pytest.approx(40.0, abs=0.5)
        assert r["summary"]["q30_fraction"] == 1.0
        assert r["summary"]["total_reads_sampled"] == 2
        assert "length_distribution" in r["summary"]

    def test_multiple_files(self, tmp_path):
        p1 = _write(tmp_path, "r1.fastq", FASTQ_TWO)
        p2 = _write(tmp_path, "r2.fastq", FASTQ_TWO)
        r = _parse(tools.fastq_qc({"files": [p1, p2]}))
        assert len(r["files"]) == 2
        assert r["summary"]["total_reads_sampled"] == 4

    def test_sample_reads_limit(self, tmp_path):
        # Larger file but sampled.
        big = "".join([FASTQ_TWO] * 10)  # 20 reads
        path = _write(tmp_path, "big.fastq", big)
        r = _parse(tools.fastq_qc({"files": [path], "sample_reads": 5}))
        assert r["files"][0]["reads_sampled"] == 5

    def test_adapter_check(self, tmp_path):
        adapter_text = ">adapter1\nACGTACGTACGT\n"
        adapter_path = _write(tmp_path, "adapters.fa", adapter_text)
        fq_path = _write(tmp_path, "r.fastq", FASTQ_TWO)
        r = _parse(tools.fastq_qc({"files": [fq_path], "adapter_file": adapter_path}))
        assert "adapter_contamination" in r
        assert r["adapter_contamination"]["total_checked"] == 2

    def test_report_file_written(self, tmp_path):
        fq_path = _write(tmp_path, "r.fastq", FASTQ_TWO)
        md = tmp_path / "report.md"
        r = _parse(tools.fastq_qc({"files": [fq_path], "report_file": str(md)}))
        assert "summary" in r  # still returns JSON
        assert md.exists()
        content = md.read_text()
        assert "FASTQ Quality Control" in content

    def test_biopython_unavailable(self, tmp_path, monkeypatch):
        path = _write(tmp_path, "r.fastq", FASTQ_TWO)
        monkeypatch.setattr(tools_seq, "_ensure_biopython", lambda: False)
        r = _parse(tools.fastq_qc({"files": [path]}))
        assert "Biopython" in r["error"]


# ===========================================================================
# seq_convert
# ===========================================================================


class TestSeqConvert:
    def test_input_not_found(self):
        r = _parse(tools.seq_convert({"input_file": "/no/such.fa", "output_file": "/tmp/out.fa"}))
        assert "Input not found" in r["error"]

    def test_missing_output_file(self, tmp_path):
        path = _write(tmp_path, "in.fa", FASTA_TWO)
        r = _parse(tools.seq_convert({"input_file": path}))
        assert "output_file" in r["error"]

    def test_convert_fasta_to_fastq_fails_gracefully(self, tmp_path):
        # FASTA→FASTQ requires quality scores which aren't present → error.
        in_path = _write(tmp_path, "in.fa", FASTA_TWO)
        out_path = str(tmp_path / "out.fastq")
        r = _parse(
            tools.seq_convert(
                {"input_file": in_path, "output_file": out_path, "output_format": "fastq"}
            )
        )
        assert "error" in r

    def test_convert_fasta_to_genbank(self, tmp_path):
        in_path = _write(tmp_path, "in.fa", FASTA_TWO)
        out_path = str(tmp_path / "out.gb")
        r = _parse(
            tools.seq_convert(
                {
                    "input_file": in_path,
                    "output_file": out_path,
                    "output_format": "genbank",
                }
            )
        )
        assert r["output_format"] == "genbank"
        assert r["records_converted"] == 2
        assert Path(out_path).exists()
        text = Path(out_path).read_text()
        assert "LOCUS" in text

    def test_convert_fasta_to_fasta_roundtrip(self, tmp_path):
        in_path = _write(tmp_path, "in.fa", FASTA_TWO)
        out_path = str(tmp_path / "out.fa")
        r = _parse(tools.seq_convert({"input_file": in_path, "output_file": out_path}))
        assert r["output_format"] == "fasta"
        assert r["records_converted"] == 2
        assert Path(out_path).exists()

    def test_convert_unknown_format_returns_error(self, tmp_path):
        in_path = _write(tmp_path, "in.fa", FASTA_TWO)
        out_path = str(tmp_path / "out.xyz")
        r = _parse(
            tools.seq_convert(
                {
                    "input_file": in_path,
                    "output_file": out_path,
                    "output_format": "totally_unknown_format",
                }
            )
        )
        assert "error" in r

    def test_convert_empty_input(self, tmp_path):
        in_path = _write(tmp_path, "empty.fa", "")
        out_path = str(tmp_path / "out.fa")
        r = _parse(tools.seq_convert({"input_file": in_path, "output_file": out_path}))
        assert "No records" in r["error"]

    def test_biopython_unavailable(self, tmp_path, monkeypatch):
        in_path = _write(tmp_path, "in.fa", FASTA_TWO)
        monkeypatch.setattr(tools_seq, "_ensure_biopython", lambda: False)
        r = _parse(
            tools.seq_convert({"input_file": in_path, "output_file": str(tmp_path / "out.fa")})
        )
        assert "Biopython" in r["error"]

    def test_format_detection_alias(self):
        # Extension aliases should map to canonical names.
        assert tools_seq._detect_format("/x/y.fna") == "fasta"
        assert tools_seq._detect_format("/x/y.fq") == "fastq"
        assert tools_seq._detect_format("/x/y.gb") == "genbank"
        # Hint wins over extension.
        assert tools_seq._detect_format("/x/y.fa", hint="genbank") == "genbank"
        # No suffix → fasta default.
        assert tools_seq._detect_format("/x/y_noext") == "fasta"
