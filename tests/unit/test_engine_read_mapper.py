"""Unit tests for engine.read_mapper — BWA/Minimap2 mappers and ReadMapper facade.

bwa/minimap2 are mocked at the subprocess.Popen boundary (streaming pipe);
samtools sort/index stay at the subprocess.run boundary; `which` is mocked at
bacmap.core.engine.read_mapper.which (imported from `._env`).
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import ClassVar
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.engine.read_mapper import (  # noqa: E402
    BwaReadMapper,
    Minimap2ReadMapper,
    ReadMapper,
    _ensure_bwa_index,
    _get_mapper,
    _run_align_and_sort,
    _sniff_read_type,
)


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakePopen:
    """Minimal Popen stand-in: captures cmd, drains stderr file, returns rc."""

    rc = 0
    err_text = ""
    instances: ClassVar[list[_FakePopen]] = []

    def __init__(self, cmd, stdout=None, stderr=None, **kwargs):
        self.cmd = cmd
        self.stdout = io.StringIO("SAM\n") if stdout == subprocess.PIPE else None
        if stderr is not None and self.err_text:
            stderr.write(self.err_text)
        _FakePopen.instances.append(self)

    def wait(self, timeout=None):
        return self.rc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_aligner(run=None, popen_rc: int = 0, popen_err: str = ""):
    """Patch which/subprocess.run/subprocess.Popen in read_mapper."""
    _FakePopen.instances = []
    _FakePopen.rc = popen_rc
    _FakePopen.err_text = popen_err
    return (
        patch("bacmap.core.engine.read_mapper.which", return_value="/fake/tool"),
        patch(
            "bacmap.core.engine.read_mapper.subprocess.run",
            return_value=run if run is not None else _proc(),
        ),
        patch("bacmap.core.engine.read_mapper.subprocess.Popen", _FakePopen),
    )


# ===========================================================================
# _ensure_bwa_index
# ===========================================================================


class TestEnsureBwaIndex:
    def test_no_op_when_bwt_exists(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        Path(f"{ref}.bwt").write_text("")
        with patch("bacmap.core.engine.read_mapper.subprocess.run") as run:
            _ensure_bwa_index(str(ref))
        run.assert_not_called()

    def test_invokes_bwa_index_when_bwt_missing(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        with (
            patch("bacmap.core.engine.read_mapper.which", return_value="/fake/bwa"),
            patch(
                "bacmap.core.engine.read_mapper.subprocess.run",
                return_value=_proc(),
            ) as run,
        ):
            _ensure_bwa_index(str(ref))
        cmd = run.call_args[0][0]
        assert cmd[0] == "/fake/bwa"
        assert "index" in cmd
        assert str(ref) in cmd

    def test_raises_when_bwa_missing(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        with patch("bacmap.core.engine.read_mapper.which", return_value=None), pytest.raises(RuntimeError, match="bwa not found"):
            _ensure_bwa_index(str(ref))


# ===========================================================================
# _sniff_read_type
# ===========================================================================


def _write_fastq(path: Path, read_len: int, n: int = 2) -> None:
    rec = "@r\n" + "A" * read_len + "\n+\n" + "!" * read_len + "\n"
    path.write_text(rec * n)


class TestSniffReadType:
    def test_short_reads(self, tmp_path):
        fq = tmp_path / "r1.fastq"
        _write_fastq(fq, 150)
        assert _sniff_read_type([str(fq)]) == "short"

    def test_long_reads(self, tmp_path):
        fq = tmp_path / "ont.fastq"
        _write_fastq(fq, 5000)
        assert _sniff_read_type([str(fq)]) == "long"

    def test_long_reads_gz(self, tmp_path):
        import gzip

        fq = tmp_path / "ont.fastq.gz"
        rec = "@r\n" + "A" * 5000 + "\n+\n" + "!" * 5000 + "\n"
        with gzip.open(fq, "wt") as fh:
            fh.write(rec)
        assert _sniff_read_type([str(fq)]) == "long"

    def test_missing_file_falls_back_to_short(self, tmp_path):
        assert _sniff_read_type([str(tmp_path / "nope.fastq")]) == "short"

    def test_empty_reads_returns_short(self):
        assert _sniff_read_type([]) == "short"


# ===========================================================================
# _run_align_and_sort
# ===========================================================================


class TestRunAlignAndSort:
    def test_pipes_aligner_into_sort_then_index(self, tmp_path):
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run as run_mock, popen:
            _run_align_and_sort(
                ["/fake/bwa", "mem", "ref", "r1"], str(out_bam), threads=4, aligner_name="bwa mem"
            )
        assert _FakePopen.instances[0].cmd == ["/fake/bwa", "mem", "ref", "r1"]
        assert run_mock.call_count == 2
        sort_cmd = run_mock.call_args_list[0][0][0]
        index_cmd = run_mock.call_args_list[1][0][0]
        assert "sort" in sort_cmd
        assert "-@" in sort_cmd and "4" in sort_cmd
        assert "-o" in sort_cmd and str(out_bam) in sort_cmd
        # sort reads from the aligner's stdout pipe, not a buffered string
        assert run_mock.call_args_list[0][1]["stdin"] is _FakePopen.instances[0].stdout
        assert "index" in index_cmd

    def test_raises_when_samtools_missing(self, tmp_path):
        with patch("bacmap.core.engine.read_mapper.which", return_value=None), pytest.raises(RuntimeError, match="samtools not found"):
            _run_align_and_sort(
                ["x"], str(tmp_path / "out.bam"), threads=2, aligner_name="bwa mem"
            )

    def test_raises_on_sort_failure(self, tmp_path):
        w, run, popen = _patch_aligner(run=_proc(stderr="bad sort", returncode=1))
        with w, run, popen, pytest.raises(RuntimeError, match="samtools sort failed"):
            _run_align_and_sort(
                ["x"], str(tmp_path / "out.bam"), threads=2, aligner_name="bwa mem"
            )

    def test_raises_on_aligner_failure_with_stderr(self, tmp_path):
        w, run, popen = _patch_aligner(popen_rc=1, popen_err="mem fail")
        with w, run, popen, pytest.raises(RuntimeError, match=r"bwa mem failed \(exit 1\): mem fail"):
            _run_align_and_sort(
                ["x"], str(tmp_path / "out.bam"), threads=2, aligner_name="bwa mem"
            )


# ===========================================================================
# BwaReadMapper
# ===========================================================================


def _make_bwa_index_marker(ref: Path) -> None:
    Path(f"{ref}.bwt").write_text("")


class TestBwaReadMapper:
    def test_paired_end_invokes_bwa_mem_with_two_reads(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        _make_bwa_index_marker(ref)
        r1 = tmp_path / "r1.fq"
        r2 = tmp_path / "r2.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        r2.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run, popen:
            result = BwaReadMapper().map([str(r1), str(r2)], str(ref), str(out_bam))
        mem_cmd = _FakePopen.instances[0].cmd
        assert mem_cmd[0] == "/fake/tool"
        assert "mem" in mem_cmd
        assert str(r1) in mem_cmd and str(r2) in mem_cmd
        assert str(ref) in mem_cmd
        assert result["aligner"] == "bwa-mem"
        assert result["paired_end"] is True
        assert result["reference"] == str(ref)
        assert result["reads"] == [str(r1), str(r2)]
        assert result["output_bam"] == str(out_bam)

    def test_single_end_marks_paired_end_false(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        _make_bwa_index_marker(ref)
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run, popen:
            result = BwaReadMapper().map([str(r1)], str(ref), str(out_bam))
        assert result["paired_end"] is False

    def test_threads_kwarg_sets_t_flag(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        _make_bwa_index_marker(ref)
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run, popen:
            BwaReadMapper().map([str(r1)], str(ref), str(out_bam), threads=8)
        mem_cmd = _FakePopen.instances[0].cmd
        idx_t = mem_cmd.index("-t")
        assert mem_cmd[idx_t + 1] == "8"

    def test_extra_args_split_appended_to_cmd(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        _make_bwa_index_marker(ref)
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run, popen:
            BwaReadMapper().map(
                [str(r1)],
                str(ref),
                str(out_bam),
                extra_args="-Y -K 100000",
            )
        mem_cmd = _FakePopen.instances[0].cmd
        assert "-Y" in mem_cmd
        assert "-K" in mem_cmd
        assert "100000" in mem_cmd

    def test_raises_on_bwa_mem_failure(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        _make_bwa_index_marker(ref)
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner(popen_rc=1, popen_err="mem fail")
        with w, run, popen, pytest.raises(RuntimeError, match="bwa mem failed"):
            BwaReadMapper().map([str(r1)], str(ref), str(out_bam))


# ===========================================================================
# Minimap2ReadMapper
# ===========================================================================


class TestMinimap2ReadMapper:
    def test_default_preset_map_ont(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run, popen:
            result = Minimap2ReadMapper().map([str(r1)], str(ref), str(out_bam))
        cmd = _FakePopen.instances[0].cmd
        assert cmd[0] == "/fake/tool"
        assert "-ax" in cmd
        idx_ax = cmd.index("-ax")
        assert cmd[idx_ax + 1] == "map-ont"
        assert "--secondary=no" in cmd
        assert "-Y" in cmd
        assert result["aligner"] == "minimap2"
        assert result["preset"] == "map-ont"
        assert result["reference"] == str(ref)

    def test_custom_preset_via_kwarg(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner()
        with w, run, popen:
            Minimap2ReadMapper().map([str(r1)], str(ref), str(out_bam), preset="sr")
        cmd = _FakePopen.instances[0].cmd
        idx_ax = cmd.index("-ax")
        assert cmd[idx_ax + 1] == "sr"

    def test_raises_on_minimap2_failure(self, tmp_path):
        ref = tmp_path / "ref.fasta"
        ref.write_text(">r\nACGT\n")
        r1 = tmp_path / "r1.fq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        out_bam = tmp_path / "out.bam"
        w, run, popen = _patch_aligner(popen_rc=1, popen_err="mm2 fail")
        with w, run, popen, pytest.raises(RuntimeError, match="minimap2 failed"):
            Minimap2ReadMapper().map([str(r1)], str(ref), str(out_bam))


# ===========================================================================
# _get_mapper
# ===========================================================================


class TestGetMapper:
    @pytest.mark.parametrize("name", ["bwa", "BWA", "bwa-mem", "BWA-MEM", "  Bwa  "])
    def test_bwa_aliases(self, name):
        m = _get_mapper(name)
        assert isinstance(m, BwaReadMapper)

    @pytest.mark.parametrize("name", ["minimap2", "Minimap2", "  MINIMAP2  "])
    def test_minimap2_aliases(self, name):
        m = _get_mapper(name)
        assert isinstance(m, Minimap2ReadMapper)

    def test_unknown_name_raises_keyerror(self):
        with pytest.raises(KeyError, match="Unknown read mapper"):
            _get_mapper("bowtie2")


# ===========================================================================
# ReadMapper facade
# ===========================================================================


class TestReadMapperSelect:
    @pytest.mark.parametrize("ext", [".fasta", ".fa", ".fna"])
    def test_fasta_extensions_route_to_minimap2(self, ext):
        assert ReadMapper._select([f"asm{ext}"]) == "minimap2"

    @pytest.mark.parametrize("name", ["r1.fastq", "r1.fq", "reads.fastq.gz"])
    def test_fastq_extensions_route_to_bwa(self, name):
        # files do not exist → sniff falls back to short
        assert ReadMapper._select([name]) == "bwa"

    def test_any_fasta_in_list_routes_to_minimap2(self):
        assert ReadMapper._select(["r1.fastq", "asm.fa"]) == "minimap2"

    def test_empty_reads_returns_bwa(self):
        assert ReadMapper._select([]) == "bwa"

    def test_unknown_extension_returns_bwa(self):
        assert ReadMapper._select(["reads.unknown"]) == "bwa"

    def test_explicit_long_read_type_routes_to_minimap2(self):
        assert ReadMapper._select(["ont.fastq"], read_type="long") == "minimap2"

    def test_explicit_short_read_type_routes_to_bwa(self):
        assert ReadMapper._select(["r1.fastq"], read_type="short") == "bwa"

    def test_fasta_wins_over_read_type(self):
        assert ReadMapper._select(["asm.fa"], read_type="short") == "minimap2"

    def test_sniffed_long_reads_route_to_minimap2(self, tmp_path):
        fq = tmp_path / "ont.fastq"
        _write_fastq(fq, 8000)
        assert ReadMapper._select([str(fq)]) == "minimap2"

    def test_sniffed_short_reads_route_to_bwa(self, tmp_path):
        fq = tmp_path / "r1.fastq"
        _write_fastq(fq, 150)
        assert ReadMapper._select([str(fq)]) == "bwa"


class TestReadMapperFacadeRouting:
    def test_auto_routes_to_bwa_for_fastq_input(self):
        with patch("bacmap.core.engine.read_mapper._get_mapper") as gm:
            ReadMapper.map(["r1.fastq", "r2.fastq"], "ref.fasta", "out.bam")
        gm.assert_called_once_with("bwa")

    def test_auto_routes_to_minimap2_for_fasta_input(self):
        with patch("bacmap.core.engine.read_mapper._get_mapper") as gm:
            ReadMapper.map(["contigs.fasta"], "ref.fasta", "out.bam")
        gm.assert_called_once_with("minimap2")

    def test_auto_routes_to_minimap2_for_long_read_type(self):
        with patch("bacmap.core.engine.read_mapper._get_mapper") as gm:
            ReadMapper.map(["ont.fastq"], "ref.fasta", "out.bam", read_type="long")
        gm.assert_called_once_with("minimap2")

    def test_invalid_read_type_raises(self):
        with pytest.raises(ValueError, match="read_type"):
            ReadMapper.map(["r1.fq"], "ref.fasta", "out.bam", read_type="medium")

    def test_explicit_mode_overrides_auto(self):
        with patch("bacmap.core.engine.read_mapper._get_mapper") as gm:
            ReadMapper.map(["contigs.fasta"], "ref.fasta", "out.bam", mode="bwa")
        gm.assert_called_once_with("bwa")

    def test_map_passes_kwargs_to_underlying_mapper(self):
        with patch("bacmap.core.engine.read_mapper._get_mapper") as gm:
            mock_mapper = gm.return_value
            mock_mapper.map.return_value = {"aligner": "bwa-mem"}
            result = ReadMapper.map(
                ["r1.fq"],
                "ref.fasta",
                "out.bam",
                threads=16,
                extra_args="-Y",
            )
        mock_mapper.map.assert_called_once_with(
            ["r1.fq"], "ref.fasta", "out.bam", threads=16, extra_args="-Y"
        )
        assert result == {"aligner": "bwa-mem"}


class TestAlignTimeoutKillsChild:
    """samtools sort 超时必须 kill 对齐子进程（否则遗留进程/僵尸）。"""

    def test_sort_timeout_kills_aligner(self, tmp_path, monkeypatch):
        import subprocess

        import bacmap.core.engine.read_mapper as rm

        monkeypatch.setattr(rm, "which", lambda c: "/usr/bin/" + c)

        class _AP:
            def __init__(self):
                self.killed = False
                self.stdout = None

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                return -9

        ap = _AP()
        monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: ap)

        def _run(cmd, **k):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=600)

        monkeypatch.setattr(rm.subprocess, "run", _run)

        import pytest

        with pytest.raises(RuntimeError, match="samtools sort timed out"):
            rm._run_align_and_sort(["bwa", "mem"], str(tmp_path / "o.bam"), 2, "bwa")
        assert ap.killed is True
