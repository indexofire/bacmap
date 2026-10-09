"""sourmash gather-based species identification (species-id plan B)."""

from __future__ import annotations

import csv
import io
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bacmap.config import SPECIES_DB_DIR

_FUW_HIGH = 0.90
_FUW_MEDIUM = 0.70
_MIXTURE_MEMBER = 0.10


@dataclass
class SourmashIdResult:
    method: str
    database: dict[str, str]
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_type": "species_identification",
            "method": self.method,
            "database": self.database,
            "result": self.result,
        }


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _gather_and_tax(contigs: str | Path, db_dir: Path) -> list[dict[str, Any]]:
    sig = db_dir / "query.sig"
    _run(["sourmash", "sketch", "dna", "-p", "k=31,scaled=1000", str(contigs), "-o", str(sig)])
    gather_csv = _run(
        [
            "sourmash",
            "gather",
            str(sig),
            str(db_dir / "gtdb-reps-k31.zip"),
            "--csv",
            "-",
            "-o",
            str(db_dir / "gather.csv"),
        ]
    )
    rows = list(csv.DictReader(io.StringIO(gather_csv))) if gather_csv.strip() else []
    lineage_map = _lineage_map(db_dir / "lineages.csv")
    out: list[dict[str, Any]] = []
    for row in rows:
        name = row.get("name", "")
        try:
            fuw = float(row.get("f_unique_weighted", 0.0))
        except ValueError:
            fuw = 0.0
        out.append({"lineage": lineage_map.get(name, name), "f_unique_weighted": fuw})
    return out


def _lineage_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    mapping: dict[str, str] = {}
    with path.open() as fh:
        for row in csv.reader(fh):
            if len(row) >= 2:
                mapping[row[0]] = row[-1].split(";")[-1].strip()
    return mapping


def _db_version(db_dir: Path) -> str:
    manifest = db_dir.parent / "manifests" / "sourmash_gtdb.json"
    if manifest.is_file():
        try:
            checksum = json.loads(manifest.read_text()).get("checksum", "")
            return checksum[:8] if checksum else "RS226"
        except json.JSONDecodeError:
            return "RS226"
    return "RS226"


def identify_by_sourmash(contigs: str | Path, db_dir: str | Path | None = None) -> SourmashIdResult:
    base = Path(db_dir) if db_dir else SPECIES_DB_DIR / "sourmash_gtdb"
    partition = _gather_and_tax(contigs, base)
    database = {"name": "sourmash_gtdb", "version": _db_version(base)}

    best_fuw = max((p["f_unique_weighted"] for p in partition), default=0.0)
    flags: list[str] = []
    strong_members = [p for p in partition if p["f_unique_weighted"] >= _MIXTURE_MEMBER]
    if len(strong_members) >= 2:
        flags.append("possible_mixture")

    if best_fuw >= _FUW_HIGH and not flags:
        species, confidence = partition[0]["lineage"], "high"
    elif best_fuw >= _FUW_MEDIUM:
        species, confidence = partition[0]["lineage"], "medium"
    else:
        species, confidence = "Mixed/Unknown", "low"

    result = {
        "species": species or "Mixed/Unknown",
        "confidence": confidence,
        "f_unique_weighted": best_fuw,
        "gather_partition": [
            {"lineage": p["lineage"], "f_unique_weighted": p["f_unique_weighted"]}
            for p in partition
        ],
        "flags": flags,
    }
    return SourmashIdResult(method="sourmash", database=database, result=result)
