"""cohort 产物进入任务目标（v1.10.28）。

回归：cohort 规则只挂 `rule all`，而引擎按样本传显式目标，导致
`cgmlst/{group}/cgmlst_summary.json` 从未进入 DAG（用户侧表现为
"cgMLST 配置开了但 results 里没有 cgmlst 目录"）。
"""

from __future__ import annotations

from pathlib import Path

from bacmap.tasks.engine.dbos_engine import _cohort_targets


def _deployed(tmp_path: Path, rows: list[str], cohort: bool = True) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "config.yaml").write_text("threads: 4\n", encoding="utf-8")
    if cohort:
        (cfg / "config.local.yaml").write_text(
            "cgmlst:\n  run_cgmlst_cohort: true\n", encoding="utf-8"
        )
    (cfg / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tassembly\n" + "\n".join(rows) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_cgmlst_target_added_for_run_species(tmp_path):
    deployed = _deployed(
        tmp_path,
        [
            "CPE1\tCPE\t\t\t/a/CPE1.fna",
            "CPE2\tCPE\t\t\t/a/CPE2.fna",
            "SAL1\tSAL\t\t\t/a/SAL1.fna",
        ],
    )
    got = _cohort_targets(deployed, {"samples": ["CPE1", "CPE2"]}, tmp_path / "run")
    assert got == [str(tmp_path / "run" / "cgmlst" / "cpe" / "cgmlst_summary.json")]


def test_no_targets_when_cohort_disabled(tmp_path):
    deployed = _deployed(tmp_path, ["CPE1\tCPE\t\t\t/a/CPE1.fna"], cohort=False)
    assert _cohort_targets(deployed, {"samples": ["CPE1"]}, tmp_path / "run") == []


def test_unknown_species_yields_no_target(tmp_path):
    deployed = _deployed(tmp_path, ["X1\tUNKNOWN\t\t\t/a/X1.fna"])
    assert _cohort_targets(deployed, {"samples": ["X1"]}, tmp_path / "run") == []


def test_empty_samples_yields_no_target(tmp_path):
    deployed = _deployed(tmp_path, ["CPE1\tCPE\t\t\t/a/CPE1.fna"])
    assert _cohort_targets(deployed, {}, tmp_path / "run") == []
