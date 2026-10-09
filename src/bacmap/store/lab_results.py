from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

_SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS lab_results (
        id               TEXT PRIMARY KEY,
        strain_id        TEXT NOT NULL,
        category         TEXT NOT NULL,
        test_name        TEXT NOT NULL,
        method           TEXT,
        result           TEXT NOT NULL,
        unit             TEXT,
        interpretation   TEXT,
        standard         TEXT,
        tested_date      TEXT,
        tested_by        TEXT,
        lab              TEXT,
        notes            TEXT,
        extra            TEXT,
        created_at       TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_lab_strain ON lab_results(strain_id)",
    "CREATE INDEX IF NOT EXISTS idx_lab_strain_cat ON lab_results(strain_id, category)",
    "CREATE INDEX IF NOT EXISTS idx_lab_category ON lab_results(category)",
]


@dataclass
class LabResult:
    id: str = ""
    strain_id: str = ""
    category: str = ""
    test_name: str = ""
    method: str = ""
    result: str = ""
    unit: str = ""
    interpretation: str = ""
    standard: str = ""
    tested_date: str = ""
    tested_by: str = ""
    lab: str = ""
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v != "" and v is not None}


class LabResultService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        for ddl in _SCHEMA_SQL:
            self._conn.execute(ddl)

    def _row_to_result(self, row: sqlite3.Row) -> LabResult:
        d = dict(row)
        extra_str = d.pop("extra", None)
        extra = json.loads(extra_str) if extra_str else {}
        return LabResult(
            id=d.get("id", ""),
            strain_id=d.get("strain_id", ""),
            category=d.get("category", ""),
            test_name=d.get("test_name", ""),
            method=d.get("method", "") or "",
            result=d.get("result", ""),
            unit=d.get("unit", "") or "",
            interpretation=d.get("interpretation", "") or "",
            standard=d.get("standard", "") or "",
            tested_date=d.get("tested_date", "") or "",
            tested_by=d.get("tested_by", "") or "",
            lab=d.get("lab", "") or "",
            notes=d.get("notes", "") or "",
            extra=extra,
            created_at=d.get("created_at", "") or "",
        )

    def add(
        self,
        strain_id: str,
        category: str,
        test_name: str,
        result: str,
        **kwargs: Any,
    ) -> LabResult:
        now = datetime.now().isoformat()
        result_id = str(uuid4())

        core_fields = {
            "id": result_id,
            "strain_id": strain_id,
            "category": category,
            "test_name": test_name,
            "result": result,
            "method": kwargs.get("method", ""),
            "unit": kwargs.get("unit", ""),
            "interpretation": kwargs.get("interpretation", ""),
            "standard": kwargs.get("standard", ""),
            "tested_date": kwargs.get("tested_date", ""),
            "tested_by": kwargs.get("tested_by", ""),
            "lab": kwargs.get("lab", ""),
            "notes": kwargs.get("notes", ""),
            "created_at": now,
        }

        extra_keys = {
            k: v for k, v in kwargs.items() if k not in core_fields and k != "extra" and v
        }
        core_fields["extra"] = json.dumps(extra_keys, ensure_ascii=False) if extra_keys else None

        cols = ", ".join(core_fields.keys())
        placeholders = ", ".join("?" for _ in core_fields)
        self._conn.execute(
            f"INSERT INTO lab_results ({cols}) VALUES ({placeholders})",
            list(core_fields.values()),
        )
        added = self.get_by_id(result_id)
        assert added is not None
        return added

    def add_batch(
        self, strain_id: str, category: str, results: list[dict[str, Any]]
    ) -> list[LabResult]:
        added = []
        for r in results:
            test_name = r.pop("test_name", "")
            result_val = r.pop("result", "")
            lr = self.add(strain_id, category, test_name, result_val, **r)
            added.append(lr)
        return added

    def get_by_id(self, result_id: str) -> LabResult | None:
        row = self._conn.execute("SELECT * FROM lab_results WHERE id = ?", (result_id,)).fetchone()
        return self._row_to_result(row) if row else None

    def get_by_strain(self, strain_id: str, category: str | None = None) -> list[LabResult]:
        if category:
            rows = self._conn.execute(
                "SELECT * FROM lab_results WHERE strain_id = ? AND category = ? ORDER BY test_name",
                (strain_id, category),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM lab_results WHERE strain_id = ? ORDER BY category, test_name",
                (strain_id,),
            ).fetchall()
        return [self._row_to_result(r) for r in rows]

    def search(
        self,
        *,
        category: str | None = None,
        test_name: str | None = None,
        result: str | None = None,
        interpretation: str | None = None,
        strain_ids: list[str] | None = None,
        limit: int = 200,
    ) -> list[LabResult]:
        conditions = []
        params: list[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if test_name:
            conditions.append("test_name = ?")
            params.append(test_name)
        if result:
            conditions.append("result = ?")
            params.append(result)
        if interpretation:
            conditions.append("interpretation = ?")
            params.append(interpretation)
        if strain_ids:
            placeholders = ", ".join("?" for _ in strain_ids)
            conditions.append(f"strain_id IN ({placeholders})")
            params.extend(strain_ids)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM lab_results{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_result(r) for r in rows]

    def delete(self, result_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM lab_results WHERE id = ?", (result_id,))
        return cur.rowcount > 0

    def delete_by_strain(self, strain_id: str, category: str | None = None) -> int:
        if category:
            cur = self._conn.execute(
                "DELETE FROM lab_results WHERE strain_id = ? AND category = ?",
                (strain_id, category),
            )
        else:
            cur = self._conn.execute("DELETE FROM lab_results WHERE strain_id = ?", (strain_id,))
        return cur.rowcount

    def import_tsv(self, tsv_path: Path | str) -> int:
        import csv

        count = 0
        with open(tsv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                strain_id = row.get("strain_id", "")
                if not strain_id:
                    continue
                category = row.get("category", "")
                test_name = row.get("test_name", "")
                result = row.get("result", "")
                if not category or not test_name or not result:
                    continue
                kwargs = {
                    k: v
                    for k, v in row.items()
                    if k not in ("strain_id", "category", "test_name", "result") and v
                }
                self.add(strain_id, category, test_name, result, **kwargs)
                count += 1
        return count

    def close(self) -> None:
        if hasattr(self, "_conn"):
            self._conn.close()

    def __enter__(self) -> LabResultService:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
