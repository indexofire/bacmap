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

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from bacmap.core.species_codes import species_code
from bacmap.tools._common import _validate_sample_id

_FASTA_EXTS = {".fna", ".fasta", ".fa"}
# `sample` 列语义 = dataset_id（历史列名保留，避免改 10 个 .smk 规则）；
# isolate/platform 为 v1.8 身份模型列；checksum 用于同名冲突检测。
_HEADER = ["sample", "species", "R1", "R2", "assembly", "isolate", "platform", "checksum"]
_IDENTITY_COLUMNS = ("isolate", "platform", "checksum")

_READ_STEMS = (".fastq.gz", ".fq.gz", ".fastq.bz2", ".fq.bz2", ".fastq", ".fq")
_MATE_PAT = re.compile(r"^(?P<prefix>.+?)[_.]?(?P<mate>R?[12])(_001)?$", re.IGNORECASE)


def parse_dataset_name(stem: str) -> tuple[str, str, str]:
    """文件名 → (dataset_id, isolate_id, platform)。

    约定 ``<isolate>__<platform>[__<date>]``；不含 ``__`` 时前两者都取 stem、platform=unknown。
    例：``HZCPE-01__ilm__20261012`` → (...,``HZCPE-01``,``ilm``)。
    """
    parts = [p for p in stem.split("__")]
    if len(parts) >= 2 and parts[0]:
        return stem, parts[0], parts[1] or "unknown"
    return stem, stem, "unknown"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _checksum(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(f"{p.name}\0{_sha256_file(p)}\n".encode())
    return h.hexdigest()


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


def _load_table(home: Path) -> tuple[Path, list[str], list[list[str]]]:
    """读 samples.tsv → (路径, 表头, 行列表)；缺失/损坏给默认表头。

    v2（5 列）自动升级为 v3（8 列）：isolate 取原 sample、platform=unknown、checksum 空。
    """
    tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    raw = tsv.read_text(encoding="utf-8").splitlines() if tsv.is_file() else []
    header = raw[0].split("\t") if raw and raw[0].split("\t")[0] == "sample" else []
    body = [ln.split("\t") for ln in raw[1:] if ln.strip()] if header else []
    if not header:
        header = list(_HEADER)
    if "assembly" not in header:  # v1.x 四列表升级
        header.append("assembly")
    for col in _IDENTITY_COLUMNS:
        if col not in header:
            header.append(col)
    rows: list[list[str]] = []
    for parts in body:
        record = dict(zip(header, parts, strict=False))
        record.setdefault("isolate", record.get("sample", ""))
        record.setdefault("platform", "unknown")
        record.setdefault("checksum", "")
        rows.append([str(record.get(col, "")) for col in header])
    return tsv, header, rows


def _save_table(tsv: Path, header: list[str], rows: list[list[str]]) -> None:
    tsv.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join("\t".join(row) for row in rows)
    tsv.write_text("\t".join(header) + "\n" + (body + "\n" if body else ""), encoding="utf-8")


def _existing(rows: list[list[str]], header: list[str], dataset_id: str) -> list[str] | None:
    idx = header.index("sample")
    for row in rows:
        if row[idx] == dataset_id:
            return row
    return None


def _guard_collision(
    existing: list[str],
    header: list[str],
    *,
    dataset_id: str,
    checksum: str,
    new_path: str,
) -> None:
    record = dict(zip(header, existing, strict=False))
    old_sum = record.get("checksum", "")
    if old_sum and checksum and old_sum != checksum:
        old_path = record.get("assembly") or record.get("R1")
        raise ValueError(
            f"dataset id collision: {dataset_id!r} already registered with different content"
            f" (existing path: {old_path}; new path: {new_path}). "
            "Rename the file or use a distinct dataset id, e.g. "
            f"{dataset_id}__<platform>__<yyyymmdd>."
        )
    if not old_sum:
        old_path = record.get("assembly") or record.get("R1")
        old_files = [Path(record[k]) for k in ("R1", "R2") if record.get(k)]
        if not old_files and record.get("assembly"):
            old_files = [Path(record["assembly"])]
        if old_files and all(p.is_file() for p in old_files):
            old_sum = _checksum(old_files)
            if old_sum != checksum:
                raise ValueError(
                    f"dataset id collision: {dataset_id!r} already registered with different "
                    f"content at {old_path} (legacy row, checksum recomputed). "
                    "Rename the file or use a distinct dataset id."
                )
        elif old_path and old_path != new_path:
            raise ValueError(
                f"dataset id collision: {dataset_id!r} is registered to {old_path}, "
                f"but this run points at {new_path}. Rename the file or use a distinct dataset id."
            )


def _ensure_isolates(home: Path, rows: list[list[str]], header: list[str]) -> None:
    """把 samples.tsv 中的 isolate 同步进 isolates 表（幂等；失败不阻断登记）。"""
    if "isolate" not in header:
        return
    from bacmap.store.isolates import IsolateService

    idx = header.index("isolate")
    try:
        with IsolateService(home / "data" / "bacmap.sqlite") as svc:
            for row in rows:
                if len(row) > idx and row[idx]:
                    svc.ensure(row[idx])
    except (OSError, ValueError):  # 注册表不可写不应让数据登记失败（登记本身已完成）
        pass


def register_fastas(
    home: Path, fasta_dir: Path, species: str = ""
) -> dict[str, Any]:
    """组装 FASTA 目录登记（assembly 列）。species 省略时逐株 gside 自动识别；
    识别失败的文件跳过并在 ``skipped`` 中列明原因。

    同名冲突策略（v1.8）：同一 dataset id 仅当内容哈希一致时幂等复用；
    路径或内容不同立即报错，绝不静默分析旧文件。
    """
    files = scan_fasta_dir(fasta_dir)
    if not files:
        raise FileNotFoundError(f"目录内未找到组装 FASTA（.fna/.fasta/.fa）：{fasta_dir}")
    tsv, header, rows = _load_table(home)

    samples: list[str] = []
    detected: dict[str, str] = {}
    skipped: list[dict[str, str]] = []
    added = 0
    for fa in files:
        sid, isolate, platform = parse_dataset_name(fa.stem)
        if not _validate_sample_id(sid):
            skipped.append(
                {
                    "file": str(fa),
                    "reason": f"非法 dataset id {sid!r}（允许 A-Za-z0-9._-，且不得为 . / ..）",
                }
            )
            continue
        sum_ = _checksum([fa])
        row = _existing(rows, header, sid)
        if row is not None:
            _guard_collision(
                row, header, dataset_id=sid, checksum=sum_, new_path=str(fa.resolve())
            )
            samples.append(sid)
            continue
        code = species or detect_species(fa)
        if not code:
            skipped.append({"file": str(fa), "reason": "物种未识别（gside Unknown/失败）"})
            continue
        detected[sid] = code
        record = {
            "sample": sid,
            "species": code,
            "R1": "",
            "R2": "",
            "assembly": str(fa.resolve()),
            "isolate": isolate,
            "platform": platform,
            "checksum": sum_,
        }
        rows.append([record.get(col, "") for col in header])
        samples.append(sid)
        added += 1

    _save_table(tsv, header, rows)
    _ensure_isolates(home, rows, header)
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
    """reads 目录登记（R1/R2 列）。无法装配前识别物种：species 省略时登记 ``UNK``。

    同名冲突策略同 ``register_fastas``：按 R1+R2 内容哈希判断。
    """
    pairs = scan_fastq_pairs(fastq_dir)
    if not pairs:
        raise FileNotFoundError(
            f"目录内未识别到 FASTQ 配对（*_R1/_R2 或 *_1/_2）：{fastq_dir}"
        )
    tsv, header, rows = _load_table(home)

    samples: list[str] = []
    skipped: list[dict[str, str]] = []
    added = 0
    for r1, r2 in pairs:
        m = _MATE_PAT.match(_strip_read_ext(r1.name))
        stem = m.group("prefix") if m else r1.stem
        sid, isolate, platform = parse_dataset_name(stem)
        if not _validate_sample_id(sid):
            skipped.append(
                {
                    "file": str(r1),
                    "reason": f"非法 dataset id {sid!r}（允许 A-Za-z0-9._-，且不得为 . / ..）",
                }
            )
            continue
        if r2 is None:
            skipped.append({"file": str(r1), "reason": "单端 reads（管线需双端配对）"})
            continue
        sum_ = _checksum([r1, r2])
        row = _existing(rows, header, sid)
        if row is not None:
            _guard_collision(
                row, header, dataset_id=sid, checksum=sum_, new_path=str(r1.resolve())
            )
            samples.append(sid)
            continue
        record = {
            "sample": sid,
            "species": species or "UNK",
            "R1": str(r1.resolve()),
            "R2": str(r2.resolve()),
            "assembly": "",
            "isolate": isolate,
            "platform": platform,
            "checksum": sum_,
        }
        rows.append([record.get(col, "") for col in header])
        samples.append(sid)
        added += 1

    _save_table(tsv, header, rows)
    _ensure_isolates(home, rows, header)
    return {
        "samples": samples,
        "added": added,
        "reused": len(samples) - added,
        "skipped": skipped,
        "detected": {},
        "samples_tsv": str(tsv),
    }
