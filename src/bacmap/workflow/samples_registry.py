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
# isolate/platform 为 v1.8 身份模型列；checksum 用于同名冲突检测；
# specimen（v1.10.27）为样本（送检编号），可空，后续由 `bacmap specimen import` 补录。
_HEADER = [
    "sample", "species", "R1", "R2", "longread",
    "assembly", "isolate", "platform", "checksum", "specimen",
]
_IDENTITY_COLUMNS = ("isolate", "platform", "checksum", "specimen")

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
    """递归收集组装 FASTA（.fna/.fasta/.fa，大小写不敏感；.gz 不收——下游需明文）。

    v1.10.20 链接去重：外部工具（如 shigapass）常在子目录留指向原始组装的
    符号链接（``run/x.fasta -> ../x.fna``）。同一物理文件经不同文件名会被
    复合校验和（含文件名）误判为"不同内容"的 dataset 碰撞——这里按
    ``resolve()`` 去重，每个物理文件只保留排序在前的代表路径。
    """
    files = sorted(
        p for p in fasta_dir.rglob("*") if p.is_file() and p.suffix.lower() in _FASTA_EXTS
    )
    seen: set[Path] = set()
    deduped: list[Path] = []
    for fa in files:
        real = fa.resolve()
        if real in seen:
            continue
        seen.add(real)
        deduped.append(fa)
    return deduped


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
    if "longread" not in header:  # v1.4.42 长读列（PLAN #4）
        r2_idx = header.index("R2") + 1 if "R2" in header else len(header)
        header.insert(r2_idx, "longread")
        # 同步在已有行插入空值（位置对齐）
        for parts in body:
            if len(parts) >= r2_idx:
                parts.insert(r2_idx, "")
    for col in _IDENTITY_COLUMNS:
        if col not in header:
            header.append(col)
    rows: list[list[str]] = []
    for parts in body:
        record = dict(zip(header, parts, strict=False))
        record.setdefault("isolate", record.get("sample", ""))
        record.setdefault("platform", "unknown")
        record.setdefault("checksum", "")
        record.setdefault("specimen", "")
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
    # v1.10.20 兜底：新文件 resolve 后与登记路径指向同一物理文件 → 必然同源
    # （复合校验和含文件名，同一文件的符号链接/换名副本会被误判"内容不同"）。
    old_path = record.get("assembly") or record.get("R1") or ""
    try:
        if old_path and Path(new_path).resolve() == Path(old_path).resolve():
            return
    except OSError:
        pass
    old_sum = record.get("checksum", "")
    if old_sum and checksum and old_sum != checksum:
        old_path = record.get("assembly") or record.get("R1") or ""
        raise ValueError(
            f"dataset id collision: {dataset_id!r} already registered with different content"
            f" (existing path: {old_path}; new path: {new_path}). "
            "Rename the file or use a distinct dataset id, e.g. "
            f"{dataset_id}__<platform>__<yyyymmdd>."
        )
    if not old_sum:
        old_path = record.get("assembly") or record.get("R1") or ""
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
    """把 samples.tsv 中的 isolate/specimen 同步进身份表（幂等；失败不阻断登记）。"""
    if "isolate" not in header:
        return
    from bacmap.store.isolates import IsolateService
    from bacmap.store.specimens import SpecimenService

    idx = header.index("isolate")
    sidx = header.index("specimen") if "specimen" in header else None
    try:
        with (
            IsolateService(home / "data" / "bacmap.sqlite") as svc,
            SpecimenService(home / "data" / "bacmap.sqlite") as specimens,
        ):
            for row in rows:
                isolate = row[idx] if len(row) > idx else ""
                specimen = row[sidx] if sidx is not None and len(row) > sidx else ""
                if specimen:
                    specimens.ensure(specimen)
                if isolate:
                    svc.ensure(isolate, specimen_id=specimen or None)
                elif specimen:
                    # 样本级测序（mNGS/tNGS 预留）：library 直接挂样本，无 isolate。
                    specimens.ensure(specimen)
    except (OSError, ValueError):  # 注册表不可写不应让数据登记失败（登记本身已完成）
        pass


def assign_specimens(
    home: Path,
    assignments: dict[str, str],
    *,
    by: str = "dataset",
    origin: str = "import",
) -> dict[str, Any]:
    """把已有登记数据关联到样本（v1.10.27，导入/补录入口）。

    ``assignments``: ``{标识: specimen_id}``；``by="dataset"`` 时标识是
    samples.tsv 的 sample 列（library/dataset id），``by="isolate"`` 时是菌株 ID。
    同时更新 samples.tsv 的 specimen 列、isolates.specimen_id 与 specimens 表；
    返回 ``{"updated": n, "specimens": [...], "missing": [...]}``。
    """
    from bacmap.store.isolates import IsolateService
    from bacmap.store.specimens import SpecimenService, validate_specimen_id

    if by not in ("dataset", "isolate"):
        raise ValueError("by must be 'dataset' or 'isolate'")
    for specimen in assignments.values():
        if not validate_specimen_id(specimen):
            raise ValueError(f"invalid specimen id: {specimen!r}")

    tsv, header, rows = _load_table(home)
    if "specimen" not in header:
        header.append("specimen")
    spec_idx = header.index("specimen")
    id_idx = header.index("sample" if by == "dataset" else "isolate")
    iso_idx = header.index("isolate") if "isolate" in header else None

    updated = 0
    matched: set[str] = set()
    used_specimens: set[str] = set()
    for row in rows:
        key = row[id_idx] if len(row) > id_idx else ""
        target = assignments.get(key)
        if target is None:
            continue
        matched.add(key)
        if len(row) <= spec_idx:
            row.extend([""] * (spec_idx + 1 - len(row)))
        row[spec_idx] = target
        updated += 1
        used_specimens.add(target)

    with (
        IsolateService(home / "data" / "bacmap.sqlite") as svc,
        SpecimenService(home / "data" / "bacmap.sqlite") as specimens,
    ):
        for specimen in used_specimens:
            specimens.ensure(specimen, origin=origin)
        for row in rows:
            key = row[id_idx] if len(row) > id_idx else ""
            target = assignments.get(key)
            if target is None:
                continue
            isolate = (
                (row[iso_idx] if iso_idx is not None and len(row) > iso_idx else "")
                or (key if by == "isolate" else "")
            )
            if isolate:
                svc.ensure(isolate, specimen_id=target)
                svc.set_specimen(isolate, target)
    if updated:
        _save_table(tsv, header, rows)
    return {
        "updated": updated,
        "specimens": sorted(used_specimens),
        "missing": sorted(set(assignments) - matched),
        "by": by,
        "tsv": str(tsv),
    }



def _scan_unpaired_longreads(
    fastq_dir: Path, pairs: list[tuple[Path, Path | None]]
) -> list[tuple[Path, str]]:
    """识别长读 FASTQ（读长≥1kb），返回 (path, platform) 列表。

    排除已配对（R1+R2 都有）的文件；单端 "R1"（无 R2）也参与探测——
    文件名尾部数字（如 ONT-001）会被 _MATE_PAT 误判为 mate 标记，
    但读长探测（≥1kb）能正确区分长读与真正的单端短读。
    """
    from bacmap.core.fastq_probe import classify, probe_file

    paired = set()
    for r1, r2 in pairs:
        if r2 is not None:
            paired.add(r1.resolve())
            paired.add(r2.resolve())
        else:
            # 单端（无 R2）：不排除，可能是长读（文件名误匹配 mate 模式）
            pass

    results: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for p in sorted(fastq_dir.rglob("*")):
        if not p.is_file() or p.resolve() in paired or p.resolve() in seen:
            continue
        if ".fastq" not in p.name.lower() and ".fq" not in p.name.lower():
            continue
        seen.add(p.resolve())
        try:
            probe = probe_file(p, sample_reads=200)
            if probe.median_len >= 1000:
                platform = classify(probe)
                if platform in ("nanopore", "pacbio_hifi"):
                    results.append((p, platform))
        except (OSError, ValueError):
            continue
    return results

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
            "longread": "",
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
    """reads 目录登记（R1/R2 列 + 长读自动检测→longread 列）。

    短读配对→R1/R2；未配对且读长≥1kb→longread（PLAN #4 flye/unicycler 路径）。

    同名冲突策略同 ``register_fastas``：按 R1+R2 内容哈希判断。
    """
    pairs = scan_fastq_pairs(fastq_dir)
    # 长读检测放在早退之前：纯长读目录（无 R1/R2 配对）也合法
    longreads = _scan_unpaired_longreads(fastq_dir, pairs)
    if not pairs and not longreads:
        raise FileNotFoundError(
            f"目录内未识别到 FASTQ 配对（*_R1/_R2 或 *_1/_2）或长读文件：{fastq_dir}"
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
            "longread": "",
            "assembly": "",
            "isolate": isolate,
            "platform": platform,
            "checksum": sum_,
        }
        rows.append([record.get(col, "") for col in header])
        samples.append(sid)
        added += 1

    # 长读登记（PLAN #4：_scan_unpaired_longreads 已在上方调用）
    detected_platforms: dict[str, str] = {}
    for lr_path, lr_platform in longreads:
        stem = _strip_read_ext(lr_path.name)
        sid, isolate, _ = parse_dataset_name(stem)
        if not _validate_sample_id(sid):
            skipped.append({"file": str(lr_path), "reason": f"非法 dataset id {sid!r}"})
            continue
        detected_platforms[sid] = lr_platform
        sum_ = _checksum([lr_path])
        row = _existing(rows, header, sid)
        if row is not None:
            # 已有短读记录 → 填充 longread 列（混合组装 unicycler 路径）
            lr_idx = header.index("longread") if "longread" in header else -1
            if lr_idx >= 0:
                row[lr_idx] = str(lr_path.resolve())
            samples.append(sid)
            continue
        # 纯长读样本（flye 路径）
        record = {
            "sample": sid,
            "species": species or "UNK",
            "R1": "",
            "R2": "",
            "longread": str(lr_path.resolve()),
            "assembly": "",
            "isolate": isolate,
            "platform": lr_platform,
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
        "detected": {"longread_platforms": detected_platforms},
        "samples_tsv": str(tsv),
    }
