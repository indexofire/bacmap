"""Shared sample status / summary helpers for scripts/run_analysis.py and web/app.py.

Reads pipeline artifacts under the results directory; pure functions, no state.
Status strings follow the web convention: "completed" | "in-progress" | "not-started".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bacmap.core.utils import parse_mlst


def summary_path(results_dir: Path, sample_id: str) -> Path:
    return results_dir / sample_id / "report" / f"{sample_id}_summary.json"


def sample_steps(results_dir: Path, sample_id: str) -> dict[str, bool]:
    """Existence of the six pipeline step artifacts for one sample."""
    base = results_dir / sample_id
    return {
        "qc": (base / "qc" / f"{sample_id}_fastp.json").exists(),
        "assembly": (base / "assembly" / "contigs.fasta").exists(),
        "species": (base / "species" / "species_id.json").exists(),
        "mlst": (base / "typing" / "mlst.tsv").exists(),
        "amr": (base / "amr" / "abricate_card.tsv").exists(),
        "report": summary_path(results_dir, sample_id).exists(),
    }


def read_summary(results_dir: Path, sample_id: str) -> dict[str, Any] | None:
    """Read the per-sample summary JSON; None when missing or unparseable."""
    p = summary_path(results_dir, sample_id)
    if not p.exists():
        return None
    try:
        result: dict[str, Any] = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    return result


def sample_status(results_dir: Path, sample_id: str) -> str:
    """Canonical status: completed (summary) > in-progress (contigs) > not-started."""
    if summary_path(results_dir, sample_id).exists():
        return "completed"
    if (results_dir / sample_id / "assembly" / "contigs.fasta").exists():
        return "in-progress"
    return "not-started"


def classify_samples(results_dir: Path, sample_ids: list[str]) -> dict[str, Any]:
    """Group samples into done / in_progress / not_started plus SNP cohort status.

    A sample is done when its report exists, in_progress when any pipeline step
    artifact exists, otherwise not_started.
    """
    done: dict[str, dict[str, bool]] = {}
    in_progress: dict[str, dict[str, bool]] = {}
    not_started: list[str] = []

    for sid in sample_ids:
        steps = sample_steps(results_dir, sid)
        if steps["report"]:
            done[sid] = steps
        elif any(steps.values()):
            in_progress[sid] = steps
        else:
            not_started.append(sid)

    return {
        "done": done,
        "in_progress": in_progress,
        "not_started": not_started,
        "snp_cohort": snp_cohort_status(results_dir),
    }


def summary_fields(summary: dict[str, Any]) -> dict[str, str]:
    """Extract species / MLST ST / serotype display fields from a summary dict."""
    steps = summary.get("steps", {})

    species = steps.get("species", {})
    species_name = species.get("species", "N/A") if isinstance(species, dict) else str(species)

    mlst_raw = steps.get("mlst", "")
    st = parse_mlst(mlst_raw)["st"] if mlst_raw and isinstance(mlst_raw, str) else "N/A"

    sero = steps.get("serotype", {})
    serotype = sero.get("sistr", "N/A") if isinstance(sero, dict) else "N/A"

    return {"species": species_name, "mlst_st": st, "serotype": serotype}


def snp_cohort_status(results_dir: Path) -> dict[str, bool]:
    return {
        "tree": (results_dir / "snp" / "core.treefile").exists(),
        "summary": (results_dir / "snp" / "snp_summary.json").exists(),
    }
