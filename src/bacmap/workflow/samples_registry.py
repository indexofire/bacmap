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
import logging
import re
import subprocess
from dataclasses import dataclass
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

_logger = logging.getLogger(__name__)

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
        if not isinstance(m, dict):
            continue
        name = str(m.get("species") or "").strip()
        if name:
            return name
        # ANI/mash/sourmash 走 MethodEnvelope：物种嵌在 result 里
        # （{"method": "panel", "result": {"species": ...}}），只看顶层会漏。
        nested = m.get("result")
        if isinstance(nested, dict):
            name = str(nested.get("species") or "").strip()
            if name:
                return name
    return ""


# 登记阶段的物种鉴定档位（v1.10.47）：marker 便宜但只认预设靶基因，对"表型基因
# 做物种标签"的种（如 CDI 的 tcdA/tcdB）会漏；漏了就补一档 ANI 再判，仍判不出
# 才跳过——绝不因为单档未命中就丢样本。
# 值是该档位在不同 gside 版本里的 CLI 名称（0.2.3 用 panel，0.2.4 起用 ani）。
_SPECIES_TIERS: dict[str, tuple[str, ...]] = {
    "marker": ("marker",),
    "ani": ("ani", "panel"),
}


@dataclass(frozen=True)
class SpeciesCall:
    """单株物种判定结果：``code`` 为空表示全部档位都未识别。"""

    code: str = ""
    method: str = ""
    attempts: tuple[dict[str, str], ...] = ()

    def tried(self) -> str:
        return "、".join(item.get("mode", "") for item in self.attempts)

    def summary(self) -> str:
        """逐档结论（含失败原因/ANI 命中），用于跳过原因与日志。"""
        parts: list[str] = []
        for item in self.attempts:
            text = f"{item.get('mode', '')}={item.get('species', '')}"
            extra: list[str] = []
            if item.get("error"):
                extra.append(f"error {item['error'][:60]}")
            if item.get("ani"):
                extra.append(f"ani {item['ani']}")
            if item.get("af"):
                extra.append(f"af {item['af']}")
            if extra:
                text += "(" + ", ".join(extra) + ")"
            parts.append(text)
        return "；".join(parts)


def _gside_verdict(
    fasta: Path, mode: str, timeout: int
) -> tuple[str, bool, dict[str, Any]]:
    """跑一档 gside → ``(物种名, 档位是否被接受)``。

    ``ran`` 为 False 表示该档位名不被本机 gside 接受（跨版本别名）或调用本身失败，
    调用方应改用下一个别名；``ran`` 为 True 但名字为空表示"这一档确实判不出"。
    """
    try:
        proc = subprocess.run(
            ["gside", "species", str(fasta), "--mode", mode],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", False, {}
    if proc.returncode != 0:
        return "", False, {}
    try:
        verdict = json.loads(proc.stdout)
    except ValueError:
        return "", False, {}
    if not isinstance(verdict, dict):
        return "", False, {}
    entry = (verdict.get("methods") or {}).get(mode) or {}
    name = _gside_species_name(verdict)
    if not name or name.lower() == "unknown":
        return "", True, entry if isinstance(entry, dict) else {}
    return name, True, entry if isinstance(entry, dict) else {}


def detect_species_call(
    fasta: Path, *, tiers: tuple[str, ...] = ("marker", "ani"), timeout: int = 120
) -> SpeciesCall:
    """按 ``tiers`` 逐档识别物种，返回命中的档位与全部尝试记录。"""
    attempts: list[dict[str, str]] = []
    for tier in tiers:
        for mode in _SPECIES_TIERS.get(tier, (tier,)):
            name, ran, raw_entry = _gside_verdict(fasta, mode, timeout)
            if not ran:
                # 档位名不被本机接受（0.2.3 叫 panel，0.2.4 起叫 ani）：换别名。
                attempts.append({"mode": mode, "species": "unsupported"})
                continue
            entry: dict[str, Any] = raw_entry
            attempt: dict[str, str] = {"mode": mode, "species": name or "Unknown"}
            # 单法失败/未过阈值的原因必须留痕：否则"该档没命中"和"该档根本没跑起来"
            # 在结果里长得一模一样。
            nested = entry.get("result")
            result: dict[str, Any] = nested if isinstance(nested, dict) else entry
            if entry.get("error"):
                attempt["error"] = str(entry["error"])[:160]
            elif result.get("ani") is not None:
                attempt["ani"] = f"{float(result['ani']):.2f}"
                if result.get("aligned_fraction") is not None:
                    attempt["af"] = f"{float(result['aligned_fraction']):.2f}"
            attempts.append(attempt)
            code = species_code(name) if name else ""
            if code:
                return SpeciesCall(code=code, method=mode, attempts=tuple(attempts))
            # 本档判不出 → 升下一档（gside 认得但 bacmap 无对应码也视为未命中）。
            break
    return SpeciesCall(attempts=tuple(attempts))


def detect_species(fasta: Path, timeout: int = 120) -> str:
    """gside 识别单株 → 三字母物种码；失败/未识别返回空串（兼容旧调用方）。"""
    return detect_species_call(fasta, timeout=timeout).code


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


def list_libraries(home: Path) -> list[dict[str, str]]:
    """samples.tsv → 测序数据（library）行（列名→值）；缺失/损坏返回 []。

    v1.10.27 身份模型：``sample`` 列是 library ID，``isolate``/``specimen``
    指向上层实体。Web/API 的测序数据列表与样本详情都复用本函数。
    """
    _, header, rows = _load_table(Path(home))
    return [dict(zip(header, row, strict=False)) for row in rows]


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


def _ensure_isolates(
    home: Path,
    rows: list[list[str]],
    header: list[str],
    *,
    owner_user_id: str = "",
) -> None:
    """把 samples.tsv 中的 isolate/specimen 同步进身份表（幂等；失败不阻断登记）。

    ``owner_user_id`` 只在新登记行上生效：已有样本/菌株的归属不会被后续
    登记静默改写（换归属走管理员接口）。
    """
    if "isolate" not in header:
        return
    from bacmap.store.isolates import IsolateService
    from bacmap.store.specimens import SpecimenService

    idx = header.index("isolate")
    sidx = header.index("specimen") if "specimen" in header else None
    owner = owner_user_id or None
    try:
        with (
            IsolateService(home / "data" / "bacmap.sqlite") as svc,
            SpecimenService(home / "data" / "bacmap.sqlite") as specimens,
        ):
            for row in rows:
                isolate = row[idx] if len(row) > idx else ""
                specimen = row[sidx] if sidx is not None and len(row) > sidx else ""
                if specimen:
                    specimens.ensure(specimen, owner_user_id=owner)
                if isolate:
                    svc.ensure(isolate, specimen_id=specimen or None, owner_user_id=owner)
                elif specimen:
                    # 样本级测序（mNGS/tNGS 预留）：library 直接挂样本，无 isolate。
                    specimens.ensure(specimen, owner_user_id=owner)
    except (OSError, ValueError):  # 注册表不可写不应让数据登记失败（登记本身已完成）
        pass


def isolate_links(home: Path, isolate_id: str) -> dict[str, int]:
    """菌株的关联计数（安全删除判定）：libraries/metadata/lab_results/gom/runs。"""
    counts = {"libraries": 0, "metadata": 0, "lab_results": 0, "gom": 0, "runs": 0}

    _tsv, header, rows = _load_table(home)
    if "isolate" in header:
        idx = header.index("isolate")
        counts["libraries"] = sum(
            1 for row in rows if len(row) > idx and row[idx] == isolate_id
        )

    data_db = home / "data" / "bacmap.sqlite"
    if data_db.is_file():
        from bacmap.store.lab_results import LabResultService
        from bacmap.store.strain_metadata import StrainMetadataService

        with StrainMetadataService(data_db) as meta:
            counts["metadata"] = 1 if meta.get(isolate_id) is not None else 0
        with LabResultService(data_db) as lab:
            counts["lab_results"] = len(lab.get_by_strain(isolate_id))

    gom_db = home / "gom.sqlite"
    if gom_db.is_file():
        import sqlite3

        with sqlite3.connect(f"file:{gom_db}?mode=ro", uri=True) as conn:
            n_index = conn.execute(
                "SELECT COUNT(*) FROM strain_genotype_index WHERE strain_id = ?",
                (isolate_id,),
            ).fetchone()[0]
            n_obj = conn.execute(
                "SELECT COUNT(*) FROM genome_objects WHERE strain_id = ?",
                (isolate_id,),
            ).fetchone()[0]
        counts["gom"] = int(n_index) + int(n_obj)

    runs_db = home / "runs.sqlite"
    if runs_db.is_file():
        import json
        import sqlite3

        with sqlite3.connect(f"file:{runs_db}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT strain_ids FROM analysis_runs").fetchall()
        counts["runs"] = sum(
            1 for (raw,) in rows if isolate_id in json.loads(raw or "[]")
        )
    return counts


def delete_isolate(home: Path, isolate_id: str) -> dict[str, Any]:
    """安全删除菌株（v1.10.33）：仅允许无任何关联的空菌株。

    关联包括测序数据（samples.tsv isolate 列）、元数据、化验结果、GOM 对象/
    特征索引与运行记录。有关联时抛出 ValueError 并列出原因，不删除任何数据。
    """
    from bacmap.store.isolates import IsolateService

    db = home / "data" / "bacmap.sqlite"
    with IsolateService(db) as isolates:
        if isolates.get(isolate_id) is None:
            return {"deleted": False, "isolate_id": isolate_id}
        links = isolate_links(home, isolate_id)
        blocked = {key: value for key, value in links.items() if value}
        if blocked:
            detail = ", ".join(f"{key}={value}" for key, value in blocked.items())
            raise ValueError(
                f"isolate {isolate_id!r} has linked data ({detail}); "
                "remove or archive those records first"
            )
        deleted = isolates.delete(isolate_id)
    return {"deleted": deleted, "isolate_id": isolate_id}


def delete_specimen(
    home: Path, specimen_id: str, *, force: bool = False
) -> dict[str, Any]:
    """删除样本（v1.10.27）：默认仅空样本；force 先解除关联再删。

    同步清理 ``samples.tsv`` 中该样本的 ``specimen`` 单元格（关联菌株的测序
    数据行），不删除任何菌株/测序数据/分析结果。
    """
    from bacmap.store.specimens import SpecimenService, validate_specimen_id

    if not validate_specimen_id(specimen_id):
        raise ValueError(f"invalid specimen id: {specimen_id!r}")

    tsv, header, rows = _load_table(home)
    db = home / "data" / "bacmap.sqlite"
    with SpecimenService(db) as specimens:
        result = specimens.delete(specimen_id, force=force)
    if result["deleted"]:
        from bacmap.store.lab_results import LabResultService
        from bacmap.store.specimen_metadata import SpecimenMetadataService

        with SpecimenMetadataService(db) as metadata:
            metadata.delete(specimen_id)
        with LabResultService(db) as labs:
            labs.delete_by_subject("specimen", specimen_id)

    updated_rows = 0
    if result["deleted"] and "specimen" in header:
        spec_idx = header.index("specimen")
        for row in rows:
            if len(row) > spec_idx and row[spec_idx] == specimen_id:
                row[spec_idx] = ""
                updated_rows += 1
        if updated_rows:
            _save_table(tsv, header, rows)
    return {**result, "specimen_id": specimen_id, "updated_tsv_rows": updated_rows}


def assign_specimens(  # noqa: C901 — 关联写路径集中在一处，拆分收益低于可读性损失
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
        # 结果索引也同步身份映射；否则样本/菌株页的物种与结果数会停留在旧关联。
        gom_db = home / "gom.sqlite"
        if gom_db.is_file():
            from bacmap.store.strain_index import StrainGenotypeIndex

            try:
                with StrainGenotypeIndex(gom_db) as index:
                    for row in rows:
                        key = row[id_idx] if len(row) > id_idx else ""
                        target = assignments.get(key)
                        if target is None:
                            continue
                        isolate = (
                            (
                                row[iso_idx]
                                if iso_idx is not None and len(row) > iso_idx
                                else ""
                            )
                            or (key if by == "isolate" else "")
                        )
                        if by == "dataset":
                            index.set_identity(
                                sample_id=key,
                                specimen_id=target,
                                new_isolate_id=isolate,
                            )
                        else:
                            index.set_identity(
                                isolate_id=key, specimen_id=target
                            )
            except Exception:  # 索引同步失败不应回滚已完成的关联
                _logger.warning("strain index identity sync failed", exc_info=True)
    return {
        "updated": updated,
        "specimens": sorted(used_specimens),
        "missing": sorted(set(assignments) - matched),
        "by": by,
        "tsv": str(tsv),
    }



def backfill_same_name_specimens(home: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """未关联菌株 → 同名样本回填（v1.10.34，一次性命令）。

    对 ``specimen_id`` 为空的菌株：若同名 specimen 不存在则创建（origin=backfill），
    再把 ``isolates.specimen_id`` 与 ``samples.tsv`` 的 ``specimen`` 列同步为该编号。
    幂等：已关联菌株跳过；不会改动已有样本编号。
    """
    from bacmap.store.isolates import IsolateService
    from bacmap.store.specimens import SpecimenService, validate_specimen_id

    db = home / "data" / "bacmap.sqlite"
    with IsolateService(db) as svc:
        rows = svc.list(limit=1_000_000)
    pending = [str(r["isolate_id"]) for r in rows if not r["specimen_id"]]
    invalid = [i for i in pending if not validate_specimen_id(i)]
    targets = [i for i in pending if validate_specimen_id(i)]
    if dry_run:
        return {
            "dry_run": True,
            "candidates": len(targets),
            "created": 0,
            "linked": 0,
            "updated_tsv_rows": 0,
            "skipped_invalid": invalid,
        }

    created = 0
    linked = 0
    updated_tsv_rows = 0
    # tsv 的 specimen 列应镜像 isolates.specimen_id（含本次新建与既有链接）。
    desired: dict[str, str] = {
        str(r["isolate_id"]): str(r["specimen_id"])
        for r in rows
        if r["specimen_id"]
    }
    desired.update({i: i for i in targets})
    if targets:
        with (
            IsolateService(db) as svc,
            SpecimenService(db) as specimens,
        ):
            for isolate_id in targets:
                existed = specimens.exists(isolate_id)
                specimens.ensure(
                    isolate_id,
                    origin="backfill",
                    note="same-name specimen backfill (v1.10.34)",
                )
                if not existed:
                    created += 1
                if svc.set_specimen(isolate_id, isolate_id):
                    linked += 1

    if desired:
        tsv, header, tsv_rows = _load_table(home)
        if "isolate" in header:
            if "specimen" not in header:
                header.append("specimen")
            spec_idx = header.index("specimen")
            iso_idx = header.index("isolate")
            for row in tsv_rows:
                isolate = row[iso_idx] if len(row) > iso_idx else ""
                target = desired.get(isolate)
                if not target:
                    continue
                if len(row) <= spec_idx:
                    row.extend([""] * (spec_idx + 1 - len(row)))
                if row[spec_idx] != target:
                    row[spec_idx] = target
                    updated_tsv_rows += 1
            if updated_tsv_rows:
                _save_table(tsv, header, tsv_rows)
    return {
        "created": created,
        "linked": linked,
        "updated_tsv_rows": updated_tsv_rows,
        "skipped_invalid": invalid,
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
    home: Path, fasta_dir: Path, species: str = "", *, owner_user_id: str = ""
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
    methods: dict[str, str] = {}
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
        call = SpeciesCall(code=species, method="explicit") if species else detect_species_call(fa)
        if not call.code:
            reason = (
                f"物种未识别（{call.summary()}）"
                if call.attempts
                else "物种未识别（gside 不可用）"
            )
            skipped.append({"file": str(fa), "reason": reason})
            continue
        code = call.code
        detected[sid] = code
        methods[sid] = call.method
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
    _ensure_isolates(home, rows, header, owner_user_id=owner_user_id)
    return {
        "samples": samples,
        "added": added,
        "reused": len(samples) - added,
        "skipped": skipped,
        "detected": detected,
        "detected_methods": methods,
        "samples_tsv": str(tsv),
    }


def register_fastqs_dir(
    home: Path, fastq_dir: Path, species: str = "", *, owner_user_id: str = ""
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
    _ensure_isolates(home, rows, header, owner_user_id=owner_user_id)
    return {
        "samples": samples,
        "added": added,
        "reused": len(samples) - added,
        "skipped": skipped,
        "detected": {"longread_platforms": detected_platforms},
        "samples_tsv": str(tsv),
    }
