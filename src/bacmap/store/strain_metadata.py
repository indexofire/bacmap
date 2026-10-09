from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS strain_metadata (
        strain_id       TEXT PRIMARY KEY,
        sample_id       TEXT NOT NULL,
        submitting_lab  TEXT,
        submit_date     TEXT,
        receiver        TEXT,
        patient_id      TEXT,
        patient_name    TEXT,
        patient_age     INTEGER,
        patient_gender  TEXT,
        patient_phone   TEXT,
        isolation_date  TEXT,
        province        TEXT,
        city            TEXT,
        district        TEXT,
        facility        TEXT,
        sample_source   TEXT,
        sample_type     TEXT,
        food_category   TEXT,
        food_name       TEXT,
        collection_date TEXT,
        symptoms        TEXT,
        onset_date      TEXT,
        diagnosis       TEXT,
        outcome         TEXT,
        hospital        TEXT,
        outbreak_id     TEXT,
        cluster_note    TEXT,
        extra           TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_meta_sample_id ON strain_metadata(sample_id)",
    "CREATE INDEX IF NOT EXISTS idx_meta_outbreak ON strain_metadata(outbreak_id)",
    "CREATE INDEX IF NOT EXISTS idx_meta_isolation_date ON strain_metadata(isolation_date)",
    "CREATE INDEX IF NOT EXISTS idx_meta_province ON strain_metadata(province)",
]

_CORE_COLUMNS = [
    "strain_id",
    "sample_id",
    "submitting_lab",
    "submit_date",
    "receiver",
    "patient_id",
    "patient_name",
    "patient_age",
    "patient_gender",
    "patient_phone",
    "isolation_date",
    "province",
    "city",
    "district",
    "facility",
    "sample_source",
    "sample_type",
    "food_category",
    "food_name",
    "collection_date",
    "symptoms",
    "onset_date",
    "diagnosis",
    "outcome",
    "hospital",
    "outbreak_id",
    "cluster_note",
]


@dataclass
class StrainMeta:
    strain_id: str
    sample_id: str = ""
    submitting_lab: str = ""
    submit_date: str = ""
    receiver: str = ""
    patient_id: str = ""
    patient_name: str = ""
    patient_age: int | None = None
    patient_gender: str = ""
    patient_phone: str = ""
    isolation_date: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    facility: str = ""
    sample_source: str = ""
    sample_type: str = ""
    food_category: str = ""
    food_name: str = ""
    collection_date: str = ""
    symptoms: str = ""
    onset_date: str = ""
    diagnosis: str = ""
    outcome: str = ""
    hospital: str = ""
    outbreak_id: str = ""
    cluster_note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if v != "" and v is not None}
        d["strain_id"] = self.strain_id
        if self.sample_id:
            d["sample_id"] = self.sample_id
        return d


class StrainMetadataService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        for ddl in _SCHEMA_SQL:
            self._conn.execute(ddl)

    def _split_core_extra(self, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        core: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for k, v in data.items():
            if k in _CORE_COLUMNS:
                core[k] = v
            elif k not in ("created_at", "updated_at", "extra"):
                extra[k] = v
        return core, extra

    def _row_to_meta(self, row: sqlite3.Row) -> StrainMeta:
        d = dict(row)
        extra_str = d.pop("extra", None)
        extra = json.loads(extra_str) if extra_str else {}
        return StrainMeta(
            strain_id=d.get("strain_id", ""),
            sample_id=d.get("sample_id", "") or "",
            submitting_lab=d.get("submitting_lab", "") or "",
            submit_date=d.get("submit_date", "") or "",
            receiver=d.get("receiver", "") or "",
            patient_id=d.get("patient_id", "") or "",
            patient_name=d.get("patient_name", "") or "",
            patient_age=d.get("patient_age"),
            patient_gender=d.get("patient_gender", "") or "",
            patient_phone=d.get("patient_phone", "") or "",
            isolation_date=d.get("isolation_date", "") or "",
            province=d.get("province", "") or "",
            city=d.get("city", "") or "",
            district=d.get("district", "") or "",
            facility=d.get("facility", "") or "",
            sample_source=d.get("sample_source", "") or "",
            sample_type=d.get("sample_type", "") or "",
            food_category=d.get("food_category", "") or "",
            food_name=d.get("food_name", "") or "",
            collection_date=d.get("collection_date", "") or "",
            symptoms=d.get("symptoms", "") or "",
            onset_date=d.get("onset_date", "") or "",
            diagnosis=d.get("diagnosis", "") or "",
            outcome=d.get("outcome", "") or "",
            hospital=d.get("hospital", "") or "",
            outbreak_id=d.get("outbreak_id", "") or "",
            cluster_note=d.get("cluster_note", "") or "",
            extra=extra,
            created_at=d.get("created_at", "") or "",
            updated_at=d.get("updated_at", "") or "",
        )

    def upsert(self, strain_id: str, data: dict[str, Any]) -> StrainMeta:
        existing = self.get(strain_id)
        existing_extra = existing.extra if existing else {}

        core, extra = self._split_core_extra(data)
        merged_extra = {**existing_extra, **extra}

        now = datetime.now().isoformat()
        core["strain_id"] = strain_id
        if not core.get("sample_id"):
            core["sample_id"] = strain_id
        core["extra"] = json.dumps(merged_extra, ensure_ascii=False) if merged_extra else None
        core["updated_at"] = now

        existing = self._conn.execute(
            "SELECT 1 FROM strain_metadata WHERE strain_id = ?", (strain_id,)
        ).fetchone()

        self._conn.execute("BEGIN")
        try:
            if existing:
                sets = ", ".join(f"{k} = ?" for k in core)
                values = list(core.values()) + [strain_id]
                self._conn.execute(f"UPDATE strain_metadata SET {sets} WHERE strain_id = ?", values)
            else:
                core["created_at"] = now
                cols = ", ".join(core.keys())
                placeholders = ", ".join("?" for _ in core)
                self._conn.execute(
                    f"INSERT INTO strain_metadata ({cols}) VALUES ({placeholders})",
                    list(core.values()),
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        result = self.get(strain_id)
        assert result is not None
        return result

    def get(self, strain_id: str) -> StrainMeta | None:
        row = self._conn.execute(
            "SELECT * FROM strain_metadata WHERE strain_id = ?", (strain_id,)
        ).fetchone()
        return self._row_to_meta(row) if row else None

    def search(
        self,
        *,
        province: str | None = None,
        outbreak_id: str | None = None,
        sample_source: str | None = None,
        isolation_date_from: str | None = None,
        isolation_date_to: str | None = None,
        extra: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[StrainMeta]:
        conditions = []
        params: list[Any] = []

        if province:
            conditions.append("province = ?")
            params.append(province)
        if outbreak_id:
            conditions.append("outbreak_id = ?")
            params.append(outbreak_id)
        if sample_source:
            conditions.append("sample_source = ?")
            params.append(sample_source)
        if isolation_date_from:
            conditions.append("isolation_date >= ?")
            params.append(isolation_date_from)
        if isolation_date_to:
            conditions.append("isolation_date <= ?")
            params.append(isolation_date_to)

        if extra:
            for k, v in extra.items():
                conditions.append("json_extract(extra, ?) = ?")
                params.append(f"$.{k}")
                params.append(v)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM strain_metadata{where} ORDER BY isolation_date DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_meta(r) for r in rows]

    def delete(self, strain_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM strain_metadata WHERE strain_id = ?", (strain_id,))
        return cur.rowcount > 0

    def list_all(self, limit: int = 100) -> list[StrainMeta]:
        rows = self._conn.execute(
            "SELECT * FROM strain_metadata ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_meta(r) for r in rows]

    def import_tsv(self, tsv_path: Path | str) -> int:
        import csv

        count = 0
        with open(tsv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                strain_id = row.get("strain_id") or row.get("sample") or ""
                if not strain_id:
                    continue
                clean = {k: v for k, v in row.items() if v}
                if "sample" in clean:
                    clean["sample_id"] = clean.pop("sample")
                self.upsert(strain_id, clean)
                count += 1
        return count

    def close(self) -> None:
        if hasattr(self, "_conn"):
            self._conn.close()

    def __enter__(self) -> StrainMetadataService:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
