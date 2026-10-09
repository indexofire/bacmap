#!/usr/bin/env python3
"""Generate whole-genome SNP matrix in FASTA format from a multi-sample VCF.

Strategy: whole-genome mode (snippy-core style)
  - Includes ALL variant sites (not just strict core)
  - Missing genotypes (./.:) filled with N
  - Low QUAL sites filtered out
  - Only biallelic SNPs (len(ref)==1, len(alt)==1)

Usage:
    python generate_snp_matrix.py <input.vcf.gz> <output.fasta> [--min-qual 30]
"""
from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path


def read_vcf(vcf_path: str) -> tuple[list[str], list[list[str]]]:
    opener = gzip.open if vcf_path.endswith(".gz") else open

    samples: list[str] = []
    variants: list[list[str]] = []

    with opener(vcf_path, "rt") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                samples = line.split("\t")[9:]
                continue
            if not line or not samples:
                continue

            fields = line.split("\t")
            ref = fields[3]
            alt = fields[4]
            qual_str = fields[5]

            if len(ref) != 1 or not alt or len(alt.split(",")[0]) != 1:
                continue

            try:
                qual = float(qual_str) if qual_str != "." else 0
            except ValueError:
                qual = 0
            if qual < 30:
                continue

            variants.append(fields)

    return samples, variants


def genotype_to_allele(gt: str, ref: str, alts: list[str]) -> str:
    """Convert a GT field to an allele code.

    Bacterial genomes are effectively haploid, so heterozygous calls
    (0/1) are treated as ALT. Missing calls become N.
    """
    if gt.startswith("./.") or gt.startswith(".") or gt == ".":
        return "N"

    gt_clean = gt.replace("|", "/")
    parts = [p for p in gt_clean.split("/") if p != "."]
    if not parts:
        return "N"

    if all(p == "0" for p in parts):
        return ref

    nonzero = [p for p in parts if p != "0"]
    if nonzero:
        idx = int(nonzero[0]) - 1
        return alts[idx] if idx < len(alts) else alts[0]

    return ref


def build_snp_matrix(
    samples: list[str], variants: list[list[str]]
) -> tuple[list[list[str]], list[list[str]]]:
    snp_sites: list[list[str]] = []

    for fields in variants:
        ref = fields[3]
        alt = fields[4]
        alts = alt.split(",")
        fmt_keys = fields[8].split(":")
        gt_idx = fmt_keys.index("GT") if "GT" in fmt_keys else 0

        sample_alleles: list[str] = []
        for i in range(len(samples)):
            sample_data = fields[9 + i].split(":")
            gt = sample_data[gt_idx] if gt_idx < len(sample_data) else "./."
            sample_alleles.append(genotype_to_allele(gt, ref, alts))

        if any(a != ref for a in sample_alleles):
            snp_sites.append(sample_alleles)

    # Transpose: snp_sites[site][sample] -> matrix[sample][site]
    matrix = [[site[i] for site in snp_sites] for i in range(len(samples))]

    return snp_sites, matrix


def write_fasta(
    output_path: str, samples: list[str], matrix: list[list[str]]
) -> None:
    with open(output_path, "w") as f:
        for i, sample in enumerate(samples):
            seq = "".join(matrix[i])
            f.write(f">{sample}\n{seq}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate whole-genome SNP matrix in FASTA format"
    )
    parser.add_argument("input_vcf", help="Multi-sample VCF (.vcf or .vcf.gz)")
    parser.add_argument("output_fasta", help="Output FASTA alignment path")
    parser.add_argument(
        "--min-qual",
        type=float,
        default=30.0,
        help="Minimum QUAL score (default: 30)",
    )
    args = parser.parse_args()

    if not Path(args.input_vcf).exists():
        print(f"ERROR: input VCF not found: {args.input_vcf}", file=sys.stderr)
        return 1

    print(f"Reading VCF: {args.input_vcf}", file=sys.stderr)
    samples, variants = read_vcf(args.input_vcf)
    print(f"  Samples: {len(samples)}", file=sys.stderr)
    print(f"  Variants (QUAL>={args.min_qual}, biallelic SNP): {len(variants)}", file=sys.stderr)

    print("Building SNP matrix (whole-genome mode, N for missing)...", file=sys.stderr)
    snp_sites, matrix = build_snp_matrix(samples, variants)
    n_sites = len(snp_sites)
    print(f"  SNP sites (>=1 sample differs from REF): {n_sites}", file=sys.stderr)

    total_cells = len(samples) * n_sites
    missing_cells = sum(1 for site in snp_sites for a in site if a == "N")
    if total_cells > 0:
        pct = 100.0 * missing_cells / total_cells
        print(f"  Missing cells: {missing_cells}/{total_cells} ({pct:.1f}%)", file=sys.stderr)

    if len(samples) >= 2 and n_sites > 0:
        print("\nPairwise SNP distances:", file=sys.stderr)
        for i in range(len(samples)):
            for j in range(i + 1, len(samples)):
                d = 0
                compared = 0
                for site in snp_sites:
                    if site[i] != "N" and site[j] != "N":
                        compared += 1
                        if site[i] != site[j]:
                            d += 1
                print(
                    f"  {samples[i]} vs {samples[j]}: {d} SNPs ({compared} compared)",
                    file=sys.stderr,
                )

    write_fasta(args.output_fasta, samples, matrix)
    print(
        f"\nFASTA written: {args.output_fasta} ({len(samples)} taxa x {n_sites} sites)",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
