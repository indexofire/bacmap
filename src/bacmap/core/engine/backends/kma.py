from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from bacmap.core.utils import parse_db_header

from .._env import which
from ..hits import Hit


class KmaBackend:
    """KMA backend for gene detection from raw sequencing reads (FASTQ).

    KMA (K-mer Alignment) maps reads directly to template sequences,
    enabling gene detection without assembly.
    """

    def __init__(self, threads: int = 4) -> None:
        self.threads = threads
        self._bin = self._find_binary()

    def _find_binary(self) -> str:
        binary = which("kma")
        if not binary:
            raise RuntimeError("kma not found in PATH. Install: pixi install")
        return binary

    def make_index(self, templates_fasta: Path, index_prefix: Path) -> Path:
        cmd = [
            self._bin,
            "index",
            "-i",
            str(templates_fasta),
            "-o",
            str(index_prefix),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        return index_prefix

    def find(
        self,
        reads_r1: Path,
        index_prefix: Path,
        reads_r2: Path | None = None,
        min_coverage: float = 0.0,
        min_identity: float = 0.0,
        output_dir: Path | None = None,
        **kwargs: Any,
    ) -> list[Hit]:
        if output_dir is None:
            import tempfile

            output_dir = Path(tempfile.mkdtemp())
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        out_prefix = output_dir / "kma_result"

        cmd = [
            self._bin,
            "-t",
            str(self.threads),
            "-t_db",
            str(index_prefix),
            "-res",
            "-1t1",
            "-cge",
            "-apm",
            "p",
            "-o",
            str(out_prefix),
        ]
        if reads_r2:
            cmd.extend(["-ipe", str(reads_r1), str(reads_r2)])
        else:
            cmd.extend(["-i", str(reads_r1)])

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"KMA failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}")

        return self._parse_res(out_prefix, min_coverage, min_identity)

    def _parse_res(self, out_prefix: Path, min_coverage: float, min_identity: float) -> list[Hit]:
        res_file = Path(f"{out_prefix}.res")
        if not res_file.exists():
            return []

        lines = res_file.read_text().strip().split("\n")
        if len(lines) < 2:
            return []

        header = [h.strip().lstrip("#") for h in lines[0].split("\t")]
        hits: list[Hit] = []

        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            row = dict(zip(header, parts))

            template = row.get("Template", "")
            if not template:
                continue

            try:
                identity = float(row.get("Template_Identity", 0))
            except (ValueError, TypeError):
                identity = 0.0
            try:
                coverage = float(row.get("Template_Coverage", 0))
            except (ValueError, TypeError):
                coverage = 0.0

            if coverage < min_coverage or identity < min_identity:
                continue

            try:
                depth = float(row.get("Depth", 0))
            except (ValueError, TypeError):
                depth = 0.0

            hits.append(
                Hit(
                    query_id="reads",
                    subject_id=template,
                    identity=identity,
                    query_coverage=coverage,
                    subject_coverage=coverage,
                    evalue=0.0,
                    bit_score=depth,
                    backend="kma",
                )
            )

        return hits

    @staticmethod
    def _parse_template(template: str) -> tuple[str, str, str]:
        gene, accession, product, _ = parse_db_header(template)
        return gene, accession, product
