from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .._env import which


@dataclass(frozen=True)
class AniHit:
    ref: str
    ani: float
    aligned_fraction: float
    backend: str = "skani"


def _find_bin() -> str:
    found = which("skani")
    if not found:
        raise RuntimeError(
            "skani not found in PATH. Install: pixi add 'skani=0.3.*' (locked to "
            "match the official pre-sketched GTDB database format)"
        )
    return found


class SkaniBackend:
    """skani ANI search against a pre-sketched database (skani sketch ... -o db)."""

    def __init__(self) -> None:
        self._bin = _find_bin()

    def search(self, query: Path, db: Path) -> list[AniHit]:
        result = subprocess.run(
            [self._bin, "search", str(query), "-d", str(db)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"skani search failed: {result.stderr.strip()}")

        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        if not lines:
            return []

        header = lines[0].split("\t")
        try:
            ref_i = header.index("ref_filename")
            qaf_i = header.index("Estimated_query_aligned_fraction")
            ani_i = header.index("ANI")
        except ValueError:
            ref_i, qaf_i, ani_i = 0, 3, 5

        hits: list[AniHit] = []
        for ln in lines[1:]:
            cols = ln.split("\t")
            if len(cols) <= max(ref_i, qaf_i, ani_i):
                continue
            hits.append(
                AniHit(
                    ref=cols[ref_i].strip(),
                    ani=float(cols[ani_i]),
                    aligned_fraction=float(cols[qaf_i]),
                )
            )
        return hits
