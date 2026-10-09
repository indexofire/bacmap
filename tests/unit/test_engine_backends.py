"""Unit tests for engine backends: blast, minimap2, kma, kmer (mash + sourmash).

All external binaries (blastn, makeblastdb, minimap2, kma, mash, sourmash) are
mocked at the subprocess.run boundary; `which` is mocked per-backend-module
(since each backend imports `which` at module level from `.._env`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.engine.backends.blast import BlastBackend  # noqa: E402
from bacmap.core.engine.backends.kma import KmaBackend  # noqa: E402
from bacmap.core.engine.backends.kmer import (  # noqa: E402
    KmerDistance,
    MashBackend,
    SourmashBackend,
)
from bacmap.core.engine.backends.minimap2 import MinimapBackend  # noqa: E402

# -------------------------- canned backend output ---------------------------

# BLAST outfmt6: 14 cols (qseqid sseqid pident length mismatch gapopen
# qstart qend sstart send evalue bitscore qlen slen)
BLAST_OUT = (
    "q1\ts1\t98.50\t295\t3\t0\t1\t295\t10\t304\t1e-100\t500\t295\t300\n"
    "q2\ts2\t99.0\t200\t1\t0\t1\t200\t400\t201\t1e-50\t300\t200\t400\n"
)
# hit1: identity=98.5, aln=295, qlen=295 → qcov=100.0; slen=300 → scov≈98.33
#       sstart=10 <= send=304 → strand "+"
# hit2: identity=99.0, aln=200, qlen=200 → qcov=100.0; slen=400 → scov=50.0
#       sstart=400 > send=201 → strand "-"

PAF_OUT = (
    "q1\t1000\t100\t500\t+\tt1\t2000\t50\t450\t380\t400\t60\tNM:i:20\n"
    "q1\t1000\t100\t500\t-\tt2\t2000\t50\t450\t0\t0\t0\n"
)
# row1: nmatch=380, aln=400 → identity=95.0; qcov=(500-100)/1000*100=40.0;
#       scov=(450-50)/2000*100=20.0; mismatches=20
# row2: aln=0 → identity=0.0; qcov=40.0; scov=20.0

KMA_RES = (
    "#Template\tScore\tExpected\tTemplate_length\t"
    "Template_Identity\tTemplate_Coverage\tQuery_Identity\t"
    "Query_Coverage\tDepth\tq_value\tp_value\n"
    "db~~~gene1~~~acc1~~~product\t1000\t5\t500\t"
    "99.50\t100.00\t99.50\t100.00\t50.0\t100.0\t1e-50\n"
    "gene2\t100\t2\t200\t50.0\t30.0\t50.0\t30.0\t10.0\t50.0\t1e-10\n"
)
# row1: identity=99.5, coverage=100.0, depth=50.0
# row2: identity=50.0, coverage=30.0, depth=10.0

MASH_DIST_OUT = (
    "ref_genome\tquery_genome\t0.05\t0.001\t450/1000\nref2\tquery_genome\t0.02\t0.001\t500/1000\n"
)
MASH_DIST_OUT_NOSLASH = "ref_genome\tquery_genome\t0.05\t0.001\t450\t1000\n"

SOURMASH_CSV = (
    "query_name,intersect_bp,query_md5,match_name,query_containment,f_match\n"
    ",1500000,abc,gene_X,0.85,0.90\n"
)
# Header is recognised → skipped. Data row: 6 cols.
# q_name="" (len not > 6), ref_name=parts[3]="gene_X",
# containment=parts[-2]=0.85 → distance=0.15


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _which_resolver(name: str) -> str:
    """Default `which` fake: returns /fake/<name> for any tool."""
    return f"/fake/{name}"


# ===========================================================================
# BlastBackend
# ===========================================================================


class TestBlastInit:
    def test_init_succeeds_when_binary_found(self):
        with patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"):
            b = BlastBackend(tool="blastn", threads=2)
        assert b.tool == "blastn"
        assert b.threads == 2
        assert b._bin == "/fake/blastn"

    def test_default_tool_and_threads(self):
        with patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"):
            b = BlastBackend()
        assert b.tool == "blastn"
        assert b.threads == 4

    def test_init_raises_when_binary_missing(self):
        with patch("bacmap.core.engine.backends.blast.which", return_value=None):
            with pytest.raises(RuntimeError, match="blastn not found"):
                BlastBackend(tool="blastn")


class TestBlastMakeDb:
    def test_make_db_runs_correct_command(self, tmp_path):
        fasta = tmp_path / "ref.fasta"
        fasta.write_text(">seq\nACGT\n")
        db_path = tmp_path / "outdb"
        with (
            patch("bacmap.core.engine.backends.blast.which", side_effect=_which_resolver),
            patch(
                "bacmap.core.engine.backends.blast.subprocess.run",
                return_value=_proc(),
            ) as run,
        ):
            b = BlastBackend(tool="blastn")
            b.make_db(fasta, db_path, db_type="nucl")
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/makeblastdb"
        assert "-in" in cmd and str(fasta) in cmd
        assert "-dbtype" in cmd and "nucl" in cmd
        assert "-out" in cmd and str(db_path) in cmd

    def test_make_db_raises_when_makeblastdb_missing(self):
        def which_strict(name: str) -> str | None:
            return "/fake/blastn" if name == "blastn" else None

        with patch("bacmap.core.engine.backends.blast.which", side_effect=which_strict):
            b = BlastBackend(tool="blastn")
            with pytest.raises(RuntimeError, match="makeblastdb not found"):
                b.make_db(Path("ref.fasta"), Path("db"))


class TestBlastEnsureIndex:
    def test_no_op_when_index_marker_exists(self, tmp_path):
        db_prefix = tmp_path / "refdb"
        db_prefix.with_suffix(".nhr").write_text("")  # marker file present

        with patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"):
            b = BlastBackend(tool="blastn")
            b.make_db = lambda *a, **k: pytest.fail("make_db should not be called")
            b.ensure_index(str(db_prefix), db_type="nucl")  # must not raise

    def test_finds_fna_source_and_builds_index(self, tmp_path):
        db_prefix = tmp_path / "refdb"
        fasta = Path(f"{db_prefix}.fna")
        fasta.write_text(">seq\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", side_effect=_which_resolver),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            b.ensure_index(str(db_prefix), db_type="nucl")
        cmd = captured["cmd"]
        assert cmd[0] == "/fake/makeblastdb"
        assert str(fasta) in cmd

    def test_finds_fasta_source(self, tmp_path):
        db_prefix = tmp_path / "refdb"
        fasta = Path(f"{db_prefix}.fasta")
        fasta.write_text(">s\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", side_effect=_which_resolver),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            b.ensure_index(str(db_prefix), db_type="nucl")
        assert str(fasta) in captured["cmd"]

    def test_finds_abricate_source(self, tmp_path):
        db_prefix = tmp_path / "refdb"
        fasta = Path(f"{db_prefix}_abricate.fasta")
        fasta.write_text(">s\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", side_effect=_which_resolver),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            b.ensure_index(str(db_prefix), db_type="nucl")
        assert str(fasta) in captured["cmd"]

    def test_raises_when_no_source_found(self, tmp_path):
        db_prefix = tmp_path / "refdb"  # no .nhr, no source FASTAs
        with patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"):
            b = BlastBackend(tool="blastn")
            with pytest.raises(FileNotFoundError, match="No BLAST index"):
                b.ensure_index(str(db_prefix), db_type="nucl")

    def test_prot_db_uses_phr_marker(self, tmp_path):
        db_prefix = tmp_path / "refdb"
        # no .phr, no source → FileNotFoundError; only verifies prot branch path
        with patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastp"):
            b = BlastBackend(tool="blastp")
            with pytest.raises(FileNotFoundError):
                b.ensure_index(str(db_prefix), db_type="prot")


class TestBlastFind:
    @pytest.fixture
    def blast_backend(self):
        with patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"):
            return BlastBackend(tool="blastn")

    def test_parses_hits(self, tmp_path, blast_backend):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.blast.subprocess.run",
            return_value=_proc(stdout=BLAST_OUT),
        ):
            hits = blast_backend.find(query=query, db_path="/fake/db")
        assert len(hits) == 2
        assert hits[0].query_id == "q1"
        assert hits[0].subject_id == "s1"
        assert hits[0].identity == 98.5
        assert hits[0].query_coverage == 100.0
        assert hits[0].subject_coverage == pytest.approx(98.33, abs=0.01)
        assert hits[0].strand == "+"
        assert hits[0].backend == "blast"
        assert hits[1].strand == "-"  # sstart=400 > send=201

    def test_filter_by_min_identity(self, tmp_path, blast_backend):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.blast.subprocess.run",
            return_value=_proc(stdout=BLAST_OUT),
        ):
            hits = blast_backend.find(query=query, db_path="/fake/db", min_identity=99.0)
        assert len(hits) == 1
        assert hits[0].identity == 99.0

    def test_filter_by_min_coverage_excludes_all(self, tmp_path, blast_backend):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.blast.subprocess.run",
            return_value=_proc(stdout=BLAST_OUT),
        ):
            hits = blast_backend.find(query=query, db_path="/fake/db", min_coverage=150.0)
        assert hits == []

    def test_raises_on_nonzero_exit(self, tmp_path, blast_backend):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.blast.subprocess.run",
            return_value=_proc(stderr="blast err", returncode=2),
        ):
            with pytest.raises(RuntimeError, match="blastn failed"):
                blast_backend.find(query=query, db_path="/fake/db")

    def test_skips_malformed_lines(self, tmp_path, blast_backend):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        out = (
            "q1\ts1\t98.50\t295\t3\t0\t1\t295\t10\t304\t1e-100\t500\t295\t300\n"
            "garbage line with few fields\n"
            "q2\ts2\t99.0\t200\t1\t0\t1\t200\t400\t201\t1e-50\t300\t200\t400\n"
        )
        with patch(
            "bacmap.core.engine.backends.blast.subprocess.run",
            return_value=_proc(stdout=out),
        ):
            hits = blast_backend.find(query=query, db_path="/fake/db")
        assert len(hits) == 2

    def test_empty_output_returns_empty_list(self, tmp_path, blast_backend):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.blast.subprocess.run",
            return_value=_proc(stdout=""),
        ):
            hits = blast_backend.find(query=query, db_path="/fake/db")
        assert hits == []

    def test_basic_command_construction(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn", threads=8)
            b.find(query=query, db_path="/fake/db", evalue=1e-10, max_targets=50)
        cmd = captured["cmd"]
        assert cmd[0] == "/fake/blastn"
        assert "-query" in cmd and str(query) in cmd
        assert "-db" in cmd and "/fake/db" in cmd
        assert "-outfmt" in cmd
        assert "-evalue" in cmd and "1e-10" in cmd
        assert "-max_target_seqs" in cmd and "50" in cmd
        assert "-num_threads" in cmd and "8" in cmd

    def test_num_threads_kwarg_overrides_default(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn", threads=4)
            b.find(query=query, db_path="/fake/db", num_threads=16)
        cmd = captured["cmd"]
        idx = cmd.index("-num_threads")
        assert cmd[idx + 1] == "16"

    def test_threads_kwarg_is_ignored(self, tmp_path):
        """`threads` is intentionally skipped (use `num_threads`)."""
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn", threads=4)
            b.find(query=query, db_path="/fake/db", threads=99)
        cmd = captured["cmd"]
        assert "-threads" not in cmd
        idx = cmd.index("-num_threads")
        assert cmd[idx + 1] == "4"

    def test_mapped_kwargs_via_param_map(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            # 'pident' maps to 'perc_identity'; 'word_size' passes through
            b.find(query=query, db_path="/fake/db", pident=95, word_size=11)
        cmd = captured["cmd"]
        assert "-perc_identity" in cmd and "95" in cmd
        assert "-word_size" in cmd and "11" in cmd

    def test_bool_true_kwarg_becomes_flag(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            b.find(query=query, db_path="/fake/db", dust="no", ungapped=True)
        cmd = captured["cmd"]
        assert "-ungapped" in cmd
        assert "-dust" in cmd and "no" in cmd

    def test_bool_false_kwarg_skipped(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            b.find(query=query, db_path="/fake/db", ungapped=False)
        cmd = captured["cmd"]
        assert "-ungapped" not in cmd

    def test_none_kwarg_skipped(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">q\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.blast.which", return_value="/fake/blastn"),
            patch("bacmap.core.engine.backends.blast.subprocess.run", side_effect=fake_run),
        ):
            b = BlastBackend(tool="blastn")
            b.find(query=query, db_path="/fake/db", custom_flag=None)
        cmd = captured["cmd"]
        assert "-custom_flag" not in cmd


# ===========================================================================
# MinimapBackend
# ===========================================================================


class TestMinimapInit:
    def test_init_succeeds_when_binary_found(self):
        with patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"):
            m = MinimapBackend(preset="asm10", threads=2)
        assert m.preset == "asm10"
        assert m.threads == 2
        assert m._bin == "/fake/minimap2"

    def test_default_preset_asm5(self):
        with patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"):
            m = MinimapBackend()
        assert m.preset == "asm5"
        assert m.threads == 4

    def test_init_raises_when_binary_missing(self):
        with patch("bacmap.core.engine.backends.minimap2.which", return_value=None):
            with pytest.raises(RuntimeError, match="minimap2 not found"):
                MinimapBackend()


class TestMinimapMakeIndex:
    def test_runs_correct_command(self, tmp_path):
        fasta = tmp_path / "ref.fasta"
        fasta.write_text(">s\nACGT\n")
        idx = tmp_path / "ref.mmi"
        with (
            patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"),
            patch(
                "bacmap.core.engine.backends.minimap2.subprocess.run",
                return_value=_proc(),
            ) as run,
        ):
            m = MinimapBackend()
            m.make_index(fasta, idx)
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/minimap2"
        assert "-d" in cmd and str(idx) in cmd
        assert str(fasta) in cmd


class TestMinimapFind:
    @pytest.fixture
    def minimap_backend(self):
        with patch(
            "bacmap.core.engine.backends.minimap2.which",
            return_value="/fake/minimap2",
        ):
            return MinimapBackend()

    def test_parses_paf_output(self, tmp_path, minimap_backend):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.minimap2.subprocess.run",
            return_value=_proc(stdout=PAF_OUT),
        ):
            hits = minimap_backend.find(query=query, target=target)
        assert len(hits) == 2
        assert hits[0].identity == 95.0
        assert hits[0].query_coverage == 40.0
        assert hits[0].subject_coverage == 20.0
        assert hits[0].mismatches == 20
        assert hits[0].strand == "+"
        assert hits[0].backend == "minimap2"
        assert hits[1].identity == 0.0  # aln_len=0 row

    def test_filter_by_identity(self, tmp_path, minimap_backend):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.minimap2.subprocess.run",
            return_value=_proc(stdout=PAF_OUT),
        ):
            hits = minimap_backend.find(query=query, target=target, min_identity=50.0)
        assert len(hits) == 1
        assert hits[0].identity == 95.0

    def test_filter_by_coverage_drops_all(self, tmp_path, minimap_backend):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.minimap2.subprocess.run",
            return_value=_proc(stdout=PAF_OUT),
        ):
            hits = minimap_backend.find(query=query, target=target, min_coverage=50.0)
        # both rows have qcov=40.0 < 50.0 → none pass
        assert hits == []

    def test_raises_on_nonzero_exit(self, tmp_path, minimap_backend):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        with patch(
            "bacmap.core.engine.backends.minimap2.subprocess.run",
            return_value=_proc(stderr="boom", returncode=1),
        ):
            with pytest.raises(RuntimeError, match="minimap2 failed"):
                minimap_backend.find(query=query, target=target)

    def test_basic_command_construction(self, tmp_path):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"),
            patch(
                "bacmap.core.engine.backends.minimap2.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            m = MinimapBackend(preset="asm10", threads=2)
            m.find(query=query, target=target)
        cmd = captured["cmd"]
        assert cmd[0] == "/fake/minimap2"
        assert "-x" in cmd and "asm10" in cmd
        assert "-t" in cmd and "2" in cmd
        assert "-c" in cmd
        assert "--secondary=no" in cmd
        # target listed before query
        assert cmd.index(str(target)) < cmd.index(str(query))

    def test_preset_override_via_kwarg(self, tmp_path):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"),
            patch(
                "bacmap.core.engine.backends.minimap2.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            m = MinimapBackend(preset="asm5")
            m.find(query=query, target=target, preset="asm20")
        cmd = captured["cmd"]
        idx = cmd.index("-x")
        assert cmd[idx + 1] == "asm20"

    def test_kwargs_appended_to_command(self, tmp_path):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"),
            patch(
                "bacmap.core.engine.backends.minimap2.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            m = MinimapBackend()
            m.find(query=query, target=target, extra_opt="value", p=None)
        cmd = captured["cmd"]
        assert "-extra_opt" in cmd and "value" in cmd
        assert "-p" not in cmd  # None value skipped

    def _capture_kwargs_cmd(self, tmp_path, **kwargs):
        query = tmp_path / "q.fasta"
        target = tmp_path / "t.fasta"
        query.write_text(">q\nACGT\n")
        target.write_text(">t\nACGT\n")
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with (
            patch("bacmap.core.engine.backends.minimap2.which", return_value="/fake/minimap2"),
            patch(
                "bacmap.core.engine.backends.minimap2.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            m = MinimapBackend(threads=4)
            m.find(query=query, target=target, **kwargs)
        return captured["cmd"]

    def test_bool_kwarg_emits_bare_flag(self, tmp_path):
        cmd = self._capture_kwargs_cmd(tmp_path, P=True)
        assert cmd.count("-P") == 1
        assert "True" not in cmd  # bare flag, no "-P True"

    def test_bool_false_kwarg_skipped(self, tmp_path):
        cmd = self._capture_kwargs_cmd(tmp_path, P=False)
        assert "-P" not in cmd

    def test_param_map_translates_pythonic_names(self, tmp_path):
        cmd = self._capture_kwargs_cmd(tmp_path, kmer=19, max_gap=100)
        assert cmd[cmd.index("-k") + 1] == "19"
        assert cmd[cmd.index("-G") + 1] == "100"

    def test_threads_kwarg_replaces_existing_flag(self, tmp_path):
        cmd = self._capture_kwargs_cmd(tmp_path, threads=16)
        assert cmd[cmd.index("-t") + 1] == "16"
        assert cmd.count("-t") == 1


# ===========================================================================
# KmaBackend
# ===========================================================================


class TestKmaInit:
    def test_init_succeeds_when_binary_found(self):
        with patch("bacmap.core.engine.backends.kma.which", return_value="/fake/kma"):
            k = KmaBackend(threads=8)
        assert k.threads == 8
        assert k._bin == "/fake/kma"

    def test_default_threads(self):
        with patch("bacmap.core.engine.backends.kma.which", return_value="/fake/kma"):
            k = KmaBackend()
        assert k.threads == 4

    def test_init_raises_when_binary_missing(self):
        with patch("bacmap.core.engine.backends.kma.which", return_value=None):
            with pytest.raises(RuntimeError, match="kma not found"):
                KmaBackend()


class TestKmaMakeIndex:
    def test_make_index_runs_correct_command(self, tmp_path):
        fasta = tmp_path / "templates.fasta"
        fasta.write_text(">t\nACGT\n")
        idx = tmp_path / "out_index"
        with (
            patch("bacmap.core.engine.backends.kma.which", return_value="/fake/kma"),
            patch(
                "bacmap.core.engine.backends.kma.subprocess.run",
                return_value=_proc(),
            ) as run,
        ):
            k = KmaBackend()
            result = k.make_index(fasta, idx)
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/kma"
        assert "index" in cmd
        assert "-i" in cmd and str(fasta) in cmd
        assert "-o" in cmd and str(idx) in cmd
        assert result == idx


class TestKmaFind:
    def _kma_runner(self, res_text: str):
        """Returns a fake subprocess.run that writes <out_prefix>.res."""

        def fake_run(cmd, *a, **k):
            io_idx = cmd.index("-o")
            out_prefix = cmd[io_idx + 1]
            Path(f"{out_prefix}.res").write_text(res_text)
            return _proc()

        return fake_run

    @pytest.fixture
    def kma_backend(self):
        with patch("bacmap.core.engine.backends.kma.which", return_value="/fake/kma"):
            return KmaBackend()

    def test_find_single_read_parses_res(self, tmp_path, kma_backend):
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        idx = tmp_path / "idx"
        out_dir = tmp_path / "out"
        with patch(
            "bacmap.core.engine.backends.kma.subprocess.run",
            side_effect=self._kma_runner(KMA_RES),
        ) as run:
            hits = kma_backend.find(r1, idx, output_dir=out_dir)
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/kma"
        assert "-i" in cmd and str(r1) in cmd
        assert "-ipe" not in cmd
        assert len(hits) == 2
        assert hits[0].subject_id.startswith("db~~~gene1")
        assert hits[0].identity == 99.50
        assert hits[0].query_coverage == 100.0
        assert hits[0].subject_coverage == 100.0
        assert hits[0].bit_score == 50.0  # depth stored in bit_score
        assert hits[0].backend == "kma"

    def test_find_paired_reads_uses_ipe(self, tmp_path, kma_backend):
        r1 = tmp_path / "r1.fq"
        r2 = tmp_path / "r2.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        r2.write_text("@r\nACGT\n+\n!!!!\n")
        idx = tmp_path / "idx"
        out_dir = tmp_path / "out"
        with patch(
            "bacmap.core.engine.backends.kma.subprocess.run",
            side_effect=self._kma_runner(KMA_RES),
        ) as run:
            kma_backend.find(r1, idx, reads_r2=r2, output_dir=out_dir)
        cmd = run.call_args[0][0]
        assert "-ipe" in cmd
        assert str(r1) in cmd and str(r2) in cmd
        assert "-i" not in cmd  # not single-end

    def test_find_filters_by_coverage(self, tmp_path, kma_backend):
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        idx = tmp_path / "idx"
        out_dir = tmp_path / "out"
        with patch(
            "bacmap.core.engine.backends.kma.subprocess.run",
            side_effect=self._kma_runner(KMA_RES),
        ):
            hits = kma_backend.find(r1, idx, output_dir=out_dir, min_coverage=50.0, min_identity=0)
        # row1 (cov=100) passes, row2 (cov=30) filtered
        assert len(hits) == 1
        assert hits[0].query_coverage == 100.0

    def test_find_filters_by_identity(self, tmp_path, kma_backend):
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        idx = tmp_path / "idx"
        out_dir = tmp_path / "out"
        with patch(
            "bacmap.core.engine.backends.kma.subprocess.run",
            side_effect=self._kma_runner(KMA_RES),
        ):
            hits = kma_backend.find(r1, idx, output_dir=out_dir, min_coverage=0, min_identity=80.0)
        # row1 (id=99.5) passes, row2 (id=50) filtered
        assert len(hits) == 1

    def test_find_raises_on_nonzero_exit(self, tmp_path, kma_backend):
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        idx = tmp_path / "idx"
        with patch(
            "bacmap.core.engine.backends.kma.subprocess.run",
            return_value=_proc(stderr="kma err", returncode=1),
        ):
            with pytest.raises(RuntimeError, match="KMA failed"):
                kma_backend.find(r1, idx, output_dir=tmp_path / "out")

    def test_find_default_output_dir_uses_tempdir(self, tmp_path, kma_backend):
        """When output_dir=None, kma creates a temporary directory."""
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        idx = tmp_path / "idx"
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            io_idx = cmd.index("-o")
            captured["out_prefix"] = cmd[io_idx + 1]
            Path(f"{cmd[io_idx + 1]}.res").write_text(KMA_RES)
            return _proc()

        with patch("bacmap.core.engine.backends.kma.subprocess.run", side_effect=fake_run):
            kma_backend.find(r1, idx)  # output_dir=None
        # out_prefix should be under a tempfile directory
        assert "/tmp" in captured["out_prefix"] or "tmp" in captured["out_prefix"].lower()

    def test_parse_res_skips_header_only(self, tmp_path):
        """A .res with only the header (no data rows) → empty hits."""
        backend = KmaBackend.__new__(KmaBackend)
        res_file = tmp_path / "x.res"
        res_file.write_text(
            "#Template\tScore\tExpected\tTemplate_length\tTemplate_Identity\tTemplate_Coverage\n"
        )
        assert backend._parse_res(tmp_path / "x", 0, 0) == []

    def test_parse_res_handles_invalid_numbers(self, tmp_path):
        backend = KmaBackend.__new__(KmaBackend)
        res_file = tmp_path / "x.res"
        res_file.write_text(
            "#Template\tTemplate_Identity\tTemplate_Coverage\tDepth\ngene1\tBAD\tNOTANUM\tALSOBAD\n"
        )
        hits = backend._parse_res(tmp_path / "x", 0, 0)
        assert len(hits) == 1
        # bad numbers default to 0.0
        assert hits[0].identity == 0.0
        assert hits[0].query_coverage == 0.0
        assert hits[0].bit_score == 0.0

    def test_parse_res_template_with_three_fields(self, tmp_path):
        """`_parse_template` returns empty product for 3-field templates."""
        backend = KmaBackend.__new__(KmaBackend)
        res_file = tmp_path / "x.res"
        res_file.write_text(
            "#Template\tTemplate_Identity\tTemplate_Coverage\tDepth\n"
            "db~~~gene1~~~acc1\t99.0\t100.0\t20.0\n"
        )
        hits = backend._parse_res(tmp_path / "x", 0, 0)
        assert len(hits) == 1
        # _parse_template returns ("gene1", "acc1", "")
        assert hits[0].subject_id == "db~~~gene1~~~acc1"


# ===========================================================================
# MashBackend
# ===========================================================================


class TestMashInit:
    def test_init_succeeds_when_binary_found(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/mash"):
            m = MashBackend(kmer_size=31, sketch_size=2000, threads=2)
        assert m.kmer_size == 31
        assert m.sketch_size == 2000
        assert m.threads == 2
        assert m._bin == "/fake/mash"

    def test_default_params(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/mash"):
            m = MashBackend()
        assert m.kmer_size == 21
        assert m.sketch_size == 1000
        assert m.threads == 4

    def test_init_raises_when_binary_missing(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value=None):
            with pytest.raises(RuntimeError, match="mash not found"):
                MashBackend()


class TestMashSketch:
    @pytest.fixture
    def mash_backend(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/mash"):
            return MashBackend(kmer_size=21, sketch_size=1000)

    def test_basic_sketch(self, tmp_path, mash_backend):
        fasta = tmp_path / "ref.fasta"
        fasta.write_text(">r\nACGT\n")
        out = tmp_path / "out"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(),
        ) as run:
            result = mash_backend.sketch(fasta, out, individual=False)
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/mash"
        assert "sketch" in cmd
        assert "-k" in cmd and "21" in cmd
        assert "-s" in cmd and "1000" in cmd
        assert "-o" in cmd and str(out) in cmd
        assert "-i" not in cmd
        assert str(fasta) in cmd
        assert result == Path(f"{out}.msh")

    def test_individual_adds_flag(self, tmp_path, mash_backend):
        fasta = tmp_path / "ref.fasta"
        fasta.write_text(">r\nACGT\n")
        out = tmp_path / "out"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(),
        ) as run:
            mash_backend.sketch(fasta, out, individual=True)
        cmd = run.call_args[0][0]
        assert "-i" in cmd


class TestMashDistance:
    @pytest.fixture
    def mash_backend(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/mash"):
            return MashBackend()

    def test_parses_slash_format(self, tmp_path, mash_backend):
        q = tmp_path / "q.msh"
        r = tmp_path / "r.msh"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=MASH_DIST_OUT),
        ):
            results = mash_backend.distance(q, r, max_distance=0.1)
        assert len(results) == 2
        assert isinstance(results[0], KmerDistance)
        assert results[0].reference_id == "ref_genome"
        assert results[0].query_id == "query_genome"
        assert results[0].distance == 0.05
        assert results[0].pvalue == 0.001
        assert results[0].shared_hashes == 450
        assert results[0].total_hashes == 1000
        assert results[0].backend == "mash"
        assert results[1].distance == 0.02
        assert results[1].shared_hashes == 500

    def test_parses_no_slash_format(self, tmp_path, mash_backend):
        q = tmp_path / "q.msh"
        r = tmp_path / "r.msh"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=MASH_DIST_OUT_NOSLASH),
        ):
            results = mash_backend.distance(q, r)
        assert len(results) == 1
        assert results[0].shared_hashes == 450
        assert results[0].total_hashes == 1000

    def test_filters_short_lines(self, tmp_path, mash_backend):
        q = tmp_path / "q.msh"
        r = tmp_path / "r.msh"
        out = "ref\tq\t0.05\n"  # 3 cols, <5 → skipped
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=out),
        ):
            results = mash_backend.distance(q, r)
        assert results == []

    def test_skips_comments_and_blank_lines(self, tmp_path, mash_backend):
        q = tmp_path / "q.msh"
        r = tmp_path / "r.msh"
        out = "#comment\n\nref\tq\t0.05\t0.001\t100/200\n"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=out),
        ):
            results = mash_backend.distance(q, r)
        assert len(results) == 1
        assert results[0].shared_hashes == 100
        assert results[0].total_hashes == 200

    def test_raises_on_nonzero_exit(self, tmp_path, mash_backend):
        q = tmp_path / "q.msh"
        r = tmp_path / "r.msh"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stderr="err", returncode=1),
        ):
            with pytest.raises(RuntimeError, match="mash dist failed"):
                mash_backend.distance(q, r)

    def test_appends_kwargs(self, tmp_path, mash_backend):
        q = tmp_path / "q.msh"
        r = tmp_path / "r.msh"
        captured: dict = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            return _proc()

        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            side_effect=fake_run,
        ):
            mash_backend.distance(q, r, max_distance=0.2, threads=4)
        cmd = captured["cmd"]
        assert "-d" in cmd and "0.2" in cmd
        assert "-threads" in cmd and "4" in cmd


class TestMashScreen:
    def test_screen_delegates_to_distance(self, tmp_path):
        q = tmp_path / "q.msh"
        rdb = tmp_path / "rdb.msh"
        with (
            patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/mash"),
            patch(
                "bacmap.core.engine.backends.kmer.subprocess.run",
                return_value=_proc(stdout=MASH_DIST_OUT),
            ),
        ):
            m = MashBackend()
            results = m.screen(q, rdb, max_distance=0.05)
        assert len(results) == 2


# ===========================================================================
# SourmashBackend
# ===========================================================================


class TestSourmashInit:
    def test_init_succeeds_when_binary_found(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/sourmash"):
            s = SourmashBackend(kmer_size=31, scaled=2000)
        assert s.kmer_size == 31
        assert s.scaled == 2000
        assert s._bin == "/fake/sourmash"

    def test_default_params(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/sourmash"):
            s = SourmashBackend()
        assert s.kmer_size == 31
        assert s.scaled == 1000

    def test_init_raises_when_binary_missing(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value=None):
            with pytest.raises(RuntimeError, match="sourmash not found"):
                SourmashBackend()


class TestSourmashSketch:
    @pytest.fixture
    def sourmash_backend(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/sourmash"):
            return SourmashBackend(kmer_size=31, scaled=1000)

    def test_basic_sketch_no_name(self, tmp_path, sourmash_backend):
        fasta = tmp_path / "ref.fasta"
        fasta.write_text(">s\nACGT\n")
        out = tmp_path / "sig.zip"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(),
        ) as run:
            result = sourmash_backend.sketch(fasta, out)
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/sourmash"
        assert "sketch" in cmd and "dna" in cmd
        assert "-p" in cmd and "k=31,scaled=1000" in cmd
        assert "-o" in cmd and str(out) in cmd
        assert "--name" not in cmd
        assert str(fasta) in cmd
        assert result == out

    def test_sketch_with_name_adds_flag(self, tmp_path, sourmash_backend):
        fasta = tmp_path / "ref.fasta"
        fasta.write_text(">s\nACGT\n")
        out = tmp_path / "sig.zip"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(),
        ) as run:
            sourmash_backend.sketch(fasta, out, name="mygenome")
        cmd = run.call_args[0][0]
        assert "--name" in cmd and "mygenome" in cmd


class TestSourmashDistance:
    @pytest.fixture
    def sourmash_backend(self):
        with patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/sourmash"):
            return SourmashBackend(scaled=1000)

    def test_parses_known_csv_header(self, tmp_path, sourmash_backend):
        q = tmp_path / "q.sig"
        r = tmp_path / "r.sig"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=SOURMASH_CSV),
        ):
            results = sourmash_backend.distance(q, r, threshold=0.1)
        assert len(results) == 1
        assert isinstance(results[0], KmerDistance)
        assert results[0].query_id == ""  # 6-col row, not >6
        assert results[0].reference_id == "gene_X"
        assert results[0].distance == pytest.approx(0.15, abs=1e-6)
        assert results[0].shared_hashes == 850
        assert results[0].total_hashes == 1000
        assert results[0].backend == "sourmash"

    def test_raises_on_nonzero_exit(self, tmp_path, sourmash_backend):
        q = tmp_path / "q.sig"
        r = tmp_path / "r.sig"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stderr="err", returncode=2),
        ):
            with pytest.raises(RuntimeError, match="sourmash search failed"):
                sourmash_backend.distance(q, r)

    def test_empty_output(self, tmp_path, sourmash_backend):
        q = tmp_path / "q.sig"
        r = tmp_path / "r.sig"
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=""),
        ):
            results = sourmash_backend.distance(q, r)
        assert results == []

    def test_short_rows_skipped(self, tmp_path, sourmash_backend):
        q = tmp_path / "q.sig"
        r = tmp_path / "r.sig"
        out = "query_name,a,b,c,d\n,1,2\n"  # row 2 has only 3 cols → skipped
        with patch(
            "bacmap.core.engine.backends.kmer.subprocess.run",
            return_value=_proc(stdout=out),
        ):
            results = sourmash_backend.distance(q, r)
        assert results == []

    def test_unknown_header_first_line_processed_as_data(self, tmp_path):
        """First-line logic: if header isn't a known name, set flag and fall through."""
        q = tmp_path / "q.sig"
        r = tmp_path / "r.sig"
        out = "unknown,1,2,geneY,0.75,end\n"  # 6 cols, no header match
        with (
            patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/sourmash"),
            patch(
                "bacmap.core.engine.backends.kmer.subprocess.run",
                return_value=_proc(stdout=out),
            ),
        ):
            s = SourmashBackend(scaled=1000)
            results = s.distance(q, r)
        assert len(results) == 1
        assert results[0].reference_id == "geneY"
        assert results[0].distance == pytest.approx(0.25, abs=1e-6)  # 1 - 0.75

    def test_intercept_bp_recognised_as_header(self, tmp_path):
        """`intersect_bp` is one of the recognised header keywords."""
        q = tmp_path / "q.sig"
        r = tmp_path / "r.sig"
        out = "intersect_bp,a,b,c,d\n,1,2,geneZ,0.50,end\n"
        with (
            patch("bacmap.core.engine.backends.kmer.which", return_value="/fake/sourmash"),
            patch(
                "bacmap.core.engine.backends.kmer.subprocess.run",
                return_value=_proc(stdout=out),
            ),
        ):
            s = SourmashBackend(scaled=1000)
            results = s.distance(q, r)
        assert len(results) == 1
        assert results[0].reference_id == "geneZ"
