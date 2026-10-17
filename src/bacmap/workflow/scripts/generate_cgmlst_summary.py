#!/usr/bin/env python3
"""Generate cohort-level cgMLST summary JSON from tree + matrix artifacts.

Reads:
    - core.treefile     (Newick, 由 gmlst visual mst + mst_to_newick.py 生成)
    - distance_matrix.json (from gmlst visual matrix)
    - cgmlst_profiles.tsv (merged per-sample profiles, from cgmlst_cohort_profiles)

Writes:
    - cgmlst_summary.json with the fields required by todo 11:
        samples, n_samples, scheme, n_loci, allele_distances, tree_newick,
        missing_rate, thresholds_applied (group's configured thresholds for
        reproducibility), plus group/organism labels when supplied.

Mirrors ``workflows/bacmap/scripts/generate_snp_summary.py`` (format-agnostic
Newick + matrix -> JSON), reusing the cgMLST parser for missing-rate
computation so marker handling (``-`` / ``~N`` / ``N,M`` / ``NN?``) stays
consistent with the rest of the pipeline.

Usage:
    python generate_cgmlst_summary.py <treefile> <matrix.json> <profiles.tsv> \\
        <output.json> [--group salmonella] [--organism "..."] [--scheme senterica_2] \\
        [--config-file workflows/bacmap/config/config.yaml]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the bacmap package is importable under the pixi env.
from bacmap.core.utils import parse_cgmlst_profiles  # noqa: E402


def _missing_rate(profiles_tsv: str) -> float:
    """Fraction of non-called loci across all cohort profiles.

    A locus counts as missing for a sample if its call was ``-`` / ``NN?``
    (missing_loci), ``~N`` (novel_loci), or ``N,M`` (ambiguous_loci) — every
    non-exact marker class. Loci with a clean integer call are excluded from
    the numerator. Mirrors the EnteroBase "missing" reporting convention.
    """
    profiles = parse_cgmlst_profiles(profiles_tsv)
    if not profiles:
        return 0.0
    total = sum(p.n_total for p in profiles)
    missing = sum(
        len(p.missing_loci) + len(p.novel_loci) + len(p.ambiguous_loci)
        for p in profiles
    )
    return round(missing / total, 4) if total > 0 else 0.0


def _load_thresholds(config_file: str | None, group: str | None) -> dict[str, object]:
    """Read this group's thresholds from config.yaml for the summary audit trail.

    Returns ``{}`` when the config or group is unavailable so the summary is
    still valid; a missing threshold file is non-fatal (the cohort summary is
    descriptive, the per-sample trace-back in todo 7 is the authoritative
    threshold consumer).
    """
    if not config_file or not group:
        return {}
    cfg_path = Path(config_file)
    if not cfg_path.exists():
        return {}
    try:
        import yaml  # PyYAML ships with snakemake in the pixi env.
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:  # pragma: no cover - defensive: config read must never break summary
        return {}
    thresholds = cfg.get("cgmlst", {}).get("thresholds", {})
    # config.yaml 的 cgmlst.thresholds 按物种名建键（salmonella/ecoli/shigella/
    # vparahaemolyticus，与 cgmlst_projection._load_species_thresholds 一致），
    # 而 cohort 的 group 名是 pathogens.yaml 的 snp_groups 键（salmonella/ecoli/
    # vpara）。故需把 group 映射到物种键，否则 vpara 组的 thresholds_applied 恒为空。
    group_to_species_key = {
        "salmonella": "salmonella",
        "ecoli": "ecoli",
        "shigella": "shigella",
        "vpara": "vparahaemolyticus",
    }
    key = group_to_species_key.get(group, group)
    return thresholds.get(key, {}) or {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a cohort-level cgMLST summary JSON.",
    )
    parser.add_argument("treefile", help="Newick treefile path.")
    parser.add_argument("matrix", help="distance_matrix.json path.")
    parser.add_argument("profiles", help="Merged cgmlst_profiles.tsv path.")
    parser.add_argument("output", help="Output JSON path.")
    parser.add_argument("--group", default=None, help="Cohort group name.")
    parser.add_argument("--organism", default=None, help="Organism label.")
    parser.add_argument("--scheme", default=None, help="cgMLST scheme name override.")
    parser.add_argument(
        "--config-file",
        default=None,
        help="config.yaml path (used to record thresholds_applied for the group).",
    )
    args = parser.parse_args()

    tree_path = Path(args.treefile)
    matrix_path = Path(args.matrix)
    profiles_path = Path(args.profiles)

    for path in (tree_path, matrix_path, profiles_path):
        if not path.exists():
            print(f"ERROR: input not found: {path}", file=sys.stderr)
            return 1

    newick = tree_path.read_text().strip()
    matrix_payload = json.loads(matrix_path.read_text())
    # gmlst 0.5.5 `visual matrix --format json` 把 labels/matrix 放在顶层 data 键下；
    # 顶层缺关键字段时解封装，否则 samples/n_loci/allele_distances 全空。
    if isinstance(matrix_payload, dict) and not any(
        k in matrix_payload
        for k in ("labels", "matrix", "samples", "distances", "allele_distances")
    ):
        inner = matrix_payload.get("data")
        if isinstance(inner, dict):
            matrix_payload = inner
    missing_rate = _missing_rate(profiles_path.read_text())

    samples = matrix_payload.get("samples") or matrix_payload.get("labels") or []
    scheme = args.scheme or matrix_payload.get("scheme", "")
    n_loci = matrix_payload.get("n_loci", 0)
    # Prefer the flat allele_distances ("A|B" -> int); fall back to rebuilding
    # from the nested distances dict so the summary is populated regardless of
    # which matrix-generator version produced the JSON.
    allele_distances = matrix_payload.get("allele_distances")
    if not allele_distances:
        distances = matrix_payload.get("distances", {})
        flat = matrix_payload.get("matrix")
        allele_distances = {}
        for i in range(len(samples)):
            for j in range(i + 1, len(samples)):
                a, b = samples[i], samples[j]
                if distances:
                    allele_distances[f"{a}|{b}"] = distances.get(a, {}).get(b, 0)
                elif flat:
                    allele_distances[f"{a}|{b}"] = flat[i][j]

    summary: dict[str, object] = {
        "samples": samples,
        "n_samples": len(samples),
        "scheme": scheme,
        "n_loci": n_loci,
        "allele_distances": allele_distances,
        "tree_newick": newick,
        "missing_rate": missing_rate,
        "thresholds_applied": _load_thresholds(args.config_file, args.group),
    }
    if args.group:
        summary["group"] = args.group
    if args.organism:
        summary["organism"] = args.organism

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    print(
        f"cgMLST summary: {len(samples)} samples, {n_loci} loci, "
        f"missing_rate={missing_rate}",
        file=sys.stderr,
    )
    print(f"Written: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
