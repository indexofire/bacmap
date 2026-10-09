from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .._env import which
from ..hits import Hit

_PARAM_MAP = {
    "kmer": "k",
    "window": "w",
    "min_chain_score": "m",
    "bandwidth": "r",
    "max_gap": "G",
    "max_chain_skip": "n",
}


class MinimapBackend:
    """minimap2 backend for assembly-to-reference alignment (PAF output)."""

    def __init__(self, preset: str = "asm5", threads: int = 4) -> None:
        self.preset = preset
        self.threads = threads
        self._bin = self._find_binary()

    def _find_binary(self) -> str:
        binary = which("minimap2")
        if not binary:
            raise RuntimeError("minimap2 not found in PATH")
        return binary

    def make_index(self, fasta: Path, index_path: Path) -> None:
        cmd = [self._bin, "-d", str(index_path), str(fasta)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)

    def find(
        self,
        query: Path,
        target: Path,
        min_identity: float = 0.0,
        min_coverage: float = 0.0,
        preset: str | None = None,
        **kwargs: Any,
    ) -> list[Hit]:
        use_preset = preset or self.preset
        cmd = [
            self._bin,
            "-x",
            use_preset,
            "-t",
            str(self.threads),
            "-c",
            "--secondary=no",
            str(target),
            str(query),
        ]

        for key, value in kwargs.items():
            if value is None:
                continue
            if key == "threads":
                cmd[cmd.index("-t") + 1] = str(value)
                continue
            mapped = _PARAM_MAP.get(key, key)
            if isinstance(value, bool):
                if value:
                    cmd.append(f"-{mapped}")
            else:
                cmd.extend([f"-{mapped}", str(value)])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"minimap2 failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}"
            )

        hits: list[Hit] = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                hit = Hit.from_paf_line(line)
            except ValueError:
                continue
            if hit.identity >= min_identity and hit.query_coverage >= min_coverage:
                hits.append(hit)

        return hits
