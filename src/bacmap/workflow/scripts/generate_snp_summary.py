#!/usr/bin/env python3
"""Generate cohort-level SNP summary JSON from tree + alignment artifacts.

Reads:
  - core.treefile (Newick)
  - core_snps.fasta (alignment)

Writes:
  - snp_summary.json (tree + pairwise distances + stats)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_fasta(path: str) -> dict[str, str]:
    seqs: dict[str, str] = {}
    name = None
    chunks: list[str] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    seqs[name] = "".join(chunks)
                name = line[1:]
                chunks = []
            else:
                chunks.append(line)
    if name is not None:
        seqs[name] = "".join(chunks)
    return seqs


def pairwise_distances(seqs: dict[str, str]) -> dict[str, int]:
    names = list(seqs.keys())
    distances: dict[str, int] = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            s1, s2 = seqs[names[i]], seqs[names[j]]
            d = 0
            compared = 0
            for a, b in zip(s1, s2):
                if a != "N" and b != "N":
                    compared += 1
                    if a != b:
                        d += 1
            key = f"{names[i]}|{names[j]}"
            distances[key] = d
    return distances


def count_missing(seqs: dict[str, str]) -> float:
    if not seqs:
        return 0.0
    total = sum(len(s) for s in seqs.values())
    missing = sum(s.count("N") for s in seqs.values())
    return missing / total if total > 0 else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SNP summary JSON")
    parser.add_argument("treefile", help="Path to Newick treefile")
    parser.add_argument("fasta", help="Path to alignment FASTA")
    parser.add_argument("output", help="Output JSON path")
    parser.add_argument("--group", default=None, help="SNP group name (e.g. salmonella)")
    parser.add_argument("--organism", default=None, help="Organism label")
    args = parser.parse_args()

    tree_path = Path(args.treefile)
    fasta_path = Path(args.fasta)

    if not tree_path.exists():
        print(f"ERROR: treefile not found: {tree_path}", file=sys.stderr)
        return 1
    if not fasta_path.exists():
        print(f"ERROR: FASTA not found: {fasta_path}", file=sys.stderr)
        return 1

    newick = tree_path.read_text().strip()
    seqs = read_fasta(str(fasta_path))

    n_sites = len(next(iter(seqs.values()))) if seqs else 0
    distances = pairwise_distances(seqs)
    missing_rate = count_missing(seqs)

    summary = {
        "tree_newick": newick,
        "n_snp_sites": n_sites,
        "n_samples": len(seqs),
        "samples": list(seqs.keys()),
        "pairwise_distances": distances,
        "missing_rate": round(missing_rate, 4),
    }
    if args.group:
        summary["group"] = args.group
    if args.organism:
        summary["organism"] = args.organism

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, indent=2))

    print(f"SNP summary: {len(seqs)} taxa, {n_sites} sites, {len(distances)} pairs", file=sys.stderr)
    print(f"Written: {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
