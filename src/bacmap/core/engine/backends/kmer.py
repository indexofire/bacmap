from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._env import which


@dataclass
class KmerDistance:
    """MinHash-based genome distance result."""

    query_id: str
    reference_id: str
    distance: float
    pvalue: float
    shared_hashes: int
    total_hashes: int
    backend: str = "mash"


class MashBackend:
    """Mash backend for rapid genome distance estimation via MinHash.

    Requires: mash installed (conda install -c bioconda mash)
    Usage:
        backend = MashBackend()
        backend.sketch(Path('genome.fasta'), Path('genome.msh'))
        results = backend.distance(Path('query.msh'), Path('ref.msh'))
    """

    def __init__(self, kmer_size: int = 21, sketch_size: int = 1000, threads: int = 4) -> None:
        self.kmer_size = kmer_size
        self.sketch_size = sketch_size
        self.threads = threads
        self._bin = self._find_binary()

    def _find_binary(self) -> str:
        binary = which("mash")
        if not binary:
            raise RuntimeError("mash not found. Install: conda install -c bioconda mash")
        return binary

    def sketch(self, fasta: Path, output: Path, individual: bool = False) -> Path:
        """Create a MinHash sketch from FASTA file(s)."""
        cmd = [
            self._bin,
            "sketch",
            "-k",
            str(self.kmer_size),
            "-s",
            str(self.sketch_size),
            "-o",
            str(output),
        ]
        if individual:
            cmd.append("-i")
        cmd.append(str(fasta))

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return Path(f"{output}.msh")

    def distance(
        self,
        query: Path,
        reference: Path,
        max_distance: float = 0.1,
        **kwargs: Any,
    ) -> list[KmerDistance]:
        """Calculate Mash distances between two sketches.

        Returns one KmerDistance per reference sequence pair.
        """
        cmd = [
            self._bin,
            "dist",
            "-d",
            str(max_distance),
            str(query),
            str(reference),
        ]

        for key, value in kwargs.items():
            if value is not None:
                cmd.extend([f"-{key}", str(value)])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"mash dist failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}"
            )

        results: list[KmerDistance] = []
        for line in proc.stdout.splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                ref_id = parts[0]
                query_id = parts[1]
                dist = float(parts[2])
                pval = float(parts[3])
                hash_field = parts[4]
                if "/" in hash_field:
                    shared, total = hash_field.split("/", 1)
                    shared_hashes = int(shared)
                    total_hashes = int(total)
                else:
                    shared_hashes = int(hash_field)
                    total_hashes = int(parts[5]) if len(parts) > 5 else 0
                results.append(
                    KmerDistance(
                        query_id=query_id,
                        reference_id=ref_id,
                        distance=dist,
                        pvalue=pval,
                        shared_hashes=shared_hashes,
                        total_hashes=total_hashes,
                    )
                )
            except (ValueError, IndexError):
                continue

        return results

    def screen(
        self,
        query: Path,
        reference_db: Path,
        max_distance: float = 0.1,
        **kwargs: Any,
    ) -> list[KmerDistance]:
        """Screen a query against a pre-built reference sketch database."""
        return self.distance(query, reference_db, max_distance, **kwargs)


class SourmashBackend:
    """Sourmash backend for genome distance estimation.

    Requires: sourmash installed (pip install sourmash)
    Advantage: Python-native, no external binary needed for some operations.
    """

    def __init__(self, kmer_size: int = 31, scaled: int = 1000) -> None:
        self.kmer_size = kmer_size
        self.scaled = scaled
        self._bin = self._find_binary()

    def _find_binary(self) -> str:
        binary = which("sourmash")
        if not binary:
            raise RuntimeError("sourmash not found. Install: pip install sourmash")
        return binary

    def sketch(self, fasta: Path, output: Path, name: str = "") -> Path:
        """Create a sourmash signature from FASTA."""
        cmd = [
            self._bin,
            "sketch",
            "dna",
            "-p",
            f"k={self.kmer_size},scaled={self.scaled}",
            "-o",
            str(output),
        ]
        if name:
            cmd.extend(["--name", name])
        cmd.append(str(fasta))

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return output

    def distance(
        self,
        query_sig: Path,
        reference_sig: Path,
        threshold: float = 0.1,
    ) -> list[KmerDistance]:
        """Calculate containment/ANI distances between signatures."""
        cmd = [
            self._bin,
            "search",
            str(query_sig),
            str(reference_sig),
            "--threshold",
            str(threshold),
            "-o",
            "/dev/stdout",
            "--csv",
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"sourmash search failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}"
            )

        results: list[KmerDistance] = []
        lines = proc.stdout.strip().splitlines()

        header_skipped = False
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(",")
            if not header_skipped:
                if parts[0].strip() in ("query_name", "intersect_bp", "name"):
                    header_skipped = True
                    continue
                header_skipped = True
            if len(parts) < 5:
                continue
            try:
                q_name = parts[0].strip() if len(parts) > 6 else ""
                ref_name = parts[3].strip() if len(parts) > 4 else parts[1].strip()
                containment = float(parts[-2]) if len(parts) >= 2 else 0.0
                results.append(
                    KmerDistance(
                        query_id=q_name,
                        reference_id=ref_name,
                        distance=round(1.0 - containment, 6),
                        pvalue=0.0,
                        shared_hashes=int(containment * self.scaled),
                        total_hashes=self.scaled,
                        backend="sourmash",
                    )
                )
            except (ValueError, IndexError):
                continue

        return results
