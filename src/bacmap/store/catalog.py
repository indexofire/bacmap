"""数据目录辅助（v1.10.x）：samples.tsv → library/isolate/specimen/owner 解析。

结果索引（``gom.sqlite::strain_genotype_index``）只存分析结果；身份层级与归属
在 ``data/bacmap.sqlite``。本模块把两侧的只读映射集中在一处，避免 Web/任务层
各写一套路径解析（ADR-02：store 不依赖 interfaces/workflow）。
"""

from __future__ import annotations

import csv
import sqlite3
from functools import lru_cache
from pathlib import Path


def samples_tsv(home: Path | str) -> Path:
    return Path(home) / "workflows" / "bacmap" / "config" / "samples.tsv"


def list_libraries(home: Path | str) -> list[dict[str, str]]:
    """读取 samples.tsv（列名→值）；缺失/损坏返回 []。"""
    path = samples_tsv(home)
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return [
                {str(k): str(v or "") for k, v in row.items()}
                for row in csv.DictReader(fh, delimiter="\t")
            ]
    except (OSError, csv.Error):
        return []


@lru_cache(maxsize=4)
def _identity_map(path_s: str, mtime_ns: int, size: int) -> dict[str, tuple[str, str]]:
    """samples.tsv 的 sample → (isolate, specimen) 快照。

    以 mtime/size 作 key：登记后文件变化自动失效；ingest 逐样本调用时不再
    每次重读整张 10 万行 TSV（否则整体退化为 O(N²)）。
    """
    out: dict[str, tuple[str, str]] = {}
    try:
        with Path(path_s).open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                sample = str(row.get("sample") or "")
                if sample:
                    out[sample] = (
                        str(row.get("isolate") or sample),
                        str(row.get("specimen") or ""),
                    )
    except (OSError, csv.Error):
        return {}
    return out


def _cached_identity(home: Path | str) -> dict[str, tuple[str, str]]:
    path = samples_tsv(home)
    try:
        stat = path.stat()
    except OSError:
        return {}
    return _identity_map(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _libraries_cached(
    path_s: str, mtime_ns: int, size: int
) -> tuple[dict[str, str], ...]:
    try:
        with Path(path_s).open(encoding="utf-8", newline="") as fh:
            return tuple(
                {str(k): str(v or "") for k, v in row.items()}
                for row in csv.DictReader(fh, delimiter="\t")
            )
    except (OSError, csv.Error):
        return ()


def cached_libraries(home: Path | str) -> list[dict[str, str]]:
    """samples.tsv 的只读快照（按 mtime/size 失效），供页面列表复用。"""
    path = samples_tsv(home)
    try:
        stat = path.stat()
    except OSError:
        return []
    return list(_libraries_cached(str(path), stat.st_mtime_ns, stat.st_size))


def library_exists(home: Path | str, library_id: str) -> bool:
    """samples.tsv 是否登记了该测序数据（不触发数据迁移/写入）。"""
    return any(row.get("sample") == library_id for row in cached_libraries(home))


def library_links(home: Path | str, library_id: str) -> dict[str, str]:
    """samples.tsv 的 library → {specimen_id, isolate_id}。

    mNGS 行可以没有 isolate（只挂 specimen）；完全没有上层链接的遗留行
    回退 isolate=library_id，保持旧行为。
    """
    for row in cached_libraries(home):
        if row.get("sample") != library_id:
            continue
        isolate = str(row.get("isolate") or "")
        specimen = str(row.get("specimen") or "")
        if not isolate and not specimen:
            isolate = library_id
        return {"specimen_id": specimen, "isolate_id": isolate}
    return {"specimen_id": "", "isolate_id": ""}


def library_identity(home: Path | str, sample_id: str) -> dict[str, str]:
    """单条 library 的身份/归属：{isolate_id, specimen_id, owner_user_id}。

    归属优先级：specimen.owner_user_id > isolate.owner_user_id。
    旧库/未登记样本只有空值，调用方按"无主"处理（普通用户不可见）。
    """
    isolate_id, specimen_id = _cached_identity(home).get(sample_id, (sample_id, ""))
    owner = ""
    db = Path(home) / "data" / "bacmap.sqlite"
    if db.is_file():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                isolate = conn.execute(
                    "SELECT specimen_id, owner_user_id FROM isolates WHERE isolate_id = ?",
                    (isolate_id,),
                ).fetchone()
                if isolate is not None:
                    specimen_id = specimen_id or str(isolate["specimen_id"] or "")
                    owner = str(isolate["owner_user_id"] or "")
                if specimen_id:
                    specimen = conn.execute(
                        "SELECT owner_user_id FROM specimens WHERE specimen_id = ?",
                        (specimen_id,),
                    ).fetchone()
                    if specimen is not None and specimen["owner_user_id"]:
                        owner = str(specimen["owner_user_id"])
        except sqlite3.Error:
            pass
    if not owner:
        gom = Path(home) / "gom.sqlite"
        if gom.is_file():
            try:
                with sqlite3.connect(f"file:{gom}?mode=ro", uri=True, timeout=10) as conn:
                    row = conn.execute(
                        "SELECT owner_user_id FROM strain_genotype_index"
                        " WHERE strain_id = ?",
                        (sample_id,),
                    ).fetchone()
                    if row is not None:
                        owner = str(row[0] or "")
            except sqlite3.Error:
                pass
    return {
        "isolate_id": isolate_id,
        "specimen_id": specimen_id,
        "owner_user_id": owner,
    }


def sample_owner(home: Path | str, sample_id: str) -> str:
    return library_identity(home, sample_id)["owner_user_id"]


def owner_for_isolate(home: Path | str, isolate_id: str) -> str:
    db = Path(home) / "data" / "bacmap.sqlite"
    if not db.is_file():
        return ""
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT i.owner_user_id, i.specimen_id, s.owner_user_id AS specimen_owner"
                " FROM isolates i LEFT JOIN specimens s ON s.specimen_id = i.specimen_id"
                " WHERE i.isolate_id = ?",
                (isolate_id,),
            ).fetchone()
    except sqlite3.Error:
        return ""
    if row is None:
        return ""
    return str(row["specimen_owner"] or row["owner_user_id"] or "")


def identity_index(home: Path | str) -> dict[str, dict[str, str]]:
    """samples.tsv 的 library → 身份映射（一次性，供列表补列）。"""
    return {
        str(row.get("sample") or ""): {
            "isolate_id": str(row.get("isolate") or row.get("sample") or ""),
            "specimen_id": str(row.get("specimen") or ""),
            "species": str(row.get("species") or ""),
        }
        for row in list_libraries(home)
        if row.get("sample")
    }
