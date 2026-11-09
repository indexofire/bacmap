"""0.1.4 新增命令测试：stats / detect / species / reference / completion / ops 组 / plan 前缀 / sample 分页。"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from bacmap.core.fastq_probe import classify, detect_directory, probe_file


def _make_fastq(path: Path, read_lengths: list[int]) -> None:
    """生成 FASTQ（4 行/read），可控读长。"""
    lines: list[str] = []
    for i, length in enumerate(read_lengths):
        seq = "A" * length
        lines.append(f"@read{i}")
        lines.append(seq)
        lines.append("+")
        lines.append("I" * length)
    data = "\n".join(lines) + "\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(data.encode()))
    else:
        path.write_text(data, encoding="utf-8")


class TestFastqProbe:
    def test_illumina_short_reads(self, tmp_path: Path):
        fq = tmp_path / "sample_R1.fastq"
        _make_fastq(fq, [150] * 100)
        probe = probe_file(fq)
        assert classify(probe) == "illumina"

    def test_nanopore_long_reads(self, tmp_path: Path):
        fq = tmp_path / "sample.fastq"
        _make_fastq(fq, [2000, 3000, 2500, 4000, 1500, 3500, 2800, 2200] * 15)
        probe = probe_file(fq)
        assert classify(probe) == "nanopore"

    def test_pacbio_hifi_reads(self, tmp_path: Path):
        fq = tmp_path / "sample.fastq"
        _make_fastq(fq, [15000] * 100)
        probe = probe_file(fq)
        assert classify(probe) == "pacbio_hifi"

    def test_too_few_reads_is_unclear(self, tmp_path: Path):
        fq = tmp_path / "sample.fastq"
        _make_fastq(fq, [150] * 10)
        probe = probe_file(fq)
        assert classify(probe) == "unclear"

    def test_gzip_supported(self, tmp_path: Path):
        fq = tmp_path / "sample_R1.fastq.gz"
        _make_fastq(fq, [150] * 100)
        probe = probe_file(fq)
        assert classify(probe) == "illumina"

    def test_directory_majority_vote(self, tmp_path: Path):
        _make_fastq(tmp_path / "a_R1.fastq", [150] * 100)
        _make_fastq(tmp_path / "a_R2.fastq", [150] * 100)
        _make_fastq(tmp_path / "b.fastq", [150] * 100)
        result = detect_directory(tmp_path)
        assert result["platform"] == "illumina"
        assert result["n_files"] == 3

    def test_missing_directory_raises(self):
        with pytest.raises(FileNotFoundError):
            detect_directory("/nonexistent/fastq/dir")

    def test_empty_directory_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="no FASTQ"):
            detect_directory(tmp_path)


class TestStatsCommand:
    def test_stats_json_on_empty_home(self, tmp_path: Path):
        from bacmap.interfaces.stats_summary import gather_stats

        stats = gather_stats(tmp_path)
        assert stats["schema"] == "bacmap.stats/1"
        assert stats["tasks"]["total"] == 0
        assert stats["gom"]["genome_objects"] == 0

    def test_stats_with_real_home(self, tmp_path: Path):
        """建一个最小 home（tasks.sqlite 有表结构）验证字段存在。"""
        from bacmap.interfaces.stats_summary import gather_stats, stats_markdown
        from bacmap.tasks.engine.task_engine import DbosTaskEngine

        DbosTaskEngine(tmp_path)  # 副作用：建 tasks.sqlite 结构
        stats = gather_stats(tmp_path)
        assert stats["tasks"]["exists"] is True
        assert stats["tasks"]["total"] == 0
        md = stats_markdown(stats)
        assert "任务" in md  # markdown 包含任务统计行


class TestSpeciesCommand:
    def test_species_list_json(self, capsys):
        import argparse

        from bacmap.interfaces.cli.quickwin import run_species_ls

        args = argparse.Namespace(query="", json=True)
        run_species_ls(args)
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) > 10  # 41 物种
        codes = {r["code"] for r in rows}
        assert {"SAL", "ECO", "VPA", "LMO"} <= codes

    def test_species_list_filtered(self, capsys):
        import argparse

        from bacmap.interfaces.cli.quickwin import run_species_ls

        args = argparse.Namespace(query="VPA", json=True)
        run_species_ls(args)
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 1
        assert rows[0]["code"] == "VPA"

    def test_species_resolve(self, capsys):
        import argparse

        from bacmap.interfaces.cli.quickwin import run_species_resolve

        args = argparse.Namespace(name="V_parahaemolyticus", json=True)
        run_species_resolve(args)
        assert json.loads(capsys.readouterr().out)["code"] == "VPA"

    def test_species_resolve_unknown(self):
        import argparse

        from bacmap.interfaces.cli.quickwin import run_species_resolve

        args = argparse.Namespace(name="not_a_thing", json=True)
        with pytest.raises(SystemExit):
            run_species_resolve(args)


class TestCompletionCommand:
    def test_bash_completion(self, capsys):
        import argparse

        from bacmap.interfaces.cli.quickwin import run_completion

        run_completion(argparse.Namespace(shell="bash"))  # noqa: S604
        out = capsys.readouterr().out
        assert "complete -F _bacmap_completions bacmap" in out
        assert "stats" in out and "detect" in out and "species" in out

    def test_zsh_completion(self, capsys):
        import argparse

        from bacmap.interfaces.cli.quickwin import run_completion

        run_completion(argparse.Namespace(shell="zsh"))  # noqa: S604
        out = capsys.readouterr().out
        assert "#compdef bacmap" in out


class TestOpsGroup:
    def test_ops_subcommands_exist(self):
        from bacmap.interfaces.cli.main import build_parser

        parser = build_parser()
        # 解析 ops 子命令
        args = parser.parse_args(["ops", "doctor", "--home", "/tmp"])
        assert args.ops_command == "doctor"

    def test_ops_backup_parse(self):
        from bacmap.interfaces.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["ops", "backup", "--out", "/tmp/x.zip", "--home", "/tmp"])
        assert args.ops_command == "backup"
        assert args.out == "/tmp/x.zip"


class TestPlanPrefixResolution:
    def test_full_id_passthrough(self):
        from unittest.mock import MagicMock

        from bacmap.application.plans import PlanService
        from bacmap.interfaces.cli.plans import _resolve_plan_id

        service = MagicMock(spec=PlanService)
        assert _resolve_plan_id(service, "0123456789abcdef") == "0123456789abcdef"
