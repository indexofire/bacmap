"""测序数据（library）级元数据（v1.10.52）。

一个菌株可有多份测序数据；mNGS library 只挂 specimen。library_id 对应
``samples.tsv`` 的 ``sample`` 列；本表只存附加元数据，不替代 samples.tsv。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.store.schema import ensure_data_schema

DDL_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS library_metadata (
        library_id TEXT PRIMARY KEY,
        specimen_id TEXT,
        isolate_id  TEXT,
        data_json   TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_library_meta_specimen"
    " ON library_metadata(specimen_id)",
    "CREATE INDEX IF NOT EXISTS idx_library_meta_isolate"
    " ON library_metadata(isolate_id)",
)


class LibraryMetadataService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> LibraryMetadataService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, library_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM library_metadata WHERE library_id = ?", (library_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(str(row["data_json"] or "{}"))
        except ValueError:
            data = {}
        return {
            "library_id": str(row["library_id"]),
            "specimen_id": str(row["specimen_id"] or ""),
            "isolate_id": str(row["isolate_id"] or ""),
            "data": data if isinstance(data, dict) else {},
        }

    def upsert(
        self,
        library_id: str,
        data: dict[str, Any],
        *,
        specimen_id: str = "",
        isolate_id: str = "",
        replace: bool = False,
    ) -> dict[str, Any]:
        if not library_id:
            raise ValueError("library_id is required")
        existing = self.get(library_id)
        merged = (
            dict(data)
            if replace
            else {**((existing or {}).get("data") or {}), **data}
        )
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO library_metadata"
            " (library_id, specimen_id, isolate_id, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(library_id) DO UPDATE SET"
            " specimen_id=excluded.specimen_id, isolate_id=excluded.isolate_id,"
            " data_json=excluded.data_json, updated_at=excluded.updated_at",
            (
                library_id,
                specimen_id or None,
                isolate_id or None,
                json.dumps(merged, ensure_ascii=False),
                now,
                now,
            ),
        )
        return {
            "library_id": library_id,
            "specimen_id": specimen_id,
            "isolate_id": isolate_id,
            "data": merged,
        }

    def delete(self, library_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM library_metadata WHERE library_id = ?", (library_id,)
        )
        return cur.rowcount > 0
