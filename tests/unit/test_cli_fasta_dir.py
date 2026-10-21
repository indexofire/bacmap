"""``task submit --fasta-dir`` 的登记逻辑（v1.4.36）：扫描/幂等/表头自愈。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bacmap.interfaces.cli.main import _register_fasta_dir


def _seed(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.fna").write_text(">c\nACGT\n")
    (d / "nested").mkdir()
    (d / "nested" / "b.FASTA").write_text(">c\nACGT\n")
    (d / "c.fa.gz").write_bytes(b"\x1f\x8b")  # gz：不收
    (d / "readme.txt").write_text("not a genome")


def _tsv(home: Path) -> Path:
    return home / "workflows" / "bacmap" / "config" / "samples.tsv"


class TestRegisterFastaDir:
    def test_scans_recursively_and_skips_gz(self, tmp_path: Path):
        _seed(tmp_path / "data")
        home = tmp_path / "home"
        samples = _register_fasta_dir(tmp_path / "data", "VPA", home)
        assert samples == ["a", "b"]  # 排序稳定；gz/txt 不收
        rows = _tsv(home).read_text().splitlines()
        assert rows[0].split("\t") == ["sample", "species", "R1", "R2", "assembly"]
        assert any(r.startswith("b\tVPA\t\t\t") and r.endswith("b.FASTA") for r in rows)

    def test_idempotent_reuses_registered_ids(self, tmp_path: Path):
        _seed(tmp_path / "data")
        home = tmp_path / "home"
        first = _register_fasta_dir(tmp_path / "data", "VPA", home)
        second = _register_fasta_dir(tmp_path / "data", "Salmonella", home)
        assert first == second  # 已登记 ID 复用，不重写物种
        rows = [r for r in _tsv(home).read_text().splitlines()[1:] if r.strip()]
        assert len(rows) == 2  # 无重复行
        assert all("\tVPA\t" in r for r in rows)  # 首次登记的物种保留

    def test_existing_header_gains_assembly_column(self, tmp_path: Path):
        home = tmp_path / "home"
        tsv = _tsv(home)
        tsv.parent.mkdir(parents=True)
        tsv.write_text("sample\tspecies\tR1\tR2\nOLD\tSalmonella\tp\tq\n", encoding="utf-8")
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "new.fna").write_text(">c\nACGT\n")
        samples = _register_fasta_dir(tmp_path / "data", "VPA", home)
        lines = tsv.read_text().splitlines()
        assert lines[0].split("\t")[-1] == "assembly"
        assert lines[1] == "OLD\tSalmonella\tp\tq"  # 旧行原样保留
        assert samples == ["new"]

    def test_no_fasta_fails_fast(self, tmp_path: Path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(SystemExit, match="未找到组装 FASTA"):
            _register_fasta_dir(tmp_path / "empty", "VPA", tmp_path / "home")


class TestRegisterFastqDir:
    """reads 目录登记（v1.4.39）：配对识别/单端跳过/UNK 默认/幂等。"""

    def test_pairs_r_variants_and_001(self, tmp_path: Path):
        from bacmap.workflow.samples_registry import scan_fastq_pairs

        d = tmp_path / "reads"
        (d / "nested").mkdir(parents=True)
        for name in ("HZCPE-10_R1.fastq.gz", "HZCPE-10_R2.fastq.gz",
                     "sampleA_1_001.fastq", "sampleA_2_001.fastq",
                     "lonely_R1.fq.gz", "notes.txt"):
            (d / "nested" / name).write_text("x")
        pairs = scan_fastq_pairs(d)
        got = {r1.name: (r2.name if r2 else None) for r1, r2 in pairs}
        assert got["HZCPE-10_R1.fastq.gz"] == "HZCPE-10_R2.fastq.gz"
        assert got["sampleA_1_001.fastq"] == "sampleA_2_001.fastq"
        assert got["lonely_R1.fq.gz"] is None  # 未配对
        assert "notes.txt" not in got

    def test_register_defaults_unk_and_skips_single(self, tmp_path: Path):
        from bacmap.workflow.samples_registry import register_fastqs_dir

        d = tmp_path / "reads"
        d.mkdir()
        (d / "HZCPE-10_R1.fastq.gz").write_text("x")
        (d / "HZCPE-10_R2.fastq.gz").write_text("x")
        (d / "lonely_R1.fastq.gz").write_text("x")
        home = tmp_path / "home"
        report = register_fastqs_dir(home, d, "")
        assert report["samples"] == ["HZCPE-10"]
        rows = (home / "workflows/bacmap/config/samples.tsv").read_text().splitlines()
        row = rows[1].split("\t")
        assert row[0] == "HZCPE-10" and row[1] == "UNK"  # 未给物种 → UNK
        assert row[2].endswith("HZCPE-10_R1.fastq.gz") and row[3].endswith("HZCPE-10_R2.fastq.gz")
        assert report["skipped"][0]["reason"].startswith("单端")

    def test_register_explicit_species_and_idempotent(self, tmp_path: Path):
        from bacmap.workflow.samples_registry import register_fastqs_dir

        d = tmp_path / "reads"
        d.mkdir()
        (d / "A_R1.fastq.gz").write_text("x")
        (d / "A_R2.fastq.gz").write_text("x")
        home = tmp_path / "home"
        register_fastqs_dir(home, d, "Salmonella")
        report = register_fastqs_dir(home, d, "ECO")  # 二次：复用不重写
        rows = [r for r in (home / "workflows/bacmap/config/samples.tsv").read_text().splitlines()[1:] if r.strip()]
        assert len(rows) == 1 and "\tSalmonella\t" in rows[0]
        assert report["reused"] == 1


class TestDetectSpecies:
    def test_detect_maps_gside_verdict_to_code(self, tmp_path, monkeypatch):
        """真实 gside 0.1.4 原始形态：物种嵌于 methods.marker（顶层无 species）。"""
        import bacmap.workflow.samples_registry as sr

        class _P:
            returncode = 0
            stdout = json.dumps(
                {"analysis_type": "species_identification", "methods": {"marker": {
                    "species": "V_parahaemolyticus", "confidence": "high"
                }}, "verdict": None}
            )

        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _P())
        assert sr.detect_species(tmp_path / "x.fna") == "VPA"

    def test_detect_prefers_top_verdict(self, tmp_path, monkeypatch):
        import bacmap.workflow.samples_registry as sr

        class _P:
            returncode = 0
            stdout = json.dumps({"verdict": "Salmonella enterica"})

        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _P())
        assert sr.detect_species(tmp_path / "x.fna") == "SAL"

    def test_detect_unknown_returns_empty(self, tmp_path, monkeypatch):
        import bacmap.workflow.samples_registry as sr

        class _P:
            returncode = 0
            stdout = json.dumps(
                {"methods": {"marker": {"species": "Unknown"}}, "verdict": None}
            )

        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _P())
        assert sr.detect_species(tmp_path / "x.fna") == ""

    def test_detect_auto_registered_when_species_omitted(self, tmp_path, monkeypatch):
        import bacmap.workflow.samples_registry as sr

        class _P:
            returncode = 0
            stdout = json.dumps(
                {"methods": {"marker": {"species": "Salmonella enterica"}}}
            )

        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _P())
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "s1.fna").write_text(">c\nACGT\n")
        report = sr.register_fastas(tmp_path / "home", tmp_path / "data", "")
        assert report["samples"] == ["s1"] and report["detected"]["s1"] == "SAL"
