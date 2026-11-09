"""长读/混合组装规则测试（PLAN #4，0.1.5）。

覆盖：_scan_unpaired_longreads 长读检测、samples_registry 的 longread 列
登记（纯长读/混合）、samples.tsv 向后兼容（v1.x 无 longread 列自动升级）。
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from bacmap.workflow.samples_registry import (
    _HEADER,
    _load_table,
    register_fastqs_dir,
)


def _make_fastq(path: Path, read_lengths: list[int]) -> None:
    lines: list[str] = []
    for i, length in enumerate(read_lengths):
        lines.append(f"@read{i}")
        lines.append("A" * length)
        lines.append("+")
        lines.append("I" * length)
    data = "\n".join(lines) + "\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(data.encode()))
    else:
        path.write_text(data, encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    wf = tmp_path / "workflows" / "bacmap" / "config"
    wf.mkdir(parents=True)
    return tmp_path


class TestHeaderUpgrade:
    def test_header_contains_longread(self):
        assert "longread" in _HEADER
        assert _HEADER.index("longread") > _HEADER.index("R2")
        assert _HEADER.index("longread") < _HEADER.index("assembly")

    def test_old_tsv_upgraded_with_longread(self, home: Path):
        """旧版 samples.tsv（无 longread 列）自动升级，行数据对齐。"""
        tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
        # 写入旧版 8 列（无 longread）
        old_header = ["sample", "species", "R1", "R2", "assembly", "isolate", "platform", "checksum"]
        old_row = ["S1", "SAL", "/a/R1.fq", "/a/R2.fq", "", "S1", "ilm", "abc"]
        tsv.write_text(
            "\t".join(old_header) + "\n" + "\t".join(old_row) + "\n",
            encoding="utf-8",
        )
        _, header, rows = _load_table(home)
        assert "longread" in header
        # 行数据对齐：longread 在 R2 之后、assembly 之前
        lr_idx = header.index("longread")
        asm_idx = header.index("assembly")
        assert lr_idx < asm_idx
        assert rows[0][lr_idx] == ""  # 旧数据 longread 为空
        assert rows[0][asm_idx] == ""  # assembly 仍为空


class TestLongreadRegistration:
    def test_pure_longread_sample(self, home: Path, tmp_path: Path):
        """纯长读样本（无 R1/R2）→ flye 路径。"""
        fq_dir = tmp_path / "longreads"
        fq_dir.mkdir()
        _make_fastq(fq_dir / "ONT-001.fastq.gz", [3000] * 60)
        result = register_fastqs_dir(home, fq_dir, species="VPA")
        assert "ONT-001" in result["samples"]
        assert result["detected"]["longread_platforms"].get("ONT-001") == "nanopore"
        # samples.tsv 中 longread 列有值
        _, header, rows = _load_table(home)
        lr_idx = header.index("longread")
        row = next(r for r in rows if r[header.index("sample")] == "ONT-001")
        assert "ONT-001.fastq.gz" in row[lr_idx]
        assert row[header.index("R1")] == ""  # 无短读

    def test_hybrid_sample_auto_detected(self, home: Path, tmp_path: Path):
        """混合样本：短读配对 + 长读文件 → unicycler 路径。"""
        fq_dir = tmp_path / "hybrid"
        fq_dir.mkdir()
        # 短读配对（前缀一致）
        _make_fastq(fq_dir / "SAMP-001_R1.fastq.gz", [150] * 100)
        _make_fastq(fq_dir / "SAMP-001_R2.fastq.gz", [150] * 100)
        # 长读（同前缀）
        _make_fastq(fq_dir / "SAMP-001.fastq.gz", [4000] * 60)

        result = register_fastqs_dir(home, fq_dir, species="ECO")
        assert "SAMP-001" in result["samples"]
        # samples.tsv 中 R1/R2 和 longread 都有值
        _, header, rows = _load_table(home)
        row = next(r for r in rows if r[header.index("sample")] == "SAMP-001")
        assert row[header.index("R1")] != ""
        assert row[header.index("R2")] != ""
        assert row[header.index("longread")] != ""

    def test_short_read_only_unchanged(self, home: Path, tmp_path: Path):
        """纯短读样本不受影响——longread 列为空。"""
        fq_dir = tmp_path / "short"
        fq_dir.mkdir()
        _make_fastq(fq_dir / "SAMP-002_R1.fastq.gz", [150] * 100)
        _make_fastq(fq_dir / "SAMP-002_R2.fastq.gz", [150] * 100)
        result = register_fastqs_dir(home, fq_dir, species="SAL")
        assert "SAMP-002" in result["samples"]
        _, header, rows = _load_table(home)
        row = next(r for r in rows if r[header.index("sample")] == "SAMP-002")
        assert row[header.index("longread")] == ""


class TestUnpairedLongreadScan:
    def test_pacbio_hifi_detected(self, tmp_path: Path):
        from bacmap.workflow.samples_registry import _scan_unpaired_longreads

        _make_fastq(tmp_path / "PACBIO-01.fastq.gz", [15000] * 100)
        pairs = []  # 无配对
        results = _scan_unpaired_longreads(tmp_path, pairs)
        assert len(results) == 1
        assert results[0][1] == "pacbio_hifi"

    def test_short_unpaired_not_longread(self, tmp_path: Path):
        """短读未配对文件（<1kb）不误判为长读。"""
        from bacmap.workflow.samples_registry import _scan_unpaired_longreads

        _make_fastq(tmp_path / "SHORT-01.fastq.gz", [150] * 100)
        pairs = []
        results = _scan_unpaired_longreads(tmp_path, pairs)
        assert len(results) == 0  # 短读不进 longread


SAMPLES_HEADER = (
    "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform\tchecksum"
)


@pytest.fixture
def wf_home(tmp_path: Path, monkeypatch) -> Path:
    """部署真实工作流到临时 home（dry-run 不执行外部工具）。"""
    from bacmap.workflow import runner as wf_runner

    monkeypatch.setattr(wf_runner, "WORKFLOWS_DIR", tmp_path / "workflows")
    monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path)
    wf_runner.deploy()
    return tmp_path


def _write_samples(home: Path, rows: list[list[str]]) -> None:
    body = "\n".join("\t".join(row) for row in rows)
    (home / "workflows" / "bacmap" / "config" / "samples.tsv").write_text(
        SAMPLES_HEADER + "\n" + body + "\n", encoding="utf-8"
    )


def _dry(home: Path, sample: str):
    from bacmap.workflow import runner as wf_runner

    runner = wf_runner.WorkflowRunner(deployed_dir=home / "workflows" / "bacmap")
    target = str(home / "results" / sample / "report" / f"{sample}_summary.json")
    return runner.dry_run([target, "-p"])


def _command(proc, needle: str) -> str:
    return next(
        line for line in proc.stdout.splitlines()
        if line.startswith("Shell command:") and needle in line
    )


class TestAssemblyDagRouting:
    def test_longread_only_uses_flye_nano_hq_without_genome_size(
        self, wf_home: Path
    ):
        sid = "ONT-001"
        d = wf_home / "gs" / sid
        d.mkdir(parents=True)
        _make_fastq(d / f"{sid}.fastq.gz", [3000] * 60)
        _write_samples(
            wf_home,
            [[sid, "VPA", "", "", str(d / f"{sid}.fastq.gz"), "", sid, "ont", ""]],
        )
        proc = _dry(wf_home, sid)
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "assembly_flye" in proc.stdout
        assert "assembly_shovill" not in proc.stdout
        assert "assembly_unicycler" not in proc.stdout
        flye_cmd = _command(proc, "flye --nano-hq")
        assert "--genome-size" not in flye_cmd  # flye 2.9+ 自动估计

    def test_pacbio_hifi_uses_pacbio_flag(self, wf_home: Path):
        sid = "HIFI-001"
        d = wf_home / "gs" / sid
        d.mkdir(parents=True)
        _make_fastq(d / f"{sid}.fastq.gz", [15000] * 100)
        _write_samples(
            wf_home,
            [
                [sid, "VPA", "", "", str(d / f"{sid}.fastq.gz"), "", sid,
                 "pacbio_hifi", ""]
            ],
        )
        proc = _dry(wf_home, sid)
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "--pacbio-hifi" in _command(proc, "flye --pacbio-hifi")

    def test_hybrid_routes_to_unicycler(self, wf_home: Path):
        sid = "HYB-001"
        d = wf_home / "gs" / sid
        d.mkdir(parents=True)
        for mate in ("R1", "R2"):
            (d / f"{sid}_{mate}.fastq.gz").write_bytes(b"")
        lr = d / f"{sid}.fastq.gz"
        _make_fastq(lr, [4000] * 60)
        _write_samples(
            wf_home,
            [
                [sid, "VPA", str(d / f"{sid}_R1.fastq.gz"),
                 str(d / f"{sid}_R2.fastq.gz"), str(lr), "", sid, "ont", ""]
            ],
        )
        proc = _dry(wf_home, sid)
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "assembly_unicycler" in proc.stdout
        assert "assembly_flye" not in proc.stdout
        assert f"-l {lr}" in _command(proc, "unicycler")

    def test_trycycler_platform_routes_to_trycycler(self, wf_home: Path):
        sid = "TRY-001"
        d = wf_home / "gs" / sid
        d.mkdir(parents=True)
        for mate in ("R1", "R2"):
            (d / f"{sid}_{mate}.fastq.gz").write_bytes(b"")
        lr = d / f"{sid}.fastq.gz"
        _make_fastq(lr, [4000] * 60)
        _write_samples(
            wf_home,
            [
                [sid, "VPA", str(d / f"{sid}_R1.fastq.gz"),
                 str(d / f"{sid}_R2.fastq.gz"), str(lr), "", sid, "trycycler", ""]
            ],
        )
        proc = _dry(wf_home, sid)
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "assembly_trycycler" in proc.stdout
        cmd = _command(proc, "trycycler cluster")
        assert "--assemblies" in cmd and "--reads" in cmd
        assert "--min_identity 98.0" in cmd
        assert "7_final_consensus.fasta" in cmd
