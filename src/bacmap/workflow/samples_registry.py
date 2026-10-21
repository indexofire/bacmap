"""样本登记（v1.4.38/39）：组装 FASTA 与 reads FASTQ → samples.tsv。

- CLI ``task submit --fasta-dir/--fastq-dir``（同步登记，即时反馈）与引擎 ``analyze``
  参数 ``fasta_dir``/``fastq_dir``（任务内登记，写操作经由任务引擎，助手可直接规划）
  共用本模块；
- FASTA：``species`` 省略时逐株 ``gside species --mode marker`` 自动识别并落码；
  FASTQ：无法装配前识别物种，``species`` 省略时登记为 ``UNK``（gside 在管线内鉴定，
  物种特异分型不路由——需要血清型/DEC 时请显式给 species）；
- 幂等：已登记样本 ID 复用；samples.tsv 缺失时按标准表头新建。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from bacmap.core.species_codes import species_code

_FASTA_EXTS = {".fna", ".fasta", ".fa"}
_HEADER = ["sample", "species", "R1", "R2", "assembly"]

_READ_STEMS = (".fastq.gz", ".fq.gz", ".fastq.bz2", ".fq.bz2", ".fastq", ".fq")
_MATE_PAT = re.compile(r"^(?P<prefix>.+?)[_.]?(?P<mate>R?[12])(_001)?$", re.IGNORECASE)


def _strip_read_ext(name: str) -> str:
    for ext in _READ_STEMS:
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def scan_fasta_dir(fasta_dir: Path) -> list[Path]:
    """递归收集组装 FASTA（.fna/.fasta/.fa，大小写不敏感；.gz 不收——下游需明文）。"""
    return sorted(
        p for p in fasta_dir.rglob("*") if p.is_file() and p.suffix.lower() in _FASTA_EXTS
    )


def scan_fastq_pairs(fastq_dir: Path) -> list[tuple[Path, Path | None]]:
    """递归识别 reads 配对（``*_R1/_R2``、``*_1/_2``，含 ``_001`` 变体，大小写不敏感）。

    以（父目录|前缀）为键配对；返回 (R1, R2) 列表，未配对的 R1 其 R2 为 None。
    """
    r1s: dict[str, Path] = {}
    r2s: dict[str, Path] = {}
    for p in sorted(fastq_dir.rglob("*")):
        if not p.is_file() or (
            ".fastq" not in p.name.lower() and ".fq" not in p.name.lower()
        ):
            continue
        stem = _strip_read_ext(p.name)
        m = _MATE_PAT.match(stem)
        if not m:
            continue
        key = f"{p.parent}|{m.group('prefix')}"
        if m.group("mate").upper() in ("R1", "1"):
            r1s[key] = p
        else:
            r2s[key] = p
    return [(r1s[k], r2s.get(k)) for k in sorted(r1s)]


def _gside_species_name(verdict: dict[str, Any]) -> str:
    """从 gside 原始 JSON 提取物种名：顶层 ``verdict``（多法仲裁）优先，
    回退 ``methods.<mode>.species``（单法运行时物种嵌在此层）。"""
    top = verdict.get("verdict")
    if isinstance(top, str) and top.strip():
        return top.strip()
    if isinstance(top, dict):
        name = str(top.get("species") or "").strip()
        if name:
            return name
    for m in (verdict.get("methods") or {}).values():
        if isinstance(m, dict):
            name = str(m.get("species") or "").strip()
            if name:
                return name
    return ""


def detect_species(fasta: Path, timeout: int = 120) -> str:
    """gside marker 档识别单株 → 三字母物种码；失败/未识别返回空串。"""
    try:
        proc = subprocess.run(
            ["gside", "species", str(fasta), "--mode", "marker"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    try:
        verdict = json.loads(proc.stdout)
    except ValueError:
        return ""
    name = _gside_species_name(verdict if isinstance(verdict, dict) else {})
    if not name or name.lower() == "unknown":
        return ""
    return species_code(name) or ""


def _load_table(home: Path) -> tuple[Path, list[str], list[str]]:
    """读 samples.tsv → (路径, 表头列, 数据行)；缺失/损坏时给默认表头与空行。"""
    tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    lines = tsv.read_text(encoding="utf-8").splitlines() if tsv.is_file() else []
    header = lines[0].split("\t") if lines and lines[0].split("\t")[0] == "sample" else []
    rows = [ln for ln in lines[1:] if ln.strip()] if header else []
    if not header:
        header = list(_HEADER)
    if header[-1] != "assembly":
        header = [*header[:4], "assembly"] if len(header) >= 4 else [*header, "assembly"]
    return tsv, header, rows


def _save_table(tsv: Path, header: list[str], rows: list[str]) -> None:
    tsv.parent.mkdir(parents=True, exist_ok=True)
    tsv.write_text("\t".join(header) + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def register_fastas(
    home: Path, fasta_dir: Path, species: str = ""
) -> dict[str, Any]:
    """组装 FASTA 目录登记（assembly 列）。species 省略时逐株 gside 自动识别；
    识别失败的文件跳过并在 ``skipped`` 中列明原因。"""
    files = scan_fasta_dir(fasta_dir)
    if not files:
        raise FileNotFoundError(f"目录内未找到组装 FASTA（.fna/.fasta/.fa）：{fasta_dir}")
    tsv, header, rows = _load_table(home)
    known = {r.split("\t", 1)[0] for r in rows}

    samples: list[str] = []
    detected: dict[str, str] = {}
    skipped: list[dict[str, str]] = []
    added = 0
    for fa in files:
        sid = fa.stem
        if sid in known:
            samples.append(sid)
            continue
        code = species or detect_species(fa)
        if not code:
            skipped.append({"file": str(fa), "reason": "物种未识别（gside Unknown/失败）"})
            continue
        detected[sid] = code
        rows.append(f"{sid}\t{code}\t\t\t{fa.resolve()}")
        known.add(sid)
        samples.append(sid)
        added += 1

    _save_table(tsv, header, rows)
    return {
        "samples": samples,
        "added": added,
        "reused": len(samples) - added,
        "skipped": skipped,
        "detected": detected,
        "samples_tsv": str(tsv),
    }


def register_fastqs_dir(
    home: Path, fastq_dir: Path, species: str = ""
) -> dict[str, Any]:
    """reads 目录登记（R1/R2 列）。无法装配前识别物种：species 省略时登记 ``UNK``。"""
    pairs = scan_fastq_pairs(fastq_dir)
    if not pairs:
        raise FileNotFoundError(
            f"目录内未识别到 FASTQ 配对（*_R1/_R2 或 *_1/_2）：{fastq_dir}"
        )
    tsv, header, rows = _load_table(home)
    known = {r.split("\t", 1)[0] for r in rows}

    samples: list[str] = []
    skipped: list[dict[str, str]] = []
    added = 0
    for r1, r2 in pairs:
        m = _MATE_PAT.match(_strip_read_ext(r1.name))
        sid = m.group("prefix") if m else r1.stem
        if sid in known:
            samples.append(sid)
            continue
        if r2 is None:
            skipped.append({"file": str(r1), "reason": "单端 reads（管线需双端配对）"})
            continue
        rows.append(f"{sid}\t{species or 'UNK'}\t{r1.resolve()}\t{r2.resolve()}\t")
        known.add(sid)
        samples.append(sid)
        added += 1

    _save_table(tsv, header, rows)
    return {
        "samples": samples,
        "added": added,
        "reused": len(samples) - added,
        "skipped": skipped,
        "detected": {},
        "samples_tsv": str(tsv),
    }
