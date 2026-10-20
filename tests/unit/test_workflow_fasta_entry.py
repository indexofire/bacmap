"""assembly 直入样本（已组装 FASTA）的封闭路径入口（v1.4.33）。

dry-run 验证 DAG 分支：
- FASTA 样本走 ``contigs_finalize``（用户提供 FASTA → contigs 通道），跳过 fastp/shovill；
- reads 样本照旧 fastp → shovill → contigs_finalize；
- 既无 R1/R2 也无 assembly 的样本在 DAG 构建期快速失败（明确报错）；
- 引擎侧 ``_fastqs`` 把 assembly FASTA 纳入 input_files 证据链（C4）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bacmap.workflow import runner as wf_runner


@pytest.fixture
def wf_home(tmp_path: Path, monkeypatch) -> Path:
    """部署真实包内工作流到临时 home（不触碰用户 BACMAP_HOME）。"""
    monkeypatch.setattr(wf_runner, "WORKFLOWS_DIR", tmp_path / "workflows")
    monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path)
    wf_runner.deploy()
    return tmp_path


def _write_samples(home: Path, rows: list[str]) -> None:
    (home / "workflows" / "bacmap" / "config" / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tassembly\n" + "\n".join(rows) + "\n", encoding="utf-8"
    )


def _dry(home: Path, sample: str):
    r = wf_runner.WorkflowRunner(deployed_dir=home / "workflows" / "bacmap")
    return r.dry_run([str(home / "results" / sample / "report" / f"{sample}_summary.json")])


class TestFastaEntryDag:
    def test_fasta_sample_skips_qc_and_shovill(self, wf_home: Path):
        asm_dir = wf_home / "gs" / "ASM-001"
        asm_dir.mkdir(parents=True)
        (asm_dir / "ASM-001.fasta").write_text(">c1\nACGTACGTACGT\n", encoding="utf-8")
        _write_samples(wf_home, ["ASM-001\tSalmonella\t\t\tgs/ASM-001/ASM-001.fasta"])
        proc = _dry(wf_home, "ASM-001")
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "contigs_finalize" in proc.stdout
        assert "species_identify" in proc.stdout
        assert "report_summary" in proc.stdout
        assert "qc_fastp" not in proc.stdout  # 无 reads：QC/组装不进 DAG
        assert "assembly_shovill" not in proc.stdout

    def test_reads_sample_path_unchanged(self, wf_home: Path):
        rd = wf_home / "gs" / "SAM-R1"
        rd.mkdir(parents=True)
        for r in ("R1", "R2"):
            (rd / f"SAM-R1_{r}.fastq.gz").write_bytes(b"")
        _write_samples(
            wf_home, ["SAM-R1\tSalmonella\tgs/SAM-R1/SAM-R1_R1.fastq.gz\tgs/SAM-R1/SAM-R1_R2.fastq.gz\t"]
        )
        proc = _dry(wf_home, "SAM-R1")
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "qc_fastp" in proc.stdout
        assert "assembly_shovill" in proc.stdout
        assert "contigs_finalize" in proc.stdout  # 统一 contigs 通道同样经过

    def test_sample_without_any_input_fails_fast(self, wf_home: Path):
        _write_samples(wf_home, ["BAD-1\tSalmonella\t\t\t"])
        proc = _dry(wf_home, "BAD-1")
        assert proc.returncode != 0
        assert "输入不完整" in (proc.stderr + proc.stdout)

    def test_rule_all_dag_builds_with_fasta_only_samples(self, wf_home: Path):
        """rule all 形态（手动 snakemake）：纯 fasta 样本不因 snp 群组缺 reads 断 DAG。"""
        for sid in ("ASM-A", "ASM-B"):
            d = wf_home / "gs" / sid
            d.mkdir(parents=True)
            (d / f"{sid}.fasta").write_text(">c1\nACGTACGT\n", encoding="utf-8")
        _write_samples(
            wf_home,
            [
                "ASM-A\tV_parahaemolyticus\t\t\tgs/ASM-A/ASM-A.fasta",
                "ASM-B\tV_parahaemolyticus\t\t\tgs/ASM-B/ASM-B.fasta",
            ],
        )
        r = wf_runner.WorkflowRunner(deployed_dir=wf_home / "workflows" / "bacmap")
        proc = r.dry_run()  # 无 targets → rule all
        assert proc.returncode == 0, (proc.stderr + proc.stdout)[-800:]
        assert "snp_calling" not in proc.stdout  # 无 reads 样本：SNP 群组不激活


class TestFastqsEvidenceChain:
    def test_assembly_fasta_in_input_files(self, wf_home: Path):
        from bacmap.tasks.engine.dbos_engine import _fastqs

        asm_dir = wf_home / "gs" / "ASM-001"
        asm_dir.mkdir(parents=True)
        (asm_dir / "ASM-001.fasta").write_text(">c1\nACGT\n", encoding="utf-8")
        _write_samples(wf_home, ["ASM-001\tSalmonella\t\t\tgs/ASM-001/ASM-001.fasta"])
        files = asyncio.run(asyncio.to_thread(_fastqs, wf_home, ["ASM-001"]))
        assert files == [wf_home / "gs" / "ASM-001" / "ASM-001.fasta"]
