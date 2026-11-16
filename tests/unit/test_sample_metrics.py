"""测序数据列表的组装指标（v1.10.41）：基因组大小 / contigs / GC。"""

from __future__ import annotations

from bacmap.core.analysis.assembly_qc import summary_metrics
from bacmap.interfaces.views import sample_digest

_QUAST = (
    "Assembly\t# contigs\tTotal length\tGC (%)\n"
    "assembly\t42\t5,200,000\t51.25"
)
_SEQKIT = (
    "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\n"
    "/a/S1.fasta\tFASTA\tDNA\t83\t4785352\t151\t57654.8\t470313"
)


def test_summary_metrics_prefers_contig_stats():
    metrics = summary_metrics(
        {
            "assembly_contig_stats": {
                "total_length": 5_000_000,
                "count": 10,
                "gc_mean": 50.5,
            },
            "assembly_quast": _QUAST,
        }
    )
    assert metrics == {"genome_size": 5_000_000, "contigs": 10, "gc_pct": 50.5}


def test_summary_metrics_falls_back_to_quast_and_seqkit():
    quast = summary_metrics({"assembly_quast": _QUAST})
    assert quast == {"genome_size": 5_200_000, "contigs": 42, "gc_pct": 51.25}
    # 旧运行只有 seqkit stats：有大小/数量，无 GC。
    seqkit = summary_metrics({"assembly": _SEQKIT})
    assert seqkit == {"genome_size": 4_785_352, "contigs": 83, "gc_pct": None}
    # 全缺时给 None，由界面显示 —
    assert summary_metrics({}) == {"genome_size": None, "contigs": None, "gc_pct": None}


def test_sample_digest_includes_assembly_metrics():
    digest = sample_digest(
        {"sample": "S1", "steps": {"species": {"species": "VPA"}, "assembly_quast": _QUAST}}
    )
    assert digest["sample_id"] == "S1"
    assert digest["genome_size"] == 5_200_000
    assert digest["contigs"] == 42
    assert digest["gc_pct"] == 51.25
