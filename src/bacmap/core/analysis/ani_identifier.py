"""ANI-based species identification (species-id plan A: panel / skani_gtdb / mash_refseq)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bacmap.config import SPECIES_DB_DIR
from bacmap.core.engine.backends.skani import AniHit

_DB_BY_MODE = {
    "panel": "refseq_panel",
    "skani_gtdb": "skani_gtdb",
    "mash_refseq": "mash_refseq",
}

_ANI_HIGH = 95.0
_ANI_MEDIUM = 93.0
_AF_MIN = 0.65
_MASH_IDENTITY_HIGH = 0.97
_TOP_N = 10


@dataclass
class AniIdResult:
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


def _hits_from_rows(rows: list[tuple[str, float, float]]) -> list[AniHit]:
    return [AniHit(ref=r, ani=a, aligned_fraction=af) for r, a, af in rows]


def _skani_search(query: str | Path, db: Path) -> list[AniHit]:
    from bacmap.core.engine.backends.skani import SkaniBackend

    return SkaniBackend().search(Path(query), db)


def _mash_dist(query: str | Path, msh: Path) -> list[tuple[str, float]]:
    import shutil

    from bacmap.config import pixi_path

    mash = shutil.which("mash", path=pixi_path()) or shutil.which("mash") or "mash"
    result = subprocess.run(
        [mash, "dist", str(msh), str(query)], capture_output=True, text=True, timeout=600
    )
    rows: list[tuple[str, float]] = []
    for ln in result.stdout.splitlines():
        cols = ln.split("\t")
        if len(cols) >= 3:
            try:
                rows.append((cols[0], 1.0 - float(cols[2])))
            except ValueError:
                continue
    return rows


def _mash_species(ref_id: str) -> str:
    return ref_id


def _load_taxa_map(db_dir: Path) -> dict[str, str]:
    for candidate in ("metadata.tsv", "taxa_map.tsv"):
        path = db_dir / candidate
        if path.is_file():
            mapping: dict[str, str] = {}
            for ln in path.read_text(encoding="utf-8").splitlines()[1:]:
                cols = ln.split("\t")
                if len(cols) >= 2:
                    mapping[cols[0].strip()] = cols[1].strip()
            return mapping
    return {}


def _db_version(db_dir: Path, name: str) -> str:
    manifest = db_dir.parent / "manifests" / f"{name}.json"
    if manifest.is_file():
        try:
            checksum = json.loads(manifest.read_text()).get("checksum", "")
            return checksum[:8] if checksum else "unknown"
        except json.JSONDecodeError:
            return "unknown"
    return "unknown"


def identify_by_ani(
    contigs: str | Path,
    mode: str,
    db_dir: str | Path | None = None,
) -> AniIdResult:
    if mode not in _DB_BY_MODE:
        raise ValueError(f"unsupported ANI mode {mode!r}; expected one of {sorted(_DB_BY_MODE)}")
    db_name = _DB_BY_MODE[mode]
    base = Path(db_dir) if db_dir else SPECIES_DB_DIR / db_name
    taxa = _load_taxa_map(base)
    database = {"name": db_name, "version": _db_version(base, db_name)}

    if mode == "mash_refseq":
        msh = base / "mash.msh"
        if not msh.exists():
            msh = base / "payload.bin"
        mash_rows = _mash_dist(contigs, msh)
        mash_top = sorted(mash_rows, key=lambda r: -r[1])[:_TOP_N]
        best_ref, best_identity = mash_top[0] if mash_top else ("", 0.0)
        species = taxa.get(best_ref, _mash_species(best_ref)) if best_ref else "Unknown"
        confidence = "high" if best_identity >= _MASH_IDENTITY_HIGH else "low"
        result = {
            "species": species or "Unknown",
            "confidence": confidence,
            "identity": best_identity,
            "top_hits": [{"genome": r, "identity": i} for r, i in mash_top],
        }
        if 0.90 <= best_identity < _MASH_IDENTITY_HIGH:
            result["confidence"] = "medium"
        return AniIdResult(method=mode, database=database, result=result)

    skani_db = base / "panel.sketch" if (base / "panel.sketch").exists() else base
    skani_hits = sorted(
        _skani_search(contigs, skani_db), key=lambda h: (-h.ani, -h.aligned_fraction)
    )
    top = skani_hits[:_TOP_N]
    best = top[0] if top else None

    species, confidence = "Unknown", "low"
    if best is not None:
        if best.ani >= _ANI_HIGH and best.aligned_fraction >= _AF_MIN:
            species, confidence = taxa.get(best.ref, best.ref), "high"
        elif _ANI_MEDIUM <= best.ani < _ANI_HIGH and best.aligned_fraction >= _AF_MIN:
            species, confidence = taxa.get(best.ref, best.ref), "medium"

    result = {
        "species": species,
        "confidence": confidence,
        "ani": best.ani if best else None,
        "aligned_fraction": best.aligned_fraction if best else None,
        "top_hits": [
            {
                "genome": h.ref,
                "species": taxa.get(h.ref, h.ref),
                "ani": h.ani,
                "af": h.aligned_fraction,
            }
            for h in top
        ],
    }
    return AniIdResult(method=mode, database=database, result=result)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="ANI species identifier")
    parser.add_argument("contigs")
    parser.add_argument("--mode", required=True, choices=sorted(_DB_BY_MODE))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    res = identify_by_ani(args.contigs, args.mode)
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        r = res.result
        print(f"Species: {r['species']} ({r['confidence']}) via {res.method}")
        for h in r.get("top_hits", [])[:5]:
            print(f"  {h['genome']}: {h.get('ani', h.get('identity'))}")


if __name__ == "__main__":
    main()
