#!/usr/bin/env python3
"""根据 abricate vfdb 检出的毒力基因组合判断 DEC pathotype。

判定规则：
  stx1 或 stx2 阳性 → STEC
  eae + bfpA 阳性 → tEPEC（典型 EPEC）
  eae 阳性（无 bfpA）→ aEPEC（非典型 EPEC）
  ipaH 阳性 → EIEC/Shigella
  est 或 elt 阳性 → ETEC
  aggR 阳性 → EAEC
  以上均阴性 → Non-pathogenic E. coli
"""
import argparse
import sys
from pathlib import Path

PATHOTYPE_RULES = [
    ("STEC", ["stx1", "stx2"], "any"),
    ("EIEC/Shigella", ["ipaH", "ipaH0722", "ipaH9.8", "ipaB", "ipaC", "ipaD", "ipaJ", "ipgC", "mxi"], "any"),
    ("tEPEC", ["eae", "bfpA"], "all"),
    ("aEPEC", ["eae"], "any"),
    ("ETEC", ["est", "elt", "STh", "STp", "LT"], "any"),
    ("EAEC", ["aggR", "aatA", "aaiC"], "any"),
]


def parse_vfdb_genes(tsv_path: str) -> set[str]:
    genes = set()
    p = Path(tsv_path)
    if not p.exists() or p.stat().st_size == 0:
        return genes
    with p.open() as f:
        lines = f.readlines()[1:]
    for line in lines:
        parts = line.strip().split("\t")
        if len(parts) >= 6:
            gene = parts[5].upper()
            genes.add(gene)
    return genes


def call_pathotype(genes: set[str]) -> list[str]:
    pathotypes = []
    for name, markers, mode in PATHOTYPE_RULES:
        markers_upper = {m.upper() for m in markers}
        if mode == "any":
            if markers_upper & genes:
                pathotypes.append(name)
        elif mode == "all":
            if markers_upper <= genes:
                pathotypes.append(name)
    if not pathotypes:
        pathotypes.append("Non-pathogenic")
    return pathotypes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vfdb", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    genes = parse_vfdb_genes(args.vfdb)
    pathotypes = call_pathotype(genes)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        f.write("pathotype\tdetected_markers\n")
        for pt in pathotypes:
            f.write(f"{pt}\t{';'.join(sorted(genes)[:20])}\n")


if __name__ == "__main__":
    sys.exit(main())
