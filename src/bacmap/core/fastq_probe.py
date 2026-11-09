"""FASTQ 测序平台探测（确定性，纯标准库）。

从 reads 的**读长分布**推断平台：ONT/PacBio 长读（中位读长 ≥1 kb、分布宽）与
Illumina 短读（<400 bp、集中）。只读每对文件的前 N 条 read（默认 2,000），
输出平台判断 + 读长统计 + 置信说明；**推断不自动改写分析路径**——检测结果作为
登记时的提示与记录，平台最终由用户/计划参数裁定（PLAN.md #4）。

判断规则（保守，宁缺勿错）：
- ``illumina``：中位 ≤400 bp 且 P90 ≤600 bp；
- ``nanopore``：中位 ≥1,000 bp；
- ``pacbio_hifi``：中位 ≥5,000 bp 且 P10 ≥1,000 bp（HiFi 读长均匀偏长）；
- ``unclear``：介于之间或样本太少（<50 条 read）——如实报告，不猜。
"""

from __future__ import annotations

import gzip
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Platform = Literal["illumina", "nanopore", "pacbio_hifi", "unclear"]

_SAMPLE_READS = 2000
_MIN_READS = 50


@dataclass(frozen=True)
class FastqProbe:
    """一个 FASTQ 文件的读长探测结果。"""

    file: str
    n_reads: int
    median_len: int
    p10_len: int
    p90_len: int
    max_len: int


def _read_lengths(path: Path, limit: int) -> list[int]:
    opener = gzip.open if path.suffix == ".gz" else open
    lengths: list[int] = []
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for i, line in enumerate(handle):
            if i % 4 != 1:  # FASTQ：每 4 行的第 2 行是序列
                continue
            lengths.append(len(line.rstrip("\n")))
            if len(lengths) >= limit:
                break
    return lengths


def probe_file(path: str | Path, *, sample_reads: int = _SAMPLE_READS) -> FastqProbe:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"fastq not found: {source}")
    lengths = sorted(_read_lengths(source, sample_reads))
    if not lengths:
        raise ValueError(f"no reads sampled from {source}")

    def pct(fraction: float) -> int:
        return lengths[min(len(lengths) - 1, int(len(lengths) * fraction))]

    return FastqProbe(
        file=str(source),
        n_reads=len(lengths),
        median_len=pct(0.5),
        p10_len=pct(0.1),
        p90_len=pct(0.9),
        max_len=lengths[-1],
    )


def classify(probe: FastqProbe) -> Platform:
    if probe.n_reads < _MIN_READS:
        return "unclear"
    if probe.median_len <= 400 and probe.p90_len <= 600:
        return "illumina"
    if probe.median_len >= 5000 and probe.p10_len >= 1000:
        return "pacbio_hifi"
    if probe.median_len >= 1000:
        return "nanopore"
    return "unclear"


_PLATFORM_NOTES = {
    "illumina": "short, uniform reads — short-read assembly/QC path",
    "nanopore": "long, broad reads — long-read-aware assembly (no built-in path yet)",
    "pacbio_hifi": "long, uniform reads — HiFi assembly (no built-in path yet)",
    "unclear": "length distribution does not match a known platform cleanly",
}


def detect_directory(
    directory: str | Path, *, sample_reads: int = _SAMPLE_READS
) -> dict:
    """探测目录下所有 FASTQ(.gz) 的平台（每文件独立统计，汇总取多数）。"""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"directory not found: {root}")
    files = sorted(
        p for p in root.iterdir()
        if (p.is_file() and p.suffix.lstrip(".").lower() in {"fastq", "fq"})
        or (p.name.lower().endswith((".fastq.gz", ".fq.gz")))
    )
    if not files:
        raise ValueError(f"no FASTQ files in {root}")
    probes = []
    for path in files:
        try:
            probes.append(probe_file(path, sample_reads=sample_reads))
        except (OSError, ValueError):
            continue  # 单文件损坏不阻断目录探测
    if not probes:
        raise ValueError(f"no readable FASTQ files in {root}")
    votes = [classify(p) for p in probes]
    # 多数票（unclear 不参与投票；全部 unclear 则如实 unclear）
    decisive = [v for v in votes if v != "unclear"]
    platform: Platform = "unclear"
    if decisive:
        counts = Counter(decisive)
        platform = counts.most_common(1)[0][0]
    return {
        "schema": "bacmap.fastq_platform/1",
        "directory": str(root),
        "n_files": len(probes),
        "platform": platform,
        "files": [
            {
                "file": Path(p.file).name,
                "n_reads": p.n_reads,
                "median_len": p.median_len,
                "p10_len": p.p10_len,
                "p90_len": p.p90_len,
                "max_len": p.max_len,
                "vote": v,
            }
            for p, v in zip(probes, votes, strict=True)
        ],
        "note": _PLATFORM_NOTES[platform],
    }
