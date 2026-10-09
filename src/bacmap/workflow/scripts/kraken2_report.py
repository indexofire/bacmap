#!/usr/bin/env python3
"""Parse kraken2 report + bracken output into a GOM-ready species_identification payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HOST_TAXID = "9606"
_OFF_TARGET_THRESHOLD_PCT = 90.0
_MODERATE_THRESHOLD_PCT = 50.0
_HOST_FLAG_THRESHOLD = 10.0


def parse_kraken2_report(text: str) -> dict[str, float]:
    species_pct: dict[str, float] = {}
    for ln in text.splitlines():
        cols = ln.rstrip().split()
        if len(cols) < 6 or cols[3] != "S":
            continue
        try:
            pct = float(cols[0])
        except ValueError:
            continue
        name = " ".join(cols[5:])
        species_pct[name] = pct
    return species_pct


def _host_pct(text: str) -> float:
    for ln in text.splitlines():
        cols = ln.rstrip().split()
        if len(cols) >= 6 and cols[4] == _HOST_TAXID:
            try:
                return float(cols[0])
            except ValueError:
                return 0.0
    return 0.0


def _bracken_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = text.splitlines()
    if not lines:
        return rows
    header = lines[0].split("\t")
    for ln in lines[1:]:
        cols = ln.split("\t")
        if len(cols) == len(header):
            rows.append(dict(zip(header, cols)))
    return rows


def build_result(report_text: str, bracken_text: str, declared_species: str) -> dict[str, Any]:
    species_pct = parse_kraken2_report(report_text)
    host = _host_pct(report_text)
    bracken = _bracken_rows(bracken_text)

    declared_pct = 0.0
    top: list[dict[str, Any]] = []
    for row in bracken:
        name = row.get("name", "")
        try:
            frac = float(row.get("fraction_total_reads", "0")) * 100
        except ValueError:
            frac = 0.0
        top.append(
            {
                "species": name,
                "abundance_pct": round(frac, 2),
                "reads": int(row.get("new_est_reads", "0") or 0),
            }
        )
        if _matches_declared(name, declared_species):
            declared_pct += frac
    top.sort(key=lambda t: -t["abundance_pct"])

    if declared_pct >= _OFF_TARGET_THRESHOLD_PCT:
        species, confidence = top[0]["species"], "high"
    elif declared_pct >= _MODERATE_THRESHOLD_PCT:
        species, confidence = (top[0]["species"] if top else "Unknown"), "medium"
    else:
        species, confidence = "Off-target", "low"

    flags: list[str] = []
    if declared_pct < _OFF_TARGET_THRESHOLD_PCT:
        flags.append("off_target_species")
    if host >= _HOST_FLAG_THRESHOLD:
        flags.append("high_host_content")

    return {
        "analysis_type": "species_identification",
        "method": "kraken2",
        "database": {"name": "kraken2_custom", "version": "panel-linked"},
        "result": {
            "species": species,
            "confidence": confidence,
            "declared_species": declared_species,
            "declared_abundance_pct": round(declared_pct, 2),
            "top_hits": top[:5],
            "host_reads_removed_pct": host,
            "flags": flags,
        },
    }


def _matches_declared(name: str, declared: str) -> bool:
    declared = declared.strip().lower()
    return bool(declared) and declared in name.lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--bracken", required=True, type=Path)
    parser.add_argument("--declared-species", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = build_result(args.report.read_text(), args.bracken.read_text(), args.declared_species)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
