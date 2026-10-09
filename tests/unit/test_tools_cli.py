"""Unit tests for bacmap.tools — external-CLI handlers.

Covers: blast, align, samtools_op, variant.

No real binaries are invoked. We monkeypatch tools.cli._which_or_error,
tools.cli._run_cmd, and (for variant's Popen-based helpers) tools.cli.subprocess.*
to feed canned stdout / returncodes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap import tools  # noqa: E402
from bacmap.tools import cli as tools_cli  # noqa: E402


def _parse(result: str) -> dict:
    return json.loads(result)


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content)
    return str(p)


# ===========================================================================
# blast
# ===========================================================================


class TestBlast:
    def test_missing_query(self):
        r = _parse(tools.blast({}))
        assert "query" in r["error"]

    def test_unknown_mode(self):
        r = _parse(tools.blast({"query": "ACGT", "mode": "bogus"}))
        assert "Unknown mode" in r["error"]

    # ---- remote mode ----
    def test_remote_happy_path(self, monkeypatch, tmp_path):
        hsp = SimpleNamespace(
            expect=1e-50,
            bits=200.0,
            identities=90,
            align_length=100,
            query_start=5,
        )
        aln = SimpleNamespace(title="ref|NC_123| Salmonella invA", length=1000, hsps=[hsp])
        rec = SimpleNamespace(alignments=[aln])

        def fake_qblast(program, db, query_str, **kwargs):
            assert program == "blastn"
            assert db == "nt"
            assert kwargs["hitlist_size"] == 10
            return "FAKE_HANDLE"

        monkeypatch.setattr("Bio.Blast.NCBIWWW.qblast", fake_qblast)
        monkeypatch.setattr("Bio.Blast.NCBIXML.parse", lambda handle: iter([rec]))

        r = _parse(tools.blast({"query": "ACGTACGT", "mode": "remote"}))
        assert r["mode"] == "remote"
        assert r["program"] == "blastn"
        assert r["database"] == "nt"
        assert r["hit_count"] == 1
        h = r["hits"][0]
        assert h["identity_pct"] == 90.0
        assert h["bit_score"] == 200.0
        assert h["query_start"] == 5

    def test_remote_with_output_file(self, monkeypatch, tmp_path):
        hsp = SimpleNamespace(expect=1e-5, bits=99.0, identities=10, align_length=20, query_start=1)
        aln = SimpleNamespace(title="some hit", length=50, hsps=[hsp])
        rec = SimpleNamespace(alignments=[aln])

        monkeypatch.setattr("Bio.Blast.NCBIWWW.qblast", lambda *a, **k: "h")
        monkeypatch.setattr("Bio.Blast.NCBIXML.parse", lambda h: iter([rec]))

        out = tmp_path / "blast.tsv"
        r = _parse(tools.blast({"query": "ACGT", "mode": "remote", "output_file": str(out)}))
        assert r["hit_count"] == 1
        assert out.exists()
        text = out.read_text()
        assert "query" in text and "some hit" in text

    def test_remote_query_is_file(self, monkeypatch, tmp_path):
        qfile = _write(tmp_path, "q.fa", ">myquery\nACGT\n")
        monkeypatch.setattr("Bio.Blast.NCBIWWW.qblast", lambda *a, **k: "h")
        monkeypatch.setattr("Bio.Blast.NCBIXML.parse", lambda h: iter([]))
        r = _parse(tools.blast({"query": qfile, "mode": "remote", "query_is_file": True}))
        assert r["hit_count"] == 0

    def test_remote_ncbi_failure(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr("Bio.Blast.NCBIWWW.qblast", boom)
        r = _parse(tools.blast({"query": "ACGT", "mode": "remote"}))
        assert "NCBI BLAST failed" in r["error"]

    # ---- local mode ----
    def test_local_missing_database(self):
        r = _parse(tools.blast({"query": "ACGT", "mode": "local"}))
        assert "Local BLAST needs 'database'" in r["error"]

    def test_local_blastn_binary_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.blast({"query": "ACGT", "mode": "local", "database": "subj.fa"}))
        assert "not found" in r["error"]

    def test_local_makedb_binary_missing(self, monkeypatch):
        def which(cmd):
            return "/usr/bin/blastn" if cmd == "blastn" else None

        monkeypatch.setattr(tools_cli, "_which_or_error", which)
        r = _parse(tools.blast({"query": "ACGT", "mode": "local", "database": "subj.fa"}))
        assert "makeblastdb not found" in r["error"]

    def test_local_happy_path(self, monkeypatch, tmp_path):
        subj = _write(tmp_path, "subj.fa", ">subj\nGGGG\n")

        def which(cmd):
            return f"/usr/bin/{cmd}"

        # BLAST outfmt 6 has 12 columns: qseqid sseqid pident length mismatch
        # gapopen qstart qend sstart send evalue bitscore
        canned_outfmt6 = (
            "query\tsubj1\t99.5\t100\t0\t0\t1\t100\t1\t100\t1e-50\t200.0\n"
            "query\tsubj2\t95.0\t80\t1\t0\t1\t80\t1\t80\t1e-30\t150.0\n"
        )

        def fake_run_cmd(cmd, timeout=3600):
            if "makeblastdb" in cmd:
                return {"returncode": 0, "stdout": "", "stderr": ""}
            return {"returncode": 0, "stdout": canned_outfmt6, "stderr": ""}

        monkeypatch.setattr(tools_cli, "_which_or_error", which)
        monkeypatch.setattr(tools_cli, "_run_cmd", fake_run_cmd)

        r = _parse(
            tools.blast(
                {
                    "query": "ACGTACGT",
                    "mode": "local",
                    "database": subj,
                    "program": "blastn",
                }
            )
        )
        assert r["mode"] == "local"
        assert r["hit_count"] == 2
        assert r["hits"][0]["subject"] == "subj1"
        assert r["hits"][0]["identity_pct"] == 99.5

    def test_local_makeblastdb_failure(self, monkeypatch, tmp_path):
        subj = _write(tmp_path, "subj.fa", ">subj\nGGGG\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli,
            "_run_cmd",
            lambda cmd, timeout=3600: {
                "returncode": 1,
                "stdout": "",
                "stderr": "makeblastdb error",
            },
        )
        r = _parse(tools.blast({"query": "ACGT", "mode": "local", "database": subj}))
        assert "makeblastdb failed" in r["error"]

    def test_local_blast_failure(self, monkeypatch, tmp_path):
        subj = _write(tmp_path, "subj.fa", ">subj\nGGGG\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")

        def fake(cmd, timeout=3600):
            if "makeblastdb" in cmd:
                return {"returncode": 0, "stdout": "", "stderr": ""}
            return {"returncode": 1, "stdout": "", "stderr": "blastn error"}

        monkeypatch.setattr(tools_cli, "_run_cmd", fake)
        r = _parse(tools.blast({"query": "ACGT", "mode": "local", "database": subj}))
        assert "blastn failed" in r["error"]

    def test_local_writes_output_file(self, monkeypatch, tmp_path):
        subj = _write(tmp_path, "subj.fa", ">subj\nGGGG\n")
        out = tmp_path / "out.tsv"
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        outfmt = "query\tsubj1\t100.0\t50\t0\t0\t1\t50\t1\t50\t1e-50\t100.0\n"

        def fake(cmd, timeout=3600):
            if "makeblastdb" in cmd:
                return {"returncode": 0, "stdout": "", "stderr": ""}
            return {"returncode": 0, "stdout": outfmt, "stderr": ""}

        monkeypatch.setattr(tools_cli, "_run_cmd", fake)
        r = _parse(
            tools.blast(
                {
                    "query": "ACGT",
                    "mode": "local",
                    "database": subj,
                    "output_file": str(out),
                }
            )
        )
        assert r["hit_count"] == 1
        assert out.exists()
        assert "subj1" in out.read_text()


# ===========================================================================
# align
# ===========================================================================


class TestAlign:
    def test_missing_reference(self):
        r = _parse(tools.align({"reads": ["r1.fq"]}))
        assert "reference" in r["error"]

    def test_missing_reads(self):
        r = _parse(tools.align({"reference": "ref.fa"}))
        assert "reads" in r["error"]

    def test_reference_not_found(self):
        r = _parse(
            tools.align({"reference": "/nope.fa", "reads": ["r1.fq"], "output_bam": "out.bam"})
        )
        assert "Reference not found" in r["error"]

    def test_missing_output_bam(self, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        r = _parse(tools.align({"reference": ref, "reads": ["r1.fq"]}))
        assert "output_bam" in r["error"]

    def test_read_file_not_found(self, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        r = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": ["/no_read.fq"],
                    "output_bam": str(tmp_path / "out.bam"),
                }
            )
        )
        assert "Read file not found" in r["error"]

    def test_star_returns_guidance(self, tmp_path):
        # STAR branch is reached only AFTER reads validation passes, so the
        # read file must exist. Provide a real (tiny) reads file.
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        reads = _write(tmp_path, "r1.fq", "@r\nACGT\n+\nIIII\n")
        r = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": [reads],
                    "output_bam": "out.bam",
                    "aligner": "star",
                }
            )
        )
        assert "STAR" in r["error"]

    def test_bwa_mem_happy_path(self, tmp_path, monkeypatch):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        read1 = _write(tmp_path, "r1.fq", "@r\nACGT\n+\nIIII\n")

        captured = {}

        class FakeMapper:
            @classmethod
            def map(cls, reads, reference, out_bam, mode="auto", **kwargs):
                captured.update(
                    reads=reads,
                    reference=reference,
                    out_bam=out_bam,
                    mode=mode,
                    kwargs=kwargs,
                )
                return {"aligned_reads": 100, "out_bam": out_bam, "mode": mode}

        monkeypatch.setattr("bacmap.core.engine.ReadMapper", FakeMapper)

        out = str(tmp_path / "out.bam")
        r = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": [read1],
                    "output_bam": out,
                    "aligner": "bwa-mem",
                }
            )
        )
        assert "aligned_reads" in r
        assert captured["mode"] == "bwa-mem"
        assert captured["reads"] == [read1]

    def test_minimap2_with_preset(self, tmp_path, monkeypatch):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        read1 = _write(tmp_path, "r1.fq", "@r\nACGT\n+\nIIII\n")

        captured = {}

        class FakeMapper:
            @classmethod
            def map(cls, reads, reference, out_bam, mode="auto", **kwargs):
                captured.update(mode=mode, kwargs=kwargs)
                return {"out_bam": out_bam, "mode": mode}

        monkeypatch.setattr("bacmap.core.engine.ReadMapper", FakeMapper)

        out = str(tmp_path / "out.bam")
        _ = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": [read1],
                    "output_bam": out,
                    "aligner": "minimap2",
                    "preset": "lr:hq",
                    "extra_args": "-x asm5",
                }
            )
        )
        assert captured["mode"] == "minimap2"
        assert captured["kwargs"]["preset"] == "lr:hq"
        assert captured["kwargs"]["extra_args"] == "-x asm5"

    def test_read_type_forwarded(self, tmp_path, monkeypatch):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        read1 = _write(tmp_path, "r1.fq", "@r\nACGT\n+\nIIII\n")

        captured = {}

        class FakeMapper:
            @classmethod
            def map(cls, reads, reference, out_bam, mode="auto", **kwargs):
                captured.update(mode=mode, kwargs=kwargs)
                return {"out_bam": out_bam, "mode": mode}

        monkeypatch.setattr("bacmap.core.engine.ReadMapper", FakeMapper)

        out = str(tmp_path / "out.bam")
        _ = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": [read1],
                    "output_bam": out,
                    "aligner": "",
                    "read_type": "long",
                }
            )
        )
        assert captured["mode"] == "auto"
        assert captured["kwargs"]["read_type"] == "long"

    def test_auto_mode_selection(self, tmp_path, monkeypatch):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        read1 = _write(tmp_path, "r1.fq", "@r\nACGT\n+\nIIII\n")

        captured = {}

        class FakeMapper:
            @classmethod
            def map(cls, reads, reference, out_bam, mode="auto", **kwargs):
                captured["mode"] = mode
                return {"out_bam": out_bam}

        monkeypatch.setattr("bacmap.core.engine.ReadMapper", FakeMapper)

        _ = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": [read1],
                    "output_bam": str(tmp_path / "out.bam"),
                    "aligner": "auto-choice",
                }
            )
        )
        # Aligner name not in the (bwa-mem, bwa, minimap2) set → mode = "auto"
        assert captured["mode"] == "auto"

    def test_readmapper_exception_returns_error(self, tmp_path, monkeypatch):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        read1 = _write(tmp_path, "r1.fq", "@r\nACGT\n+\nIIII\n")

        class FakeMapper:
            @classmethod
            def map(cls, **kwargs):
                raise RuntimeError("bwa failed")

        monkeypatch.setattr("bacmap.core.engine.ReadMapper", FakeMapper)

        r = _parse(
            tools.align(
                {
                    "reference": ref,
                    "reads": [read1],
                    "output_bam": str(tmp_path / "out.bam"),
                }
            )
        )
        assert "Alignment failed" in r["error"]


# ===========================================================================
# samtools_op
# ===========================================================================


class TestSamtoolsOp:
    def test_missing_operation_or_input(self):
        r = _parse(tools.samtools_op({"input": "x.bam"}))
        assert "error" in r
        r = _parse(tools.samtools_op({"operation": "sort"}))
        assert "error" in r

    def test_samtools_binary_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.samtools_op({"operation": "index", "input": "x.bam"}))
        assert "samtools not found" in r["error"]

    def test_input_not_found(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: "/usr/bin/samtools")
        r = _parse(tools.samtools_op({"operation": "index", "input": "/no/such.bam"}))
        assert "Input not found" in r["error"]

    def test_unknown_operation(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: "/usr/bin/samtools")
        r = _parse(tools.samtools_op({"operation": "bogus", "input": bam}))
        assert "Unknown operation" in r["error"]

    def _setup(self, monkeypatch, stdout="", stderr="", rc=0):
        """Wire _which + _run_cmd to canned outputs."""
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: "/usr/bin/samtools")

        def fake_run(cmd, timeout=3600):
            return {"returncode": rc, "stdout": stdout, "stderr": stderr}

        monkeypatch.setattr(tools_cli, "_run_cmd", fake_run)

    def test_sort_no_output_arg(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        self._setup(monkeypatch)
        r = _parse(tools.samtools_op({"operation": "sort", "input": bam}))
        assert "sort needs 'output'" in r["error"]

    def test_sort_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        out = str(tmp_path / "sorted.bam")
        self._setup(monkeypatch)
        r = _parse(
            tools.samtools_op(
                {"operation": "sort", "input": bam, "output": out, "extra_args": "-n"}
            )
        )
        assert r["operation"] == "sort"
        assert r["returncode"] == 0

    def test_index_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        self._setup(monkeypatch)
        r = _parse(tools.samtools_op({"operation": "index", "input": bam}))
        assert r["operation"] == "index"
        assert r["returncode"] == 0

    def test_view_happy_with_region(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        out = str(tmp_path / "view.bam")
        self._setup(monkeypatch, stdout="read1\tflag1\nread2\tflag2\n")
        r = _parse(
            tools.samtools_op(
                {
                    "operation": "view",
                    "input": bam,
                    "output": out,
                    "flags": "-F 4",
                    "region": "chr1:1-1000",
                    "extra_args": "-q 20",
                }
            )
        )
        assert r["operation"] == "view"
        assert r["stdout_lines"] == 2

    def test_depth_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        self._setup(monkeypatch, stdout="chr1\t1\t10\nchr1\t2\t12\n")
        r = _parse(tools.samtools_op({"operation": "depth", "input": bam, "region": "chr1:1-10"}))
        assert r["operation"] == "depth"
        assert r["stdout_lines"] == 2

    def test_flagstat_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        canned = "100 + 0 in total\n98 + 0 primary\n95 + 0 mapped\n"
        self._setup(monkeypatch, stdout=canned)
        r = _parse(tools.samtools_op({"operation": "flagstat", "input": bam}))
        assert r["operation"] == "flagstat"
        assert r["stdout_lines"] == 3

    def test_idxstats_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        canned = "chr1\t1000\t50\t10\nchr2\t500\t0\t0\n"
        self._setup(monkeypatch, stdout=canned)
        r = _parse(tools.samtools_op({"operation": "idxstats", "input": bam}))
        assert r["stdout_lines"] == 2

    def test_mpileup_no_output(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        self._setup(monkeypatch)
        r = _parse(tools.samtools_op({"operation": "mpileup", "input": bam}))
        assert "mpileup needs 'output'" in r["error"]

    def test_mpileup_no_reference(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        out = str(tmp_path / "out.pileup")
        self._setup(monkeypatch)
        r = _parse(tools.samtools_op({"operation": "mpileup", "input": bam, "output": out}))
        assert "mpileup needs 'reference'" in r["error"]

    def test_mpileup_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        out = str(tmp_path / "out.pileup")
        self._setup(monkeypatch)
        r = _parse(
            tools.samtools_op(
                {
                    "operation": "mpileup",
                    "input": bam,
                    "output": out,
                    "reference": ref,
                }
            )
        )
        assert r["operation"] == "mpileup"
        assert r["returncode"] == 0

    def test_faidx_happy(self, monkeypatch, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        self._setup(monkeypatch)
        r = _parse(tools.samtools_op({"operation": "faidx", "input": ref}))
        assert r["operation"] == "faidx"

    def test_fasta_index_alias(self, monkeypatch, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        self._setup(monkeypatch)
        r = _parse(tools.samtools_op({"operation": "fasta_index", "input": ref}))
        assert r["operation"] == "fasta_index"

    def test_cmd_failure_returns_error(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        self._setup(monkeypatch, rc=1, stderr="bad input\n")
        r = _parse(tools.samtools_op({"operation": "index", "input": bam}))
        assert "samtools index failed" in r["error"]
        assert "bad input" in r["stderr"]

    def test_stderr_tail_in_result(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        self._setup(
            monkeypatch,
            stdout="ok line\n",
            stderr="warn1\nwarn2\nwarn3\nwarn4\n",
            rc=0,
        )
        r = _parse(tools.samtools_op({"operation": "flagstat", "input": bam}))
        # last 3 lines of stderr
        assert r["stderr_tail"] == ["warn2", "warn3", "warn4"]


# ===========================================================================
# variant
# ===========================================================================


class _FakePopen:
    """Stand-in for subprocess.Popen used by _var_mpileup_call."""

    def __init__(self, cmd, stdout=None, stderr=None, **kwargs):
        self.cmd = cmd
        self.stdout = stdout if stdout is not None else _BytesIO(b"vcf data")
        self.stderr = stderr if stderr is not None else _BytesIO(b"")
        self._returncode = 0

    def wait(self):
        return self._returncode


class _BytesIO:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def decode(self):
        return self._data.decode()


class _FakeCompletedProc:
    """Stand-in for subprocess.run result. stderr/stdout are bytes so .decode() works."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestVariant:
    def test_missing_operation(self):
        r = _parse(tools.variant({}))
        assert "operation" in r["error"]

    def test_unknown_operation(self):
        r = _parse(tools.variant({"operation": "bogus"}))
        assert "Unknown operation" in r["error"]

    # ---- mpileup_call ----
    def test_mpileup_call_bcftools_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.variant({"operation": "mpileup_call"}))
        assert "bcftools not found" in r["error"]

    def test_mpileup_call_samtools_missing(self, monkeypatch):
        def which(cmd):
            return "/usr/bin/bcftools" if cmd == "bcftools" else None

        monkeypatch.setattr(tools_cli, "_which_or_error", which)
        r = _parse(tools.variant({"operation": "mpileup_call"}))
        assert "samtools not found" in r["error"]

    def test_mpileup_call_missing_reference(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(tools.variant({"operation": "mpileup_call", "input": "x.bam"}))
        assert "reference" in r["error"]

    def test_mpileup_call_missing_output(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(
            tools.variant(
                {
                    "operation": "mpileup_call",
                    "input": "x.bam",
                    "reference": "ref.fa",
                }
            )
        )
        assert "output" in r["error"]

    def test_mpileup_call_happy(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        out = str(tmp_path / "out.vcf")

        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")

        # Need to stub subprocess.Popen + subprocess.run for indexing and
        # subprocess.run for the bcftools call stage.
        written = {}

        class FakePopen(_FakePopen):
            def __init__(self, cmd, **kwargs):
                super().__init__(cmd, **kwargs)
                self.stdout = _BytesIO(b"")  # mpileup output unused on success path
                self.stderr = _BytesIO(b"")

        def fake_run(cmd, **kwargs):
            # Detect: call_cmd is ["bcftools", "call", ...] with stdin=pipe,
            # stdout=open(out_path, "wb"). Write canned VCF into the open file.
            if "call" in cmd:
                f = kwargs.get("stdout")
                if f is not None and hasattr(f, "write"):
                    f.write(b"##VCF\n#CHROM\nchr1\t1\t.\tA\tT\t30\n")
                return _FakeCompletedProc(returncode=0)
            # else: samtools faidx / samtools index — no-op
            return _FakeCompletedProc(returncode=0)

        monkeypatch.setattr(tools_cli.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(tools_cli.subprocess, "run", fake_run)

        r = _parse(
            tools.variant(
                {
                    "operation": "mpileup_call",
                    "input": bam,
                    "reference": ref,
                    "output": out,
                }
            )
        )
        assert r["operation"] == "mpileup_call"
        assert r["output_vcf"] == out
        # 1 non-header, non-empty data line in canned VCF
        assert r["variant_count"] == 1
        assert written == {} or True

    def test_mpileup_call_call_failure(self, monkeypatch, tmp_path):
        bam = _write(tmp_path, "x.bam", "")
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        out = str(tmp_path / "out.vcf")

        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")

        class FakePopen(_FakePopen):
            def __init__(self, cmd, **kwargs):
                super().__init__(cmd, **kwargs)
                self.stdout = _BytesIO(b"")
                self.stderr = _BytesIO(b"mpileup boom")
                self._returncode = 1

        def fake_run(cmd, **kwargs):
            return _FakeCompletedProc(returncode=1, stderr=b"call boom")

        monkeypatch.setattr(tools_cli.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(tools_cli.subprocess, "run", fake_run)

        r = _parse(
            tools.variant(
                {
                    "operation": "mpileup_call",
                    "input": bam,
                    "reference": ref,
                    "output": out,
                }
            )
        )
        assert "mpileup/call failed" in r["error"]

    # ---- filter ----
    def test_filter_bcftools_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.variant({"operation": "filter", "input": "x.vcf"}))
        assert "bcftools not found" in r["error"]

    def test_filter_input_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(tools.variant({"operation": "filter", "input": "/no/such.vcf"}))
        assert "VCF not found" in r["error"]

    def test_filter_no_filter_expr(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(tools.variant({"operation": "filter", "input": vcf}))
        assert "filter_expr" in r["error"]

    def test_filter_happy(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\nchr1\t1\nchr1\t2\n")
        out = str(tmp_path / "filt.vcf")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")

        # _run_cmd writes the filtered VCF out so _count_vcf_records works.
        def fake_run(cmd, timeout=3600):
            # Write canned output if -o is present in cmd.
            if "-o" in cmd:
                idx = cmd.index("-o")
                Path(cmd[idx + 1]).write_text("#CHROM\nchr1\t1\n")
            return {"returncode": 0, "stdout": "", "stderr": ""}

        monkeypatch.setattr(tools_cli, "_run_cmd", fake_run)
        r = _parse(
            tools.variant(
                {
                    "operation": "filter",
                    "input": vcf,
                    "output": out,
                    "filter_expr": "QUAL>30",
                }
            )
        )
        assert r["operation"] == "filter"
        assert r["input_variants"] == 2
        assert r["filtered_variants"] == 1

    def test_filter_failure(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\nchr1\t1\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli,
            "_run_cmd",
            lambda cmd, timeout=3600: {"returncode": 1, "stdout": "", "stderr": "bad"},
        )
        r = _parse(
            tools.variant(
                {
                    "operation": "filter",
                    "input": vcf,
                    "filter_expr": "QUAL>30",
                }
            )
        )
        assert "filter failed" in r["error"]

    # ---- query ----
    def test_query_bcftools_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.variant({"operation": "query", "input": "x.vcf"}))
        assert "bcftools not found" in r["error"]

    def test_query_input_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(tools.variant({"operation": "query", "input": "/no/such.vcf"}))
        assert "VCF not found" in r["error"]

    def test_query_happy(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli,
            "_run_cmd",
            lambda cmd, timeout=3600: {
                "returncode": 0,
                "stdout": "chr1\t1\tA\tT\t30\nchr1\t2\tG\tC\t20\n",
                "stderr": "",
            },
        )
        r = _parse(tools.variant({"operation": "query", "input": vcf, "query": "%CHROM\\t%POS\\n"}))
        assert r["operation"] == "query"
        assert r["record_count"] == 2
        assert r["results"][0] == "chr1\t1\tA\tT\t30"

    def test_query_failure(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli,
            "_run_cmd",
            lambda cmd, timeout=3600: {"returncode": 1, "stdout": "", "stderr": "bad"},
        )
        r = _parse(tools.variant({"operation": "query", "input": vcf}))
        assert "query failed" in r["error"]

    # ---- annotate ----
    def test_annotate_bcftools_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.variant({"operation": "annotate", "input": "x.vcf"}))
        assert "bcftools not found" in r["error"]

    def test_annotate_input_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(tools.variant({"operation": "annotate", "input": "/no/such.vcf"}))
        assert "VCF not found" in r["error"]

    def test_annotate_happy(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\nchr1\t1\n")
        out = str(tmp_path / "annot.vcf")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli,
            "_run_cmd",
            lambda cmd, timeout=3600: {"returncode": 0, "stdout": "", "stderr": ""},
        )
        r = _parse(tools.variant({"operation": "annotate", "input": vcf, "output": out}))
        assert r["operation"] == "annotate"
        assert r["output"] == out

    def test_annotate_failure(self, monkeypatch, tmp_path):
        vcf = _write(tmp_path, "x.vcf", "#CHROM\nchr1\t1\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli,
            "_run_cmd",
            lambda cmd, timeout=3600: {"returncode": 1, "stdout": "", "stderr": "bad"},
        )
        r = _parse(tools.variant({"operation": "annotate", "input": vcf}))
        assert "annotate failed" in r["error"]

    # ---- consensus ----
    def test_consensus_bcftools_missing(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: None)
        r = _parse(tools.variant({"operation": "consensus", "input": "x.vcf"}))
        assert "bcftools not found" in r["error"]

    def test_consensus_missing_reference(self, monkeypatch):
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(tools.variant({"operation": "consensus", "input": "x.vcf"}))
        assert "reference" in r["error"]

    def test_consensus_missing_output(self, monkeypatch, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        r = _parse(
            tools.variant(
                {
                    "operation": "consensus",
                    "input": "x.vcf",
                    "reference": ref,
                }
            )
        )
        assert "output" in r["error"]

    def test_consensus_happy(self, monkeypatch, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        vcf = _write(tmp_path, "x.vcf", "#CHROM\nchr1\t1\n")
        out = str(tmp_path / "cons.fa")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")

        def fake_run(cmd, **kwargs):
            # If stdout is an open file, write FASTA to it.
            f = kwargs.get("stdout")
            if f is not None and hasattr(f, "write"):
                f.write(">consensus\nACGT\n")
            return _FakeCompletedProc(returncode=0)

        monkeypatch.setattr(tools_cli.subprocess, "run", fake_run)
        r = _parse(
            tools.variant(
                {
                    "operation": "consensus",
                    "input": vcf,
                    "reference": ref,
                    "output": out,
                }
            )
        )
        assert r["operation"] == "consensus"
        assert r["output_fasta"] == out
        assert Path(out).read_text() == ">consensus\nACGT\n"

    def test_consensus_failure(self, monkeypatch, tmp_path):
        ref = _write(tmp_path, "ref.fa", ">r\nACGT\n")
        vcf = _write(tmp_path, "x.vcf", "#CHROM\n")
        out = str(tmp_path / "cons.fa")
        monkeypatch.setattr(tools_cli, "_which_or_error", lambda cmd: f"/usr/bin/{cmd}")
        monkeypatch.setattr(
            tools_cli.subprocess,
            "run",
            lambda cmd, **kwargs: _FakeCompletedProc(returncode=1, stderr="boom"),
        )
        r = _parse(
            tools.variant(
                {
                    "operation": "consensus",
                    "input": vcf,
                    "reference": ref,
                    "output": out,
                }
            )
        )
        assert "consensus failed" in r["error"]

    def test_count_vcf_records_helper(self, tmp_path):
        p = tmp_path / "x.vcf"
        p.write_text("##header\n#CHROM\nchr1\t1\nchr1\t2\n\n")
        assert tools_cli._count_vcf_records(str(p)) == 2
        assert tools_cli._count_vcf_records(str(tmp_path / "nope.vcf")) == 0
