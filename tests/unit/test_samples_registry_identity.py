"""身份与登记冲突（v1.8 I1）：dataset/isolate 命名 + 内容哈希去重。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.workflow.samples_registry import (
    parse_dataset_name,
    register_fastas,
    register_fastqs_dir,
)


def _tsv(home: Path) -> list[list[str]]:
    p = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    return [ln.split("\t") for ln in p.read_text().splitlines() if ln.strip()]


class TestDatasetName:
    def test_plain_stem_is_dataset_and_isolate(self):
        assert parse_dataset_name("HZCPE-01") == ("HZCPE-01", "HZCPE-01", "unknown")

    def test_double_underscore_encodes_isolate_and_platform(self):
        assert parse_dataset_name("HZCPE-01__ilm__20261012") == (
            "HZCPE-01__ilm__20261012",
            "HZCPE-01",
            "ilm",
        )
        assert parse_dataset_name("EVO-001-P037__ont") == ("EVO-001-P037__ont", "EVO-001-P037", "ont")

    def test_empty_isolate_falls_back_to_stem(self):
        assert parse_dataset_name("__ilm")[1] == "__ilm"


class TestCollision:
    def test_same_content_is_idempotent(self, tmp_path: Path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "S1.fna").write_text(">c\nACGT\n")
        home = tmp_path / "home"
        first = register_fastas(home, d, "VPA")
        second = register_fastas(home, d, "VPA")
        assert first["added"] == 1 and second["added"] == 0 and second["reused"] == 1

    def test_same_id_different_content_fails_loudly(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "S1.fna").write_text(">c\nACGT\n")
        (b / "S1.fna").write_text(">c\nTTTT\n")
        home = tmp_path / "home"
        register_fastas(home, a, "VPA")
        with pytest.raises(ValueError, match="dataset id collision"):
            register_fastas(home, b, "VPA")

    def test_isolate_and_platform_recorded(self, tmp_path: Path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "HZCPE-01__ilm__20261012.fna").write_text(">c\nACGT\n")
        home = tmp_path / "home"
        register_fastas(home, d, "VPA")
        rows = _tsv(home)
        header, row = rows[0], rows[1]
        assert header[:5] == ["sample", "species", "R1", "R2", "assembly"]
        record = dict(zip(header, row, strict=False))
        assert record["sample"] == "HZCPE-01__ilm__20261012"
        assert record["isolate"] == "HZCPE-01" and record["platform"] == "ilm"
        assert len(record["checksum"]) >= 16

    def test_legacy_v2_table_is_upgraded(self, tmp_path: Path):
        home = tmp_path / "home"
        tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
        tsv.parent.mkdir(parents=True)
        tsv.write_text("sample\tspecies\tR1\tR2\tassembly\nOLD\tSAL\tp\tq\told.fna\n")
        d = tmp_path / "data"
        d.mkdir()
        (d / "new.fna").write_text(">c\nACGT\n")
        register_fastas(home, d, "VPA")
        header = _tsv(home)[0]
        assert {"isolate", "platform", "checksum"} <= set(header)
        old = dict(zip(header, _tsv(home)[1], strict=False))
        assert old["isolate"] == "OLD" and old["platform"] == "unknown"

    def test_fastq_pair_checksum_and_collision(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        for d in (a, b):
            (d / "P1__ilm_R1.fastq.gz").write_text("ACGT")
            (d / "P1__ilm_R2.fastq.gz").write_text("TGCA")
        home = tmp_path / "home"
        r1 = register_fastqs_dir(home, a, "UNK")
        assert r1["samples"] == ["P1__ilm"]
        # 同内容：幂等
        assert register_fastqs_dir(home, a, "UNK")["added"] == 0
        # 改 R2 内容：同 id 不同内容 → 报错
        (b / "P1__ilm_R2.fastq.gz").write_text("CCCC")
        with pytest.raises(ValueError, match="dataset id collision"):
            register_fastqs_dir(home, b, "UNK")
