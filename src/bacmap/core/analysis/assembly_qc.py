"""描述性组装统计（v1.10.28）。

数据来源是外部工具 **seqkit**（``fx2tab -n -l -g``）的逐 contig 长度/GC；
bacmap 只做聚合与呈现（Nx 曲线、长度/GC 直方图），不产生生物学判定
（ADR-20）。旧运行没有 ``contig_stats.tsv`` 时，读取已存在的 FASTA 仅做
只读回退（长度/GC 计数），不改变任何分析结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# 逐 contig 长度分布（左闭右开；最后一箱无上界）
LENGTH_BINS: list[tuple[int, int | None, str]] = [
    (0, 1_000, "<1 kb"),
    (1_000, 5_000, "1–5 kb"),
    (5_000, 10_000, "5–10 kb"),
    (10_000, 25_000, "10–25 kb"),
    (25_000, 50_000, "25–50 kb"),
    (50_000, 100_000, "50–100 kb"),
    (100_000, 250_000, "100–250 kb"),
    (250_000, 500_000, "250–500 kb"),
    (500_000, 1_000_000, "500 kb–1 Mb"),
    (1_000_000, None, "≥ 1 Mb"),
]

GC_BINS: list[tuple[float, float, str]] = [
    (0, 30, "<30%"),
    (30, 35, "30–35%"),
    (35, 40, "35–40%"),
    (40, 45, "40–45%"),
    (45, 50, "45–50%"),
    (50, 55, "50–55%"),
    (55, 60, "55–60%"),
    (60, 101, "≥60%"),
]


def summarize(contigs: list[tuple[str, int, float | None]]) -> dict[str, Any]:
    """[(name, length, gc_pct)] → Nx 曲线、长度/GC 直方图与汇总指标。"""
    rows = [(name, length, gc) for name, length, gc in contigs if length > 0]
    if not rows:
        return {}
    lengths = sorted((length for _name, length, _gc in rows), reverse=True)
    total = sum(lengths)

    def nx(x: int) -> tuple[int, int]:
        target = total * x / 100
        acc = 0
        for index, length in enumerate(lengths, 1):
            acc += length
            if acc >= target:
                return length, index
        return lengths[-1], len(lengths)

    n50, l50 = nx(50)
    n75, l75 = nx(75)
    n90, l90 = nx(90)

    length_bins: list[dict[str, Any]] = []
    for low, high, label in LENGTH_BINS:
        members = [L for L in lengths if low <= L and (high is None or high > L)]
        length_bins.append(
            {"label": label, "count": len(members), "bp": sum(members)}
        )

    gc_values: list[tuple[float, int]] = [
        (gc, length) for _name, length, gc in rows if gc is not None
    ]
    gc_bins: list[dict[str, Any]] = []
    for gc_low, gc_high, gc_label in GC_BINS:
        gc_members = [(gc, L) for gc, L in gc_values if gc_low <= gc < gc_high]
        gc_bins.append(
            {
                "label": gc_label,
                "count": len(gc_members),
                "bp": sum(L for _gc, L in gc_members),
            }
        )
    gc_bases = sum(L for _gc, L in gc_values)
    gc_mean = (
        round(sum(gc * L for gc, L in gc_values) / gc_bases, 2) if gc_bases else None
    )

    top = sorted(rows, key=lambda item: item[1], reverse=True)[:8]
    return {
        "source": "seqkit fx2tab",
        "count": len(rows),
        "total_length": total,
        "largest": lengths[0],
        "n50": n50,
        "l50": l50,
        "n75": n75,
        "l75": l75,
        "n90": n90,
        "l90": l90,
        "gc_mean": gc_mean,
        "length_bins": length_bins,
        "gc_bins": gc_bins,
        "nx": [{"x": x, "length": nx(x)[0]} for x in range(0, 101, 5)],
        "top_contigs": [
            {
                "name": (name.split()[0] if name else ""),
                "length": length,
                "gc": round(gc, 2) if gc is not None else None,
            }
            for name, length, gc in top
        ],
    }


def from_seqkit_tsv(path: Path | str) -> dict[str, Any]:
    """``seqkit fx2tab -n -l -g -H``（#name/length/GC）→ 统计块。"""
    try:
        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return {}
    contigs: list[tuple[str, int, float | None]] = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) < 3:
            continue
        try:
            length = int(float(cells[1].replace(",", "")))
        except ValueError:
            continue
        if length <= 0:
            continue
        try:
            gc = float(cells[2]) * 100.0
        except ValueError:
            gc = None
        contigs.append((cells[0], length, gc))
    return summarize(contigs)


def from_fasta(path: Path | str) -> dict[str, Any]:
    """旧运行回退：从 FASTA 统计逐 contig 长度与 GC（只读、描述性）。"""
    path = Path(path)
    contigs: list[tuple[str, int, float | None]] = []
    name = ""
    length = 0
    gc_bases = 0
    atgc = 0
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return {}
    with handle:
        for line in handle:
            if line.startswith(">"):
                if name and length:
                    gc_pct = 100.0 * gc_bases / atgc if atgc else None
                    contigs.append((name, length, gc_pct))
                name = line[1:].strip()
                length = gc_bases = atgc = 0
                continue
            seq = line.strip().upper()
            if not seq:
                continue
            length += len(seq)
            gc_bases += seq.count("G") + seq.count("C")
            atgc += seq.count("G") + seq.count("C") + seq.count("A") + seq.count("T")
    if name and length:
        gc_pct = 100.0 * gc_bases / atgc if atgc else None
        contigs.append((name, length, gc_pct))
    return summarize(contigs)


def load(sample_dir: Path) -> dict[str, Any]:
    """优先 seqkit TSV，旧运行回退 assembly 目录内的 FASTA。"""
    assembly = sample_dir / "assembly"
    stats = from_seqkit_tsv(assembly / "contig_stats.tsv")
    if stats:
        return stats
    candidates = sorted(assembly.glob("*.fasta")) + sorted(assembly.glob("*.fa"))
    for path in candidates:
        stats = from_fasta(path)
        if stats:
            return stats
    return {}
