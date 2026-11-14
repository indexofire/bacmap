"""描述性组装统计（v1.10.28）：seqkit TSV / FASTA 回退 → Nx 与直方图。"""

from __future__ import annotations

from pathlib import Path

from bacmap.core.analysis.assembly_qc import (
    from_fasta,
    from_seqkit_tsv,
    is_usable,
    load,
    summarize,
)


def test_summarize_nx_and_bins():
    stats = summarize(
        [("c1", 100_000, 50.0), ("c2", 50_000, 50.0), ("c3", 10_000, 40.0)]
    )
    assert stats["total_length"] == 160_000
    assert (stats["n50"], stats["l50"]) == (100_000, 1)
    assert (stats["n75"], stats["l75"]) == (50_000, 2)
    assert (stats["n90"], stats["l90"]) == (50_000, 2)
    assert stats["gc_mean"] == 49.38
    assert stats["nx"][0] == {"x": 0, "length": 100_000}
    ten_k = next(b for b in stats["length_bins"] if b["label"] == "10–25 kb")
    assert ten_k == {"label": "10–25 kb", "count": 1, "bp": 10_000}
    assert stats["top_contigs"][0]["name"] == "c1"


def test_from_seqkit_tsv(tmp_path: Path):
    path = tmp_path / "contig_stats.tsv"
    path.write_text(
        "#name\tlength\tGC\ncontig1\t2000\t50.0\ncontig2\t1000\t40.0\n",
        encoding="utf-8",
    )
    stats = from_seqkit_tsv(path)
    assert stats["count"] == 2
    assert stats["total_length"] == 3000
    assert stats["gc_mean"] == 46.67
    # seqkit -g 已经是百分数：不能再乘 100（回归 v1.10.29 的 4538% bug）
    path.write_text("#name\tlength\tGC\ncontig1\t1000\t45.0\n", encoding="utf-8")
    assert from_seqkit_tsv(path)["gc_mean"] == 45.0


def test_from_fasta_fallback_and_load(tmp_path: Path):
    assembly = tmp_path / "assembly"
    assembly.mkdir()
    fasta = assembly / "S1.fasta"
    fasta.write_text(">c1\nGGCCAATT\n>c2\nGGGGCCCC\n", encoding="utf-8")
    stats = from_fasta(fasta)
    assert stats["count"] == 2
    assert stats["largest"] == 8
    assert stats["gc_mean"] == 75.0
    assert load(tmp_path)["total_length"] == 16

    # seqkit TSV 优先于 FASTA
    (assembly / "contig_stats.tsv").write_text(
        "#name\tlength\tGC\nx\t100\t0.5\n", encoding="utf-8"
    )
    assert load(tmp_path)["total_length"] == 100


def test_empty_inputs():
    assert summarize([]) == {}
    assert from_seqkit_tsv(Path("/nonexistent/x.tsv")) == {}
    assert from_fasta(Path("/nonexistent/x.fasta")) == {}
    assert load(Path("/nonexistent")) == {}

def test_is_usable_rejects_old_multiplied_gc():
    assert is_usable({"gc_mean": 45.3})
    assert is_usable({"gc_mean": None})
    assert not is_usable({"gc_mean": 4530.0})
    assert not is_usable({})
