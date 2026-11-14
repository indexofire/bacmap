"""Specimen 注册表（v1.10.27，身份模型 P1）：样本实体。

身份层级（specimen / isolate / library / run）：

    specimen（样本，唯一送检编号，如 A03-SN-001）
       ├── isolate（菌株，0..N；isolates.specimen_id 指向本表）
       │      └── library（一次测序数据；samples.tsv 的 sample 列）
       │             └── run（一次分析执行）
       └── library（mNGS/tNGS 直接测样本；下一大版本接入）

样本编号**允许为空**（外部未提供时先留空）：此时 isolate.specimen_id 为 NULL，
后续通过 ``bacmap specimen import`` / ``assign`` 补录并建立关联。旧库迁移采用
"影子样本"（specimen_id = isolate_id，origin=legacy，1:1），查询行为不变。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.store.schema import ensure_data_schema

# 与 dataset/isolate 一致的宽松白名单（不含路径分隔符，拒绝 . / ..）
_SPECIMEN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

SPECIMENS_DDL = """
CREATE TABLE IF NOT EXISTS specimens (
    specimen_id TEXT PRIMARY KEY,
    origin      TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""


def validate_specimen_id(specimen_id: str) -> bool:
    """样本编号白名单（``A03-SN-001`` 形态；拒绝 ``.``/``..`` 与路径分隔符）。"""
    return bool(specimen_id) and specimen_id not in (".", "..") and bool(
        _SPECIMEN_ID_RE.match(specimen_id)
    )


class SpecimenService:
    """``data/bacmap.sqlite`` 中的 specimens 表（与 isolates / 化验结果同库）。"""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SpecimenService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def ensure(self, specimen_id: str, *, origin: str = "", note: str = "") -> None:
        """登记样本（幂等；已存在时不覆盖 origin/note）。"""
        if not validate_specimen_id(specimen_id):
            raise ValueError(f"invalid specimen id: {specimen_id!r}")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO specimens"
            " (specimen_id, origin, note, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (specimen_id, origin, note, now, now),
        )

    def exists(self, specimen_id: str) -> bool:
        return self.get(specimen_id) is not None

    def get(self, specimen_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM specimens WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()
        return dict(row) if row else None

    def isolates(self, specimen_id: str) -> list[dict[str, Any]]:
        """该样本下的菌株（隔离/传代信息原样返回）。"""
        rows = self._conn.execute(
            "SELECT * FROM isolates WHERE specimen_id = ? ORDER BY isolate_id",
            (specimen_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT s.*,"
            " (SELECT COUNT(*) FROM isolates i WHERE i.specimen_id = s.specimen_id)"
            " AS n_isolates"
            " FROM specimens s ORDER BY s.specimen_id LIMIT ?",
            (max(1, limit),),
        ).fetchall()
        return [dict(r) for r in rows]
