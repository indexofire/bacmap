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
    # (name, markers, mode, exclude) —— exclude 中的任一基因存在则整条规则不成立
    ("STEC", ["stx1", "stx2"], "any", []),
    ("EIEC/Shigella", ["ipaH", "ipaH0722", "ipaH9.8", "ipaB", "ipaC", "ipaD", "ipaJ", "ipgC", "mxi"], "any", []),
    ("tEPEC", ["eae", "bfpA"], "all", []),
    ("aEPEC", ["eae"], "any", ["bfpA"]),  # eae 阳性且无 bfpA
    ("ETEC", ["est", "elt", "STh", "STp", "LT"], "any", []),
    ("EAEC", ["aggR", "aatA", "aaiC"], "any", []),
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


def call_pathotype(genes: set[str]) -> list[tuple[str, list[str]]]:
    """返回 (pathotype, 命中的标记基因) 列表；无命中则 Non-pathogenic。"""
    results: list[tuple[str, list[str]]] = []
    for name, markers, mode, exclude in PATHOTYPE_RULES:
        markers_upper = {m.upper() for m in markers}
        if {e.upper() for e in exclude} & genes:
            continue  # 排他基因阳性（如 eae+bfpA 不再判 aEPEC）
        matched = sorted(markers_upper & genes)
        if mode == "any":
            if matched:
                results.append((name, matched))
        elif mode == "all":
            if markers_upper <= genes:
                results.append((name, sorted(markers_upper)))
    if not results:
        results.append(("Non-pathogenic", []))
    return results


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
        for pt, matched in pathotypes:
            f.write(f"{pt}\t{';'.join(matched)}\n")


if __name__ == "__main__":
    sys.exit(main())
