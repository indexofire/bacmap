#!/usr/bin/env python3
"""病原菌自动分析编排器（4种病原通用）。

一次命令自动完成：QC → 组装 → 物种验证 → MLST → 血清型 → AMR → 毒力 → 报告。
Snakemake DAG 自动编排所有依赖，无需人为逐步触发。

用法:
    python scripts/run_analysis.py --sample SAM-TYP-001
    python scripts/run_analysis.py --all
    python scripts/run_analysis.py --status
    python scripts/run_analysis.py --status --sample SAM-TYP-001
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import validate_all_sample_names

from bacmap.config import RESULTS_DIR, WORKFLOWS_DIR
from bacmap.store.sample_summary import (
    classify_samples,
    read_summary,
    summary_fields,
    summary_path,
)

PIXI_BIN = Path(sys.executable).resolve().parent
WORKFLOW_DIR = WORKFLOWS_DIR / "bacmap"
RESULTS_DIR = RESULTS_DIR


def validate_sample(sample: str) -> None:
    import csv

    samples_tsv = WORKFLOW_DIR / "config/samples.tsv"
    if not samples_tsv.exists():
        print(f"❌ samples.tsv not found: {samples_tsv}")
        sys.exit(1)
    with samples_tsv.open() as f:
        valid = {r["sample"] for r in csv.DictReader(f, delimiter="\t")}
    if sample not in valid:
        print(f"❌ Unknown sample: {sample}")
        print(f"   Valid samples: {', '.join(sorted(valid))}")
        sys.exit(1)


SPECIES_MODES = ["simple", "panel", "skani_gtdb", "mash_refseq", "sourmash", "standard"]


def run_snakemake(
    targets: list[str],
    cores: int = 8,
    timeout: int = 7200,
    config_overrides: dict[str, str] | None = None,
) -> bool:
    import os

    env = dict(os.environ)
    env["PATH"] = f"{PIXI_BIN}:{env['PATH']}"

    cmd = [
        str(PIXI_BIN / "snakemake"),
        "-s",
        str(WORKFLOW_DIR / "Snakefile"),
        "--cores",
        str(cores),
        "--rerun-incomplete",
        "--printshellcmds",
    ]
    if config_overrides:
        cmd += ["--config"] + [f"{k}={v}" for k, v in config_overrides.items()]
    cmd += targets

    print(f"\n{'=' * 60}")
    print(f"启动 Snakemake 自动编排 ({len(targets)} target(s))")
    print(f"Cores: {cores}")
    print(f"{'=' * 60}\n")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(WORKFLOW_DIR),
            env=env,
            timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"\n❌ Snakemake 超时 ({timeout}s)。可能卡在锁等待或资源争用。")
        print(f"   检查: snakemake --unlock (在 {WORKFLOW_DIR} 下)")
        return False


def check_status(sample: str | None = None) -> dict:
    import csv

    samples_tsv = WORKFLOW_DIR / "config/samples.tsv"
    with samples_tsv.open() as f:
        all_samples = [r["sample"] for r in csv.DictReader(f, delimiter="\t")]

    ids = [s for s in all_samples if not sample or s == sample]
    return classify_samples(RESULTS_DIR, ids)


def interpret_summary(sample: str) -> None:
    summary = read_summary(RESULTS_DIR, sample)
    if summary is None:
        print(f"  ❌ {sample}: summary not found")
        return

    print(f"\n{'=' * 60}")
    print(f"  {sample} 分析结果")
    print(f"{'=' * 60}")

    fields = summary_fields(summary)

    verdict = fields["species"]
    icon = "✅" if verdict != "N/A" and verdict != "Unknown" else "❌"
    print(f"\n  {icon} Species: {verdict}")

    if fields["mlst_st"] != "N/A":
        print(f"  🧬 MLST: ST{fields['mlst_st']}")

    serotype = summary.get("steps", {}).get("serotype", {})
    if isinstance(serotype, dict):
        print(f"  🔬 Serotype (SISTR): {fields['serotype']}")

    amr = summary.get("steps", {}).get("amr", {})
    if isinstance(amr, dict):
        amrfp = amr.get("amrfinderplus", [])
        if amrfp:
            genes = [r.get("Gene symbol", "?") for r in amrfp if isinstance(r, dict)]
            print(f"  💊 AMR genes ({len(genes)}): {', '.join(genes[:10])}")
        else:
            print("  💊 AMR genes: none found (susceptible)")

    print(f"\n  Full report: {summary_path(RESULTS_DIR, sample)}")


# 分组一律由 registry 派生（单一事实来源），不再手抄 species 列表；
# samples.tsv 的 species 值经 resolve_species 双接受（码/标签/显示名）。
def _registry_tables():
    from bacmap.core.pathogen_registry import get_workflow_tables

    return get_workflow_tables()


def _resolve_species(value: str) -> str | None:
    from bacmap.core.pathogen_registry import resolve_species

    return resolve_species(value)


def _read_species(samples_tsv: Path) -> list[str]:
    import csv

    with samples_tsv.open() as f:
        return [row.get("species", "") for row in csv.DictReader(f, delimiter="\t")]


def _cohort_members(samples_tsv: Path, species_list: list[str]) -> int:
    codes = [_resolve_species(sp) for sp in _read_species(samples_tsv)]
    return sum(1 for c in codes if c in species_list)


def _cohort_targets(samples_tsv: Path, kind: str) -> list[str]:
    """≥2 样本的 cohort 目标（kind: snp|cgmlst），并附重组目标（plan-driven）。

    与 snp.smk/cgmlst.smk 的 ≥2 样本门一致，确保目标在 DAG 内可产出。
    """
    tables = _registry_tables()
    if kind == "snp":
        groups = tables.snp_groups
        summary_name = "snp_summary.json"
        recombination = set(tables.recombination_groups)
    else:
        groups = tables.cgmlst_species_groups
        summary_name = "cgmlst_summary.json"
        recombination = set()

    targets: list[str] = []
    for group, info in groups.items():
        if _cohort_members(samples_tsv, info["species"]) < 2:
            continue
        targets.append(str(RESULTS_DIR / kind / group / summary_name))
        if group in recombination:
            targets.append(str(RESULTS_DIR / "snp" / group / "recombination.json"))
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="病原菌自动分析编排器（4种病原通用）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", type=str, help="Sample ID to analyze")
    group.add_argument("--all", action="store_true", help="Analyze all samples")
    group.add_argument("--snp", action="store_true", help="Run SNP cohort analysis")
    group.add_argument(
        "--cgmlst",
        action="store_true",
        help="Run per-sample cgMLST typing (typing_cgmlst) for all samples",
    )
    group.add_argument(
        "--cgmlst-cohort",
        action="store_true",
        dest="cgmlst_cohort",
        help="Run cgMLST cohort analysis (distance matrix + MST + summary) per group",
    )
    # --status 可与 --sample 组合（查单样本状态），故不在互斥组内。
    parser.add_argument("--status", action="store_true", help="Check analysis status")
    parser.add_argument("--cores", type=int, default=8)
    parser.add_argument(
        "--species-mode",
        dest="species_mode",
        choices=SPECIES_MODES,
        help="Species identification method (default: config.yaml species_mode)",
    )
    args = parser.parse_args()

    has_action = bool(
        args.sample or args.all or args.snp or args.cgmlst or args.cgmlst_cohort
    )
    if not args.status and not has_action:
        parser.error(
            "one of --sample/--all/--snp/--cgmlst/--cgmlst-cohort is required "
            "(or --status)"
        )

    if args.status:
        status = check_status(args.sample)

        print(f"\n{'=' * 60}")
        print("  分析状态")
        print(f"{'=' * 60}")

        if status["done"]:
            print(f"\n  ✅ 完成 ({len(status['done'])} 株):")
            for s, _steps in status["done"].items():
                print(f"     {s}")
        if status["in_progress"]:
            print(f"\n  🔄 进行中 ({len(status['in_progress'])} 株):")
            for s, steps in status["in_progress"].items():
                done = sum(steps.values())
                total = len(steps)
                details = ", ".join(k for k, v in steps.items() if v)
                print(f"     {s}: {done}/{total} steps ({details})")
        if status["not_started"]:
            print(f"\n  ⬜ 未开始 ({len(status['not_started'])} 株):")
            for s in status["not_started"]:
                print(f"     {s}")

        snp = status.get("snp_cohort", {})
        snp_icon = "✅" if snp.get("summary") else ("🔄" if snp.get("tree") else "⬜")
        print(
            f"\n  {snp_icon} SNP Cohort: tree={'yes' if snp.get('tree') else 'no'}, "
            f"summary={'yes' if snp.get('summary') else 'no'}"
        )

        print()
        return 0

    if args.snp:
        targets = _cohort_targets(WORKFLOW_DIR / "config" / "samples.tsv", "snp")
    elif args.cgmlst:
        samples = validate_all_sample_names()
        targets = [str(RESULTS_DIR / s / "typing" / "cgmlst.tsv") for s in samples]
    elif args.cgmlst_cohort:
        targets = _cohort_targets(WORKFLOW_DIR / "config" / "samples.tsv", "cgmlst")
    elif args.sample:
        validate_sample(args.sample)
        target = str(RESULTS_DIR / args.sample / "report" / f"{args.sample}_summary.json")
        targets = [target]
    elif args.all:
        targets = []
    else:
        return 1

    validate_all_sample_names()
    if args.species_mode:
        success = run_snakemake(
            targets, args.cores, config_overrides={"species_mode": args.species_mode}
        )
    else:
        success = run_snakemake(targets, args.cores)

    if success:
        if args.snp:
            print("\n✅ SNP cohort analysis 完成。")
            print(f"   Trees/Summaries: {RESULTS_DIR}/snp/{{group}}/")
            print(f"   Recombination: {RESULTS_DIR}/snp/{{group}}/recombination.json（若启用）")
            print("   Report: python workflows/bacmap/scripts/generate_report.py --cohort")
        elif args.cgmlst:
            print("\n✅ cgMLST per-sample typing 完成。")
            print(f"   Profiles: {RESULTS_DIR}/{{sample}}/typing/cgmlst.tsv")
            print("   Ingest: python scripts/ingest_results.py --cgmlst")
        elif args.cgmlst_cohort:
            print("\n✅ cgMLST cohort analysis 完成。")
            print(f"   Summaries: {RESULTS_DIR}/cgmlst/{{group}}/cgmlst_summary.json")
            print("   Ingest: python scripts/ingest_results.py --cgmlst-cohort")
        elif args.sample:
            interpret_summary(args.sample)
        else:
            import csv

            failed = []
            with (WORKFLOW_DIR / "config/samples.tsv").open() as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    sid = r["sample"]
                    summary = RESULTS_DIR / sid / "report" / f"{sid}_summary.json"
                    if summary.exists():
                        interpret_summary(sid)
                    else:
                        failed.append(sid)
                        print(f"  ❌ {sid}: summary not found")
            if failed:
                print(f"\n⚠️  {len(failed)} sample(s) failed: {', '.join(failed)}")
                print(f"\n✅ 部分完成 ({len(failed)} 失败)。")
                return 1
        print("\n✅ 全部完成。")
        return 0
    else:
        from bacmap.core.analysis.failure_diagnostics import diagnose_from_log

        diag = diagnose_from_log(str(WORKFLOW_DIR / ".snakemake/log"))

        print("\n❌ Snakemake 失败。诊断结果:")
        print(f"   类型: {diag.error_type}")
        print(f"   原因: {diag.details}")
        if diag.rule_name:
            print(f"   规则: {diag.rule_name}")
        print(f"   修复: {diag.suggested_fix}")
        if diag.recovery_commands:
            print("   命令:")
            for cmd in diag.recovery_commands:
                print(f"     $ {cmd}")
        print(f"\n   手动检查: {WORKFLOW_DIR}/.snakemake/log/")
        return 1


if __name__ == "__main__":
    sys.exit(main())
