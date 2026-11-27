"""Isolate 注册表（v1.8.2，I3）：菌株实体与传代谱系。

一株菌可多次测序（不同平台/批次/传代）。`isolates` 只承载**生物学实体**：
- `isolate_id`：稳定主键（dataset 通过 samples.tsv 的 isolate 列指向它）；
- `lineage_id`：同一谱系（传代实验的祖先株）；
- `passage`：代数（从 `EVO-001-P037` 这类命名自动解析，也可显式指定）。

数据集与结果仍按 dataset/run 存储：结果永不因"同一株"而混在一起。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.store.schema import ensure_data_schema

_PASSAGE_RE = re.compile(r"^(?P<lineage>.+)-P(?P<passage>\d{1,4})$", re.IGNORECASE)

ISOLATES_DDL = """
CREATE TABLE IF NOT EXISTS isolates (
    isolate_id  TEXT PRIMARY KEY,
    lineage_id  TEXT,
    passage     INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""


def parse_isolate_identity(isolate_id: str) -> tuple[str | None, int | None, str | None]:
    """`EVO-001-P037` → ("EVO-001", 37, "EVO-001")；普通株 → (None, None, None)。"""
    m = _PASSAGE_RE.match(isolate_id)
    if m is None:
        return None, None, None
    lineage = m.group("lineage")
    return lineage, int(m.group("passage")), lineage


class IsolateService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> IsolateService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def ensure(
        self,
        isolate_id: str,
        *,
        lineage_id: str | None = None,
        passage: int | None = None,
        specimen_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> None:
        """登记 isolate；已存在时不覆盖显式 lineage/passage（幂等）。

        ``specimen_id``（v1.10.27）把菌株挂到样本；为空表示外部尚未提供样本
        信息（后续可用 ``bacmap specimen import`` 补录）。
        """
        auto_lineage, auto_passage, _ = parse_isolate_identity(isolate_id)
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO isolates"
            " (isolate_id, lineage_id, passage, specimen_id, created_at, updated_at,"
            "  owner_user_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                isolate_id,
                lineage_id if lineage_id is not None else auto_lineage,
                passage if passage is not None else auto_passage,
                specimen_id or None,
                now,
                now,
                owner_user_id or None,
            ),
        )
        if specimen_id:
            # 已存在的 isolate：仅补空关联（幂等）；更换样本走显式 set_specimen。
            self._conn.execute(
                "UPDATE isolates SET specimen_id = ?, updated_at = ?"
                " WHERE isolate_id = ? AND (specimen_id IS NULL OR specimen_id = ?)",
                (specimen_id, now, isolate_id, specimen_id),
            )

    def set_specimen(self, isolate_id: str, specimen_id: str) -> bool:
        """显式设置菌株所属样本；返回是否命中该菌株。"""
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE isolates SET specimen_id = ?, updated_at = ? WHERE isolate_id = ?",
            (specimen_id, now, isolate_id),
        )
        return cur.rowcount > 0

    def set_owner(self, isolate_id: str, owner_user_id: str | None) -> bool:
        """显式改菌株归属；返回是否命中该菌株。"""
        cur = self._conn.execute(
            "UPDATE isolates SET owner_user_id = ?, updated_at = ? WHERE isolate_id = ?",
            (owner_user_id or None, datetime.now(UTC).isoformat(), isolate_id),
        )
        return cur.rowcount > 0

    def get(self, isolate_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM isolates WHERE isolate_id = ?", (isolate_id,)
        ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        limit: int = 500,
        offset: int = 0,
        *,
        query: str = "",
        owner_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _isolate_filters(query, owner_user_id)
        rows = self._conn.execute(
            f"SELECT i.* FROM isolates i LEFT JOIN specimens s"  # noqa: S608 — where 片段仅由本模块常量拼装，值参数化
            f" ON s.specimen_id = i.specimen_id{where} ORDER BY i.isolate_id LIMIT ? OFFSET ?",
            (*params, max(1, limit), max(0, offset)),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, isolate_id: str) -> bool:
        """删除 isolates 行（仅空菌株；关联检查在 workflow/samples_registry）。"""
        cur = self._conn.execute(
            "DELETE FROM isolates WHERE isolate_id = ?", (isolate_id,)
        )
        return cur.rowcount > 0

    def count(
        self, *, query: str = "", owner_user_id: str | None = None
    ) -> int:
        where, params = _isolate_filters(query, owner_user_id)
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM isolates i LEFT JOIN specimens s"  # noqa: S608 — 同上
            f" ON s.specimen_id = i.specimen_id{where}", params
        ).fetchone()
        return int(row[0]) if row else 0


def _isolate_filters(
    query: str, owner_user_id: str | None
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if owner_user_id is not None:
        clauses.append("COALESCE(s.owner_user_id, i.owner_user_id) = ?")
        params.append(owner_user_id)
    q = query.strip().lower()
    if q:
        like = f"%{q}%"
        clauses.append(
            "(LOWER(i.isolate_id) LIKE ? OR LOWER(COALESCE(i.lineage_id,'')) LIKE ?"
            " OR LOWER(COALESCE(i.specimen_id,'')) LIKE ?)"
        )
        params.extend([like, like, like])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)
