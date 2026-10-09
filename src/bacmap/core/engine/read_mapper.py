from __future__ import annotations

import gzip
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ._env import which

_LONG_READ_MIN_LEN = 1000


def _ensure_bwa_index(ref: str) -> None:
    if not Path(ref + ".bwt").exists():
        bwa = which("bwa")
        if not bwa:
            raise RuntimeError("bwa not found")
        subprocess.run([bwa, "index", ref], check=True, capture_output=True, timeout=120)


def _sniff_read_type(reads: list[str]) -> str:
    """Inspect the first FASTQ records; any read >= _LONG_READ_MIN_LEN bp ⇒ 'long'.

    Falls back to 'short' when the file cannot be opened (missing, not FASTQ).
    """
    if not reads:
        return "short"
    path = reads[0]
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt") as fh:
            for i, line in enumerate(fh):
                if i > 400:  # first ~100 FASTQ records
                    break
                if i % 4 == 1 and len(line.strip()) >= _LONG_READ_MIN_LEN:
                    return "long"
    except OSError:
        pass
    return "short"


def _run_align_and_sort(
    aligner_cmd: list[str],
    out_bam: str,
    threads: int,
    aligner_name: str,
) -> None:
    """Run the aligner, stream its SAM stdout into samtools sort, then index.

    Uses a pipe instead of buffering the whole SAM in memory (multi-GB for
    deep-coverage samples). Aligner stderr goes to a temp file to avoid
    pipe-buffer deadlock, and is surfaced on failure.
    """
    samtools = which("samtools")
    if not samtools:
        raise RuntimeError("samtools not found")

    with tempfile.TemporaryFile(mode="w+t") as err:
        with subprocess.Popen(aligner_cmd, stdout=subprocess.PIPE, stderr=err) as ap:
            proc = subprocess.run(
                [samtools, "sort", "-@", str(threads), "-o", out_bam, "-"],
                stdin=ap.stdout,
                capture_output=True,
                text=True,
                timeout=600,
            )
            rc = ap.wait(timeout=600)
        if rc != 0:
            err.seek(0)
            raise RuntimeError(f"{aligner_name} failed (exit {rc}): {err.read()[:500]}")

    if proc.returncode != 0:
        raise RuntimeError(f"samtools sort failed: {proc.stderr[:500]}")

    subprocess.run([samtools, "index", out_bam], check=True, capture_output=True, timeout=120)


class BwaReadMapper:
    def map(
        self,
        reads: list[str],
        reference: str,
        out_bam: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        threads = kwargs.get("threads", os.cpu_count() or 4)
        extra = kwargs.get("extra_args", "")

        _ensure_bwa_index(reference)

        bwa = which("bwa")
        if not bwa:
            raise RuntimeError("bwa not found")

        cmd = [bwa, "mem", "-t", str(threads)]
        if extra:
            cmd += extra.split()
        cmd += [reference] + reads

        _run_align_and_sort(cmd, out_bam, threads, "bwa mem")

        return {
            "aligner": "bwa-mem",
            "reference": reference,
            "reads": reads,
            "output_bam": out_bam,
            "paired_end": len(reads) == 2,
            "indexed": Path(out_bam + ".bai").exists(),
        }


class Minimap2ReadMapper:
    def map(
        self,
        reads: list[str],
        reference: str,
        out_bam: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        threads = kwargs.get("threads", os.cpu_count() or 4)
        preset = kwargs.get("preset", "map-ont")
        extra = kwargs.get("extra_args", "")

        mm2 = which("minimap2")
        if not mm2:
            raise RuntimeError("minimap2 not found")

        cmd = [mm2, "-ax", preset, "--secondary=no", "-Y", "-t", str(threads)]
        if extra:
            cmd += extra.split()
        cmd += [reference] + reads

        _run_align_and_sort(cmd, out_bam, threads, "minimap2")

        return {
            "aligner": "minimap2",
            "preset": preset,
            "reference": reference,
            "reads": reads,
            "output_bam": out_bam,
            "indexed": Path(out_bam + ".bai").exists(),
        }


def _get_mapper(name: str) -> BwaReadMapper | Minimap2ReadMapper:
    key = name.strip().lower()
    if key in ("bwa", "bwa-mem"):
        return BwaReadMapper()
    if key == "minimap2":
        return Minimap2ReadMapper()
    raise KeyError(f"Unknown read mapper: {name}")


class ReadMapper:
    """Map sequencing reads to a reference genome, producing sorted BAM."""

    @classmethod
    def map(
        cls,
        reads: list[str],
        reference: str,
        out_bam: str,
        mode: str = "auto",
        read_type: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if read_type is not None and read_type not in ("short", "long"):
            raise ValueError(f"read_type must be 'short' or 'long', got {read_type!r}")
        if mode == "auto":
            mode = cls._select(reads, read_type)
        mapper = _get_mapper(mode)
        return mapper.map(reads, reference, out_bam, **kwargs)

    @staticmethod
    def _select(reads: list[str], read_type: str | None = None) -> str:
        for r in reads:
            if r.endswith((".fasta", ".fa", ".fna")):
                return "minimap2"
        if read_type is None:
            read_type = _sniff_read_type(reads)
        return "minimap2" if read_type == "long" else "bwa"
