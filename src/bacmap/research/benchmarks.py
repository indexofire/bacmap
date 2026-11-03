"""P2 科学基准：合成 L0、真实数据 L1/L2，以及数据清单校验。

真实数据不进入代码仓库；调用方通过 ``BACMAP_BENCHMARK_DATA`` 或 ``$BACMAP_HOME/benchmarks``
指向本地快照。基准是**观察性回归测试**，不是金标准真值。
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from bacmap.research.stats import (
    associate_counts,
    benjamini_hochberg,
    sensitivity_summary,
)


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    table: tuple[int, int, int, int]
    direction: str  # positive | null | negative
    max_p: float


AMR_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase("strong-positive", (6, 1, 2, 7), "positive", 0.10),
    BenchmarkCase("null", (5, 5, 5, 5), "null", 1.01),
    BenchmarkCase("strong-negative", (1, 6, 7, 2), "negative", 0.10),
)

# 已知的碳青霉烯酶先验方向；CTX-M 不是碳青霉烯酶，观察到的负相关是混杂示例。
BVBRC_TARGETS: dict[str, dict] = {
    "OXA-48": {"needles": ("oxa-48",), "expected": "positive"},
    "KPC": {"needles": ("kpc",), "expected": "positive"},
    "NDM": {"needles": ("ndm",), "expected": "positive"},
    "CTX-M": {"needles": ("ctx-m", "ctxm"), "expected": "not_positive"},
}


def _direction(odds_ratio: float | None) -> str:
    if odds_ratio is None:
        return "unknown"
    if odds_ratio > 1:
        return "positive"
    if odds_ratio < 1:
        return "negative"
    return "null"


def run_amr_benchmark() -> dict:
    results = []
    for case in AMR_CASES:
        stat = associate_counts(*case.table)
        if case.direction == "positive":
            ok = stat.odds_ratio is not None and stat.odds_ratio > 1 and (
                stat.p_value is not None and stat.p_value <= case.max_p
            )
        elif case.direction == "negative":
            ok = stat.odds_ratio is not None and stat.odds_ratio < 1 and (
                stat.p_value is not None and stat.p_value <= case.max_p
            )
        else:
            ok = stat.odds_ratio is not None and abs(stat.odds_ratio - 1) < 1e-9
        results.append(
            {
                "name": case.name,
                "table": list(case.table),
                "odds_ratio": stat.odds_ratio,
                "p_value": stat.p_value,
                "pass": bool(ok),
            }
        )
    return {
        "suite": "amr-association-l0",
        "passed": all(r["pass"] for r in results),
        "cases": results,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_rows(path: Path) -> int:
    """Count data rows: JSON array length, or CSV lines minus the header."""
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, list) else 1
    with path.open(encoding="utf-8", errors="replace") as fh:
        return max(0, sum(1 for _ in fh) - 1)


def verify_benchmark_dir(root: Path | str, manifest_path: Path | str | None = None) -> dict:
    """校验本地基准快照：文件存在、SHA-256、最小行数。

    manifest 缺失时返回 ``available=False``；校验失败返回 ``ok=False`` 并保留逐项
    ``checks``，便于 CI/运维定位，而不是静默使用被替换的数据。
    """
    root = Path(root)
    manifest = Path(manifest_path) if manifest_path else root / "manifest.json"
    if not manifest.is_file():
        return {
            "dataset": root.name,
            "available": False,
            "ok": False,
            "reason": f"manifest not found: {manifest}",
            "checks": [],
        }
    data = json.loads(manifest.read_text(encoding="utf-8"))
    checks: list[dict] = []
    for rel, spec in (data.get("files") or {}).items():
        path = root / rel
        exists = path.is_file()
        entry = {"file": rel, "exists": exists, "ok": False}
        if exists:
            actual = sha256_file(path)
            entry["sha256"] = actual
            entry["sha256_ok"] = not spec.get("sha256") or actual == spec["sha256"]
            if spec.get("min_rows") is not None:
                rows = _count_rows(path)
                entry["rows"] = rows
                entry["rows_ok"] = rows >= int(spec["min_rows"])
            else:
                entry["rows_ok"] = True
            entry["ok"] = bool(entry["sha256_ok"] and entry["rows_ok"])
        checks.append(entry)
    return {
        "dataset": data.get("dataset", root.name),
        "version": data.get("version", ""),
        "available": True,
        "ok": bool(checks) and all(c["ok"] for c in checks),
        "checks": checks,
    }


def _bvbrc_stratum(row: dict[str, str]) -> str:
    for key in ("geo_loc_name", "isolation_source", "testing_standard"):
        value = (row.get(key) or "").strip()
        if value and value.casefold() not in {"na", "n/a", "not available", "unknown"}:
            return value.casefold()
    return "unknown"


def run_bvbrc_amr_benchmark(data_dir: Path | str) -> dict:
    """Run a real-data AMR benchmark from a BV-BRC snapshot directory.

    Expected files: ``labels.csv`` (genome_id, phenotype, ...) and ``genes.csv``
    (genome_id, gene, product). The data is not committed; see dev/benchmark-data.
    """
    root = Path(data_dir)
    labels_path = root / "labels.csv"
    genes_path = root / "genes.csv"
    if not labels_path.is_file() or not genes_path.is_file():
        return {
            "suite": "bvbrc-amr-real",
            "available": False,
            "reason": "labels.csv/genes.csv missing",
        }
    by_gene: dict[str, set[str]] = {k: set() for k in BVBRC_TARGETS}
    with genes_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            text = f"{row.get('gene', '')} {row.get('product', '')}".casefold()
            for target, spec in BVBRC_TARGETS.items():
                if any(n in text for n in spec["needles"]):
                    by_gene[target].add(row["genome_id"])
    with labels_path.open(encoding="utf-8") as fh:
        labels = list(csv.DictReader(fh))
    results = []
    p_values: list[float | None] = []
    intermediate = sum(
        1 for row in labels if row.get("phenotype", "").strip().lower() == "intermediate"
    )
    for target, spec in BVBRC_TARGETS.items():
        a = b = c = d = 0
        strata: dict[str, list[int]] = {}
        for row in labels:
            ph = row.get("phenotype", "").strip().lower()
            if ph not in {"resistant", "susceptible"}:
                continue
            present = row["genome_id"] in by_gene[target]
            resistant = ph == "resistant"
            if present and resistant:
                a += 1
                cell = 0
            elif present and not resistant:
                b += 1
                cell = 1
            elif not present and resistant:
                c += 1
                cell = 2
            else:
                d += 1
                cell = 3
            geo = _bvbrc_stratum(row)
            counts = strata.setdefault(geo, [0, 0, 0, 0])
            counts[cell] += 1
        stat = associate_counts(a, b, c, d)
        sensitivity = sensitivity_summary(
            (a, b, c, d),
            [
                (geo, counts[0], counts[1], counts[2], counts[3])
                for geo, counts in sorted(strata.items())
            ],
        )
        direction = _direction(stat.odds_ratio)
        expected = spec["expected"]
        passed = direction == expected or (expected == "not_positive" and direction != "positive")
        p_values.append(stat.p_value)
        results.append(
            {
                "target": target,
                "n": stat.n,
                "table": stat.table,
                "odds_ratio": stat.odds_ratio,
                "ci_low": stat.ci_low,
                "ci_high": stat.ci_high,
                "p_value": stat.p_value,
                "direction": direction,
                "expected_direction": expected,
                "pass": bool(passed),
                "sensitivity": sensitivity,
            }
        )
    for result, q in zip(results, benjamini_hochberg(p_values), strict=True):
        result["q_value"] = q
    verification = (
        verify_benchmark_dir(root) if (root / "manifest.json").is_file() else None
    )
    return {
        "suite": "bvbrc-amr-real",
        "available": True,
        "passed": all(r["pass"] for r in results),
        "n_labels": len(labels),
        "n_excluded_intermediate": intermediate,
        "multiplicity": "Benjamini-Hochberg FDR across targets",
        "verification": verification,
        "cases": results,
    }


def summarize_osf_cohort(root: Path | str) -> dict:
    """Summarise the OSF n78q3 cohort without re-running bioinformatics.

    Reads ``table_s1.csv`` (metadata), ``table_s2.csv`` (colistin phenotype) and
    ``genomes.csv`` (UUID -> assembly file). This is a data-quality benchmark:
    phenotype availability, study composition and assembly coverage.
    """
    root = Path(root)
    metadata_path = root / "table_s1.csv"
    phenotype_path = root / "table_s2.csv"
    genomes_path = root / "genomes.csv"
    if not all(p.is_file() for p in (metadata_path, phenotype_path, genomes_path)):
        return {
            "suite": "osf-n78q3-cohort",
            "available": False,
            "reason": "table_s1.csv/table_s2.csv/genomes.csv missing",
        }

    def _read(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return list(csv.DictReader(fh))

    metadata = _read(metadata_path)
    phenotypes = _read(phenotype_path)
    with genomes_path.open(encoding="utf-8", errors="replace") as fh:
        first = fh.readline().strip()
        fh.seek(0)
        if first.lower().startswith("name,"):
            mappings = list(csv.DictReader(fh))
            mapping_names = {str(r.get("name", "")) for r in mappings}
        else:
            mapping_names = {line.split(",", 1)[0] for line in fh if line.strip()}

    meta_names = {r.get("name", "") for r in metadata}
    pheno_names = {r.get("name", "") for r in phenotypes}
    studies: dict[str, int] = {}
    for row in metadata:
        study = (row.get("study") or "unknown").strip()
        studies[study] = studies.get(study, 0) + 1
    breakpoints: dict[str, int] = {}
    for row in phenotypes:
        bp = (row.get("breakpoint") or "unknown").strip() or "unknown"
        breakpoints[bp] = breakpoints.get(bp, 0) + 1
    extracted = root / "extracted"
    assemblies = (
        sorted(extracted.rglob("*.fna.gz")) if extracted.is_dir() else []
    )
    pheno_with_meta = len(pheno_names & meta_names)
    return {
        "suite": "osf-n78q3-cohort",
        "available": True,
        "n_metadata": len(metadata),
        "n_phenotypes": len(phenotypes),
        "n_genome_mappings": len(mapping_names),
        "n_assemblies_extracted": len(assemblies),
        "n_phenotype_names": len(pheno_names),
        "n_phenotype_with_metadata": pheno_with_meta,
        "phenotype_coverage": round(pheno_with_meta / len(meta_names), 4) if meta_names else 0.0,
        "n_phenotype_without_metadata": len(pheno_names - meta_names),
        "n_metadata_without_phenotype": len(meta_names - pheno_names),
        "top_studies": sorted(studies.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "breakpoints": dict(sorted(breakpoints.items())),
        "limits": [
            "single/regional hospital context; not a global population",
            "phenotype missingness is not random",
            "assemblies are filtered derivatives; raw reads are not included",
            "no lineage or variant calls are recomputed here",
        ],
    }
