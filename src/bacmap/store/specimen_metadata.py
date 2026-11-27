"""样本级湿实验元数据（v1.10.52）：患者/采样/来源等与 specimen 挂钩。

与 ``strain_metadata``（菌株级）分开存储；数据主体是 JSON，便于 Excel 中
不断变化的湿实验列，不做字段白名单。``specimens`` 必须已存在，避免孤儿元数据。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.store.schema import ensure_data_schema
from bacmap.store.specimens import validate_specimen_id

DDL_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS specimen_metadata (
        specimen_id TEXT PRIMARY KEY,
        data_json   TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
)


class SpecimenMetadataService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SpecimenMetadataService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, specimen_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT data_json FROM specimen_metadata WHERE specimen_id = ?",
            (specimen_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(str(row["data_json"] or "{}"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def upsert(
        self, specimen_id: str, data: dict[str, Any], *, replace: bool = False
    ) -> dict[str, Any]:
        if not validate_specimen_id(specimen_id):
            raise ValueError(f"invalid specimen id: {specimen_id!r}")
        exists = self._conn.execute(
            "SELECT 1 FROM specimens WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()
        if exists is None:
            raise KeyError(f"no such specimen: {specimen_id}")
        merged = dict(data) if replace else {**(self.get(specimen_id) or {}), **data}
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO specimen_metadata"
            " (specimen_id, data_json, created_at, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(specimen_id) DO UPDATE SET"
            " data_json=excluded.data_json, updated_at=excluded.updated_at",
            (
                specimen_id,
                json.dumps(merged, ensure_ascii=False),
                now,
                now,
            ),
        )
        return merged

    def delete(self, specimen_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM specimen_metadata WHERE specimen_id = ?", (specimen_id,)
        )
        return cur.rowcount > 0
