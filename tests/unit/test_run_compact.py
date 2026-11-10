"""冷产物压缩（v1.10.20）：compact/expand 幂等性与热路径保护。"""

from __future__ import annotations

from pathlib import Path

from bacmap.store.results_layout import compact_run_artifacts, expand_run_artifacts


def _make_run(run_dir: Path) -> None:
    s = run_dir / "S1"
    (s / "annotation/bakta").mkdir(parents=True)
    (s / "annotation/eggnog").mkdir(parents=True)
    (s / "assembly/quast/basic_stats").mkdir(parents=True)
    (s / "gspec").mkdir(parents=True)
    (s / "report").mkdir(parents=True)
    # 冷：Bakta 导出 / annotation.json / eggNOG 表 / quast 图表
    (s / "annotation/bakta/S1.embl").write_text("x" * 10_000)
    (s / "annotation/bakta/S1.faa").write_text("y" * 5_000)
    (s / "annotation/eggnog/S1.emapper.annotations").write_text("z" * 8_000)
    (s / "annotation/annotation.json").write_text("{" + '"f":"' + "a" * 6_000 + '"}')
    (s / "assembly/quast/report.pdf").write_bytes(b"%PDF" + b"0" * 4_000)
    (s / "assembly/quast/basic_stats/plot.svg").write_text("<svg/>")
    # 热：报告 / summary / gspec / contigs / quast 表
    (s / "report/S1_summary.json").write_text("{}")
    (s / "report/S1_report.html").write_text("<html>")
    (s / "gspec/card.json").write_text("{}")
    (s / "assembly/contigs.fasta").write_text(">c\nACGT")
    (s / "assembly/quast/report.tsv").write_text("a\tb")
    (s / "assembly/quast/transposed_report.tsv").write_text("a\tb")


class TestCompactExpand:
    def test_compact_gzips_cold_keeps_hot(self, tmp_path: Path):
        run_dir = tmp_path / "runs/t1"
        _make_run(run_dir)
        result = compact_run_artifacts(run_dir, ["S1"])
        assert result["files"] == 6  # embl/faa/annotations/annotation.json/pdf/svg
        assert result["bytes_saved"] > 30_000
        # 冷文件变 .gz
        assert (run_dir / "S1/annotation/bakta/S1.embl.gz").is_file()
        assert not (run_dir / "S1/annotation/bakta/S1.embl").exists()
        assert (run_dir / "S1/annotation/annotation.json.gz").is_file()
        # 热文件保持明文
        for hot in (
            "report/S1_summary.json",
            "report/S1_report.html",
            "gspec/card.json",
            "assembly/contigs.fasta",
            "assembly/quast/report.tsv",
            "assembly/quast/transposed_report.tsv",
        ):
            assert (run_dir / "S1" / hot).is_file(), hot

    def test_compact_idempotent(self, tmp_path: Path):
        run_dir = tmp_path / "runs/t2"
        _make_run(run_dir)
        first = compact_run_artifacts(run_dir, ["S1"])
        second = compact_run_artifacts(run_dir, ["S1"])
        assert first["files"] == 6 and second["files"] == 0

    def test_expand_restores(self, tmp_path: Path):
        run_dir = tmp_path / "runs/t3"
        _make_run(run_dir)
        compact_run_artifacts(run_dir, ["S1"])
        count = expand_run_artifacts(run_dir, ["S1"])
        assert count == 6
        assert (run_dir / "S1/annotation/bakta/S1.embl").is_file()
        assert (run_dir / "S1/annotation/bakta/S1.embl").read_text() == "x" * 10_000
        assert not (run_dir / "S1/annotation/bakta/S1.embl.gz").exists()
