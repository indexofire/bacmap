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

    def ensure(
        self,
        specimen_id: str,
        *,
        origin: str = "",
        note: str = "",
        owner_user_id: str | None = None,
    ) -> None:
        """登记样本（幂等；已存在时不覆盖 origin/note/owner）。

        ``owner_user_id`` 只在新行写入时生效；旧数据/已有样本的归属不会被
        普通登记流程改写（显式改归属走 ``set_owner`` 或管理员接口）。
        """
        if not validate_specimen_id(specimen_id):
            raise ValueError(f"invalid specimen id: {specimen_id!r}")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO specimens"
            " (specimen_id, origin, note, created_at, updated_at, owner_user_id)"
            " VALUES (?,?,?,?,?,?)",
            (specimen_id, origin, note, now, now, owner_user_id or None),
        )

    def set_owner(self, specimen_id: str, owner_user_id: str | None) -> bool:
        """显式改样本归属；返回是否命中该样本（管理员/导入脚本使用）。"""
        cur = self._conn.execute(
            "UPDATE specimens SET owner_user_id = ?, updated_at = ? WHERE specimen_id = ?",
            (owner_user_id or None, datetime.now(UTC).isoformat(), specimen_id),
        )
        return cur.rowcount > 0

    def exists(self, specimen_id: str) -> bool:
        return self.get(specimen_id) is not None

    def get(self, specimen_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM specimens WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete(self, specimen_id: str, *, force: bool = False) -> dict[str, Any]:
        """删除样本。

        默认只允许删除**空样本**（无关联菌株）；``force=True`` 先把关联菌株的
        ``specimen_id`` 置空（不删菌株/测序数据）再删除。返回
        ``{"deleted": bool, "unlinked_isolates": n}``。
        """
        row = self.get(specimen_id)
        if row is None:
            return {"deleted": False, "unlinked_isolates": 0}
        linked = self._conn.execute(
            "SELECT COUNT(*) FROM isolates WHERE specimen_id = ?", (specimen_id,)
        ).fetchone()[0]
        if linked and not force:
            raise ValueError(
                f"specimen {specimen_id!r} has {linked} linked isolate(s); "
                "reassign them first or use force to unlink"
            )
        # autocommit 连接（isolation_level=None）：解绑+删除必须包进显式事务——
        # 否则两次写入各自独立提交，中途崩溃会留下"菌株已解绑但样本仍存在"的不一致态。
        unlinked = 0
        self._conn.execute("BEGIN")
        try:
            if linked:
                now = datetime.now(UTC).isoformat()
                self._conn.execute(
                    "UPDATE isolates SET specimen_id = NULL, updated_at = ?"
                    " WHERE specimen_id = ?",
                    (now, specimen_id),
                )
                unlinked = int(linked)
            self._conn.execute("DELETE FROM specimens WHERE specimen_id = ?", (specimen_id,))
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return {"deleted": True, "unlinked_isolates": unlinked}

    def isolates(self, specimen_id: str) -> list[dict[str, Any]]:
        """该样本下的菌株（隔离/传代信息原样返回）。"""
        rows = self._conn.execute(
            "SELECT * FROM isolates WHERE specimen_id = ? ORDER BY isolate_id",
            (specimen_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list(
        self,
        limit: int = 200,
        offset: int = 0,
        *,
        query: str = "",
        owner_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _specimen_filters(query, owner_user_id)
        rows = self._conn.execute(
            "SELECT s.*,"  # noqa: S608 — where 片段仅由本模块常量拼装
            " (SELECT COUNT(*) FROM isolates i WHERE i.specimen_id = s.specimen_id)"
            " AS n_isolates"
            f" FROM specimens s{where} ORDER BY s.specimen_id LIMIT ? OFFSET ?",
            (*params, max(1, limit), max(0, offset)),
        ).fetchall()
        return [dict(r) for r in rows]

    def count(
        self, *, query: str = "", owner_user_id: str | None = None
    ) -> int:
        where, params = _specimen_filters(query, owner_user_id)
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM specimens s{where}", params  # noqa: S608
        ).fetchone()
        return int(row[0]) if row else 0


def _specimen_filters(
    query: str, owner_user_id: str | None
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if owner_user_id is not None:
        clauses.append("s.owner_user_id = ?")
        params.append(owner_user_id)
    q = query.strip().lower()
    if q:
        like = f"%{q}%"
        clauses.append(
            "(LOWER(s.specimen_id) LIKE ? OR LOWER(s.origin) LIKE ? OR LOWER(s.note) LIKE ?)"
        )
        params.extend([like, like, like])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)
