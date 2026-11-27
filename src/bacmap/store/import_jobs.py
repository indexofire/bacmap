"""湿实验导入提案（v1.10.53）：上传与写入之间的审核态。

文件保存在 ``$BACMAP_HOME/imports/<job_id>/``；提案只记录摘要/错误和审核状态，
不写 specimen/isolate/library 元数据。审核通过后才由接口层提交 record batch 任务。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.store.schema import ensure_data_schema

IMPORT_JOB_DDL = """
CREATE TABLE IF NOT EXISTS import_jobs (
    job_id       TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    file_sha256  TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    reviewed_by  TEXT NOT NULL DEFAULT '',
    reviewed_at  TEXT NOT NULL DEFAULT '',
    review_note  TEXT NOT NULL DEFAULT '',
    task_id      TEXT NOT NULL DEFAULT '',
    sheet_args   TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    errors_json  TEXT NOT NULL DEFAULT '[]'
)
"""

IMPORT_JOB_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_status"
    " ON import_jobs(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_creator"
    " ON import_jobs(created_by, created_at)",
)

# 迁移 7（v1.10.56）：把导入提案扩展为通用湿实验提案。
IMPORT_JOB_V7 = (
    "ALTER TABLE import_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'import'",
    "ALTER TABLE import_jobs ADD COLUMN payload_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE import_jobs ADD COLUMN target_type TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE import_jobs ADD COLUMN target_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE import_jobs ADD COLUMN base_version TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_target"
    " ON import_jobs(target_type, target_id, status)",
)


class ImportJobService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ImportJobService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        def _json(value: str, fallback: Any) -> Any:
            try:
                return json.loads(value or "")
            except ValueError:
                return fallback

        return {
            "job_id": str(row["job_id"]),
            "kind": str(row["kind"] or "import"),
            "target_type": str(row["target_type"] or ""),
            "target_id": str(row["target_id"] or ""),
            "base_version": str(row["base_version"] or ""),
            "payload": _json(str(row["payload_json"] or "[]"), []),
            "filename": str(row["filename"]),
            "file_sha256": str(row["file_sha256"]),
            "status": str(row["status"]),
            "created_by": str(row["created_by"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "reviewed_by": str(row["reviewed_by"] or ""),
            "reviewed_at": str(row["reviewed_at"] or ""),
            "review_note": str(row["review_note"] or ""),
            "task_id": str(row["task_id"] or ""),
            "sheet_args": _json(str(row["sheet_args"] or "{}"), {}),
            "summary": _json(str(row["summary_json"] or "{}"), {}),
            "errors": _json(str(row["errors_json"] or "[]"), []),
        }

    def create(
        self,
        *,
        job_id: str,
        filename: str,
        file_sha256: str,
        file_path: Path | str | None,
        created_by: str,
        sheet_args: dict[str, Any],
        summary: dict[str, Any],
        errors: list[str],
        kind: str = "import",
        payload: list[dict[str, Any]] | None = None,
        target_type: str = "",
        target_id: str = "",
        base_version: str = "",
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO import_jobs"
            " (job_id, filename, file_sha256, file_path, status, created_by,"
            "  created_at, updated_at, sheet_args, summary_json, errors_json,"
            "  kind, payload_json, target_type, target_id, base_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                filename,
                file_sha256,
                str(file_path) if file_path else "",
                "pending_review",
                created_by,
                now,
                now,
                json.dumps(sheet_args, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                json.dumps(errors, ensure_ascii=False),
                kind,
                json.dumps(payload or [], ensure_ascii=False),
                target_type,
                target_id,
                base_version,
            ),
        )
        job = self.get(job_id)
        if job is None:  # pragma: no cover
            raise RuntimeError("created import job cannot be read back")
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM import_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return self._payload(row) if row else None

    def file_path(self, job_id: str) -> Path | None:
        row = self._conn.execute(
            "SELECT file_path FROM import_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return Path(str(row["file_path"])) if row else None

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        created_by: str | None = None,
        status: str = "",
        kind: str = "",
    ) -> Sequence[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if created_by is not None:
            clauses.append("created_by = ?")
            params.append(created_by)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            "SELECT * FROM import_jobs" + where  # noqa: S608 — 片段由本模块常量拼装
            + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
        return [self._payload(row) for row in rows]

    def count(
        self, *, created_by: str | None = None, status: str = "", kind: str = ""
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if created_by is not None:
            clauses.append("created_by = ?")
            params.append(created_by)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM import_jobs" + where, params  # noqa: S608
        ).fetchone()
        return int(row[0]) if row else 0

    def mark_reviewed(
        self,
        job_id: str,
        *,
        status: str,
        reviewed_by: str,
        note: str = "",
        task_id: str = "",
    ) -> dict[str, Any] | None:
        if status not in {"submitted", "rejected", "withdrawn", "expired"}:
            raise ValueError(f"invalid import job status: {status}")
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE import_jobs SET status = ?, reviewed_by = ?, reviewed_at = ?,"
            " review_note = ?, task_id = ?, updated_at = ?"
            " WHERE job_id = ? AND status = 'pending_review'",
            (status, reviewed_by, now, note[:1000], task_id, now, job_id),
        )
        if cur.rowcount == 0:
            return None
        return self.get(job_id)

    def pending_for_target(
        self, target_type: str, target_id: str
    ) -> Sequence[dict[str, Any]]:
        if not target_type or not target_id:
            return []
        rows = self._conn.execute(
            "SELECT * FROM import_jobs WHERE target_type = ? AND target_id = ?"
            " AND status = 'pending_review' ORDER BY created_at",
            (target_type, target_id),
        ).fetchall()
        return [self._payload(row) for row in rows]

    def count_pending_before(self, before: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM import_jobs"
            " WHERE status = 'pending_review' AND created_at < ?",
            (before,),
        ).fetchone()
        return int(row[0]) if row else 0

    def expire_pending(self, before: str) -> int:
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE import_jobs SET status = 'expired', updated_at = ?"
            " WHERE status = 'pending_review' AND created_at < ?",
            (now, before),
        )
        return int(cur.rowcount)

    def terminal_before(self, before: str) -> Sequence[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM import_jobs WHERE status IN"
            " ('submitted','rejected','withdrawn','expired') AND updated_at < ?"
            " ORDER BY updated_at",
            (before,),
        ).fetchall()
        return [self._payload(row) for row in rows]

    def delete(self, job_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM import_jobs WHERE job_id = ?", (job_id,))
        return cur.rowcount > 0
