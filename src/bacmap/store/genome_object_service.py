"""Genome Object Service (GOS) — Sprint 1 实现。

project.md §5 定义的 Genome Object Model (GOM) 服务层。

参考文档：
- project.md §5.1 标准 Schema
- project.md §5.2 Composite Triplet Schema
- project.md §5.4 SQLite 表结构
- project.md §4.4 Event First
- project.md §4.5 Version First（三元证据链）
- project.md §4.6 Immutable（不可覆盖）
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, get_args
from uuid import uuid4

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.]+)?$")

_logger = logging.getLogger(__name__)


class GOMValidationError(Exception):
    pass


class GOMNotFoundError(KeyError):
    pass


class GOMImmutableError(Exception):
    pass


class ObjectType(StrEnum):
    SAMPLE = "sample"
    ANALYSIS = "analysis"
    REPORT = "report"
    WORKFLOW = "workflow"
    PLUGIN = "plugin"
    KNOWLEDGE = "knowledge"
    TASK = "task"


EventType = Literal[
    "uploaded",
    "qc_finished",
    "assembly_finished",
    "annotation_finished",
    "amr_finished",
    "mlst_finished",
    "serotype_finished",
    "snp_finished",
    "report_generated",
    "analysis_failed",
    "version_created",
    "nli_reflected",
    "species_identified",
]

# 运行期校验集合由 Literal 派生（单一事实来源：新增事件类型只改上面一处）。
_VALID_EVENT_TYPES = frozenset(get_args(EventType))


# cgMLST-only; every other analysis_type stays opaque (additive, no migration).
_CGMLST_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "cgmlst_profile": ("scheme", "n_loci"),
    "cgmlst_cohort": ("scheme", "n_loci", "allele_distances"),
}

SPECIES_ID_METHODS = frozenset(
    {"marker", "panel", "skani_gtdb", "mash_refseq", "sourmash", "gtdbtk", "kraken2"}
)


def _validate_species_payload(payload: dict[str, Any]) -> None:
    """Species-identification ANALYSIS payloads; no-op for any other analysis_type."""
    if payload.get("analysis_type") != "species_identification":
        return
    for field_name in ("method", "database", "result"):
        if field_name not in payload:
            raise GOMValidationError(
                f"species_identification payload missing required field {field_name!r}"
            )
    method = payload["method"]
    if method not in SPECIES_ID_METHODS:
        raise GOMValidationError(
            f"species_identification method {method!r} not in {sorted(SPECIES_ID_METHODS)}"
        )
    result = payload["result"]
    if not isinstance(result, dict) or "species" not in result or "confidence" not in result:
        raise GOMValidationError(
            "species_identification result must be a dict with 'species' and 'confidence'"
        )


def _validate_cgmlst_payload(payload: dict[str, Any]) -> None:
    """Validate cgMLST ANALYSIS payloads; no-op for any other analysis_type.

    Raises GOMValidationError when a cgMLST payload is missing a required
    top-level field:
      - ``cgmlst_profile`` requires ``scheme`` and ``n_loci``
      - ``cgmlst_cohort`` requires ``scheme``, ``n_loci`` and ``allele_distances``

    For every other ``analysis_type`` (including missing ``analysis_type``)
    this function is a pass-through, preserving the existing opaque-payload
    contract for SNP cohort / MLST / AMR / serotype analyses.
    """
    analysis_type = payload.get("analysis_type")
    if not isinstance(analysis_type, str):
        return
    required = _CGMLST_REQUIRED_FIELDS.get(analysis_type)
    if required is None:
        return
    missing = [field for field in required if field not in payload]
    if missing:
        raise GOMValidationError(
            f"{analysis_type} ANALYSIS payload missing required field(s): {missing}"
        )


@dataclass(frozen=True)
class GenomeObject:
    """Genome Object 标准实体（project.md §5.1）。frozen=True 强制 Immutable（§4.6）。"""

    object_id: str
    object_type: ObjectType | str
    version: int
    schema_version: str
    created_at: datetime
    created_by: str
    payload: dict[str, Any] = field(default_factory=dict)
    pipeline_version: str | None = None
    database_versions: dict[str, str] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)
    organism: str | None = None
    strain_id: str | None = None
    database_signature: str | None = None

    def __post_init__(self) -> None:
        # 保留前缀防护：__gom_* 由服务层注入管线/数据库版本（_go_to_row 写入、
        # _row_to_go 剥离）。用户 payload 携带同名键会在写入时被静默覆盖、读出时
        # 被静默剥离——数据损坏且无检测，故在模型边界直接拒绝。
        reserved = [str(k) for k in self.payload if str(k).startswith("__gom_")]
        if reserved:
            raise GOMValidationError(
                f"payload keys with reserved prefix '__gom_' are not allowed: {reserved}"
            )
        if isinstance(self.object_type, str) and not isinstance(self.object_type, ObjectType):
            try:
                object.__setattr__(self, "object_type", ObjectType(self.object_type))
            except ValueError:
                valid = [t.value for t in ObjectType]
                raise GOMValidationError(
                    f"Invalid object_type: {self.object_type!r}. Must be one of {valid}"
                ) from None
        elif not isinstance(self.object_type, ObjectType):
            raise GOMValidationError(f"Invalid object_type: {self.object_type!r}")

        if not isinstance(self.version, int) or self.version < 1:
            raise GOMValidationError(f"version must be a positive integer, got {self.version!r}")

        if not _SEMVER_RE.match(self.schema_version):
            raise GOMValidationError(
                f"schema_version must be semver (X.Y.Z[-suffix]), got {self.schema_version!r}"
            )

        if self.object_type == ObjectType.ANALYSIS:
            if not self.pipeline_version:
                raise GOMValidationError(
                    "ANALYSIS GenomeObject requires pipeline_version"
                    " (project.md §4.5 evidence chain)"
                )
            # C4 证据链要求"参考数据库与工具的实测版本"：二者至少有其一即可
            # （运行记录里 tool_versions 由 probe 保证非空，参考库清单可能为空）。
            if not self.database_versions and not self.tool_versions:
                raise GOMValidationError(
                    "ANALYSIS GenomeObject requires database_versions or tool_versions"
                    " (project.md §4.5)"
                )
            _validate_cgmlst_payload(self.payload)
            _validate_species_payload(self.payload)


@dataclass(frozen=True)
class FileArtifact:
    artifact_id: str
    object_id: str
    version: int
    file_type: str
    file_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Event:
    event_id: str
    object_id: str
    event_type: str
    event_payload: dict[str, Any]
    timestamp: datetime


@dataclass(frozen=True)
class CompositeTriplet:
    """复合三元组（project.md §5.2，学 GPAS 防近邻幻觉）。

    示例（AMR）:
        subject="blaCTX-M-15", relation="confers_resistance_to", object="Cefotaxime"
        subject_attributes={"mutation_site": "Promoter -281G>A"}
        relation_conditions={"mic": "≥64", "method": "in_silico"}
        object_attributes={"class": "β-lactam/3rd-gen cephalosporin"}
    """

    subject: str
    relation: str
    object: str
    subject_attributes: dict[str, Any] = field(default_factory=dict)
    relation_conditions: dict[str, Any] = field(default_factory=dict)
    object_attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject:
            raise GOMValidationError("CompositeTriplet.subject is required")
        if not self.relation:
            raise GOMValidationError("CompositeTriplet.relation is required")
        if not self.object:
            raise GOMValidationError("CompositeTriplet.object is required")


_SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS genome_objects (
        object_id TEXT NOT NULL,
        object_type TEXT NOT NULL,
        version INTEGER NOT NULL,
        schema_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        organism TEXT,
        strain_id TEXT,
        pipeline_version TEXT,
        database_signature TEXT,
        PRIMARY KEY (object_id, version)
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS genome_objects_fts USING fts5(
        object_type, organism, strain_id, payload_text
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        object_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_payload TEXT NOT NULL,
        timestamp TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS file_artifacts (
        artifact_id TEXT PRIMARY KEY,
        object_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        file_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_go_type ON genome_objects(object_type)",
    "CREATE INDEX IF NOT EXISTS idx_go_organism ON genome_objects(organism)",
    "CREATE INDEX IF NOT EXISTS idx_go_strain ON genome_objects(strain_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_object ON events(object_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_fa_object ON file_artifacts(object_id, version)",
]


class GenomeObjectService:
    """Genome Object 的 CRUD + 版本管理 + 事件 + 文件产物。

    后端：SQLite + WAL + JSON 列 + FTS5（project.md §5.4, §6.1）。
    """

    def __init__(self, db_path: Path) -> None:
        import sqlite3

        self.db_path = db_path
        self._conn = sqlite3.connect(
            str(db_path),
            isolation_level=None,  # autocommit; we manage txns manually
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA temp_store = MEMORY")
        for ddl in _SCHEMA_SQL:
            self._conn.execute(ddl)

    def _begin(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def _commit(self) -> None:
        self._conn.execute("COMMIT")

    def _rollback(self) -> None:
        try:
            self._conn.execute("ROLLBACK")
        except Exception:
            # 已回滚/无活动事务属预期；其余（如连接损坏）留 debug 痕迹便于排查。
            _logger.debug("ROLLBACK skipped (no active transaction or broken conn)",
                          exc_info=True)

    @staticmethod
    def _go_to_row(obj: GenomeObject) -> dict[str, Any]:
        full_payload = dict(obj.payload)
        full_payload["__gom_pipeline_version"] = obj.pipeline_version
        full_payload["__gom_database_versions"] = obj.database_versions
        full_payload["__gom_tool_versions"] = obj.tool_versions
        return {
            "object_id": obj.object_id,
            "object_type": str(obj.object_type),
            "version": obj.version,
            "schema_version": obj.schema_version,
            "created_at": obj.created_at.isoformat(),
            "created_by": obj.created_by,
            "payload_json": json.dumps(full_payload, ensure_ascii=False),
            "organism": obj.organism,
            "strain_id": obj.strain_id,
            "pipeline_version": obj.pipeline_version,
            "database_signature": obj.database_signature,
        }

    @staticmethod
    def _row_to_go(row: sqlite3.Row | dict[str, Any]) -> GenomeObject:
        d = dict(row) if not isinstance(row, dict) else row
        payload = json.loads(d["payload_json"])
        full_payload = dict(payload)
        pv = full_payload.pop("__gom_pipeline_version", d.get("pipeline_version"))
        db_v = full_payload.pop("__gom_database_versions", {})
        tv = full_payload.pop("__gom_tool_versions", {})
        return GenomeObject(
            object_id=d["object_id"],
            object_type=ObjectType(d["object_type"]),
            version=d["version"],
            schema_version=d["schema_version"],
            created_at=datetime.fromisoformat(d["created_at"]),
            created_by=d["created_by"],
            payload=full_payload,
            pipeline_version=pv,
            database_versions=db_v if isinstance(db_v, dict) else {},
            tool_versions=tv if isinstance(tv, dict) else {},
            organism=d.get("organism"),
            strain_id=d.get("strain_id"),
            database_signature=d.get("database_signature"),
        )

    def create(self, obj: GenomeObject) -> GenomeObject:
        row = self._go_to_row(obj)
        payload_json = row.pop("payload_json")
        self._begin()
        try:
            # 不可变检查必须在 BEGIN IMMEDIATE 事务内：并发写者后到者会命中
            # 这里的 SELECT（或下方 IntegrityError 兜底）得到 GOMImmutableError，
            # 而非裸 sqlite3.IntegrityError——dbos_engine 依赖该异常类型实现幂等重跑。
            existing = self._conn.execute(
                "SELECT 1 FROM genome_objects WHERE object_id = ? AND version = ?",
                (obj.object_id, obj.version),
            ).fetchone()
            if existing:
                raise GOMImmutableError(
                    f"GenomeObject ({obj.object_id}, v{obj.version}) already exists. "
                    "Use create_new_version() for new versions (project.md §4.6 Immutable)."
                )
            cur = self._conn.execute(
                """INSERT INTO genome_objects
                   (object_id, object_type, version, schema_version, created_at, created_by,
                    payload_json, organism, strain_id, pipeline_version, database_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["object_id"],
                    row["object_type"],
                    row["version"],
                    row["schema_version"],
                    row["created_at"],
                    row["created_by"],
                    payload_json,
                    row["organism"],
                    row["strain_id"],
                    row["pipeline_version"],
                    row["database_signature"],
                ),
            )
            # FTS rowid 显式对齐 genome_objects.rowid（search 依赖该不变量），
            # 不依赖两张表"各自自增恰好同步"的偶然性。
            self._conn.execute(
                """INSERT INTO genome_objects_fts
                   (rowid, object_type, organism, strain_id, payload_text)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    int(cur.lastrowid or 0),
                    row["object_type"],
                    row["organism"] or "",
                    row["strain_id"] or "",
                    payload_json,
                ),
            )
            self._commit()
        except sqlite3.IntegrityError as exc:
            # 并发兜底：另一写者已插入同 (object_id, version)（如唯一索引/主键冲突）。
            self._rollback()
            raise GOMImmutableError(
                f"GenomeObject ({obj.object_id}, v{obj.version}) already exists. "
                "Use create_new_version() for new versions (project.md §4.6 Immutable)."
            ) from exc
        except Exception:
            self._rollback()
            raise
        return obj

    def read(self, object_id: str, version: int = 1) -> GenomeObject:
        row = self._conn.execute(
            "SELECT * FROM genome_objects WHERE object_id = ? AND version = ?",
            (object_id, version),
        ).fetchone()
        if row is None:
            raise GOMNotFoundError(f"GenomeObject not found: ({object_id}, v{version})")
        return self._row_to_go(row)

    def _list_latest(
        self, where: str, params: tuple[Any, ...], suffix: str = ""
    ) -> list[GenomeObject]:
        """按条件取每个 object_id 的最新版本（单一 SQL 模板，避免四处复制粘贴）。

        ``where`` 只允许本模块内拼入（参数一律走 ``params`` 绑定，不拼用户输入）。
        """
        cond = f"WHERE {where}" if where else ""

        sql = (
            "SELECT g.* FROM genome_objects g"  # noqa: S608 — 片段为本模块常量拼装，值经 params 绑定
            " INNER JOIN (SELECT object_id, MAX(version) AS max_v FROM genome_objects"
            f" {cond} GROUP BY object_id)"
            " latest ON g.object_id = latest.object_id AND g.version = latest.max_v"
            f" {suffix}"
        )
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_go(r) for r in rows]

    def list_by_type(
        self, object_type: ObjectType, limit: int = 100, offset: int = 0
    ) -> list[GenomeObject]:
        return self._list_latest(
            "object_type = ?",
            (object_type.value, limit, offset),
            suffix="ORDER BY g.created_at DESC LIMIT ? OFFSET ?",
        )

    def list_species_identifications(self, strain_id: str) -> list[GenomeObject]:
        """Latest-version species_identification ANALYSIS objects for one strain."""
        return [
            go
            for go in self._list_latest(
                "object_type = 'analysis' AND strain_id = ?",
                (strain_id,),
                suffix="ORDER BY g.created_at DESC",
            )
            if go.payload.get("analysis_type") == "species_identification"
        ]

    def list_by_organism(
        self, organism: str, limit: int = 100, offset: int = 0
    ) -> list[GenomeObject]:
        return self._list_latest(
            "organism = ?",
            (organism, limit, offset),
            suffix="ORDER BY g.created_at DESC LIMIT ? OFFSET ?",
        )

    def create_new_version(
        self,
        object_id: str,
        payload: dict[str, Any],
        *,
        pipeline_version: str | None = None,
        database_versions: dict[str, str] | None = None,
        tool_versions: dict[str, str] | None = None,
    ) -> GenomeObject:
        latest = self.get_latest_version(object_id)
        old = self.read(object_id, latest)
        new_obj = GenomeObject(
            object_id=object_id,
            object_type=old.object_type,
            version=latest + 1,
            schema_version=old.schema_version,
            created_at=datetime.now(UTC),
            created_by=old.created_by,
            payload=payload,
            pipeline_version=pipeline_version
            if pipeline_version is not None
            else old.pipeline_version,
            database_versions=database_versions
            if database_versions is not None
            else old.database_versions,
            tool_versions=tool_versions if tool_versions is not None else old.tool_versions,
            organism=old.organism,
            strain_id=old.strain_id,
            database_signature=old.database_signature,
        )
        return self.create(new_obj)

    def get_latest_version(self, object_id: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(version) AS v FROM genome_objects WHERE object_id = ?",
            (object_id,),
        ).fetchone()
        if row is None or row["v"] is None:
            raise GOMNotFoundError(f"GenomeObject not found: {object_id}")
        return int(row["v"])

    def list_versions(self, object_id: str) -> list[GenomeObject]:
        rows = self._conn.execute(
            "SELECT * FROM genome_objects WHERE object_id = ? ORDER BY version ASC",
            (object_id,),
        ).fetchall()
        if not rows:
            raise GOMNotFoundError(f"GenomeObject not found: {object_id}")
        return [self._row_to_go(r) for r in rows]

    def delete(self, object_id: str, version: int) -> None:
        raise GOMImmutableError(
            f"删除 GenomeObject ({object_id}, v{version}) 被拒绝："
            "Immutable 原则禁止删除（project.md §4.6）"
        )

    def register_file_artifact(
        self,
        object_id: str,
        version: int,
        file_type: str,
        file_path: Path,
        sha256: str,
        size_bytes: int,
    ) -> FileArtifact:
        self.read(object_id, version)  # 对象不存在 → GOMNotFoundError 透传

        # 格式校验前置：避免先白读一遍大文件再报格式错误。
        if not sha256 or len(sha256) != 64:
            raise GOMValidationError("sha256 must be a 64-character hex string")
        if not file_path.exists():
            raise GOMValidationError(f"File not found: {file_path}")
        actual_sha = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192 * 1024), b""):
                actual_sha.update(chunk)
        actual_hex = actual_sha.hexdigest()
        if actual_hex != sha256:
            raise GOMValidationError(
                f"SHA256 mismatch for {file_path}: expected {sha256}, got {actual_hex}"
            )
        actual_size = file_path.stat().st_size
        if actual_size != size_bytes:
            raise GOMValidationError(
                f"Size mismatch for {file_path}: expected {size_bytes}, got {actual_size}"
            )

        artifact_id = str(uuid4())
        artifact = FileArtifact(
            artifact_id=artifact_id,
            object_id=object_id,
            version=version,
            file_type=file_type,
            file_path=str(file_path),
            sha256=sha256,
            size_bytes=size_bytes,
        )
        self._begin()
        try:
            self._conn.execute(
                """INSERT INTO file_artifacts
                   (artifact_id, object_id, version, file_type, file_path, sha256, size_bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (artifact_id, object_id, version, file_type, str(file_path), sha256, size_bytes),
            )
            self._commit()
        except Exception:
            self._rollback()
            raise
        return artifact

    def list_file_artifacts(self, object_id: str, version: int | None = None) -> list[FileArtifact]:
        if version is not None:
            self.read(object_id, version)
        else:
            self.get_latest_version(object_id)

        if version is not None:
            rows = self._conn.execute(
                "SELECT * FROM file_artifacts WHERE object_id = ? AND version = ?",
                (object_id, version),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM file_artifacts WHERE object_id = ?",
                (object_id,),
            ).fetchall()
        return [
            FileArtifact(
                artifact_id=r["artifact_id"],
                object_id=r["object_id"],
                version=r["version"],
                file_type=r["file_type"],
                file_path=r["file_path"],
                sha256=r["sha256"],
                size_bytes=r["size_bytes"],
            )
            for r in rows
        ]

    def log_event(self, object_id: str, event_type: str, event_payload: dict[str, Any]) -> Event:
        # 门事件按冻结设计 §4.2 记为 event_type = "gate.<name>"；其余走白名单。
        if not (event_type in _VALID_EVENT_TYPES or event_type.startswith("gate.")):
            raise GOMValidationError(
                f"Invalid event_type: {event_type!r}. Must be one of {sorted(_VALID_EVENT_TYPES)}"
                " or 'gate.<name>'"
            )
        self.get_latest_version(object_id)  # 对象不存在 → GOMNotFoundError 透传

        event_id = str(uuid4())
        timestamp = datetime.now(UTC).replace(tzinfo=None)
        event = Event(
            event_id=event_id,
            object_id=object_id,
            event_type=event_type,
            event_payload=event_payload,
            timestamp=timestamp,
        )
        self._begin()
        try:
            self._conn.execute(
                """INSERT INTO events (event_id, object_id, event_type, event_payload, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event_id,
                    object_id,
                    event_type,
                    json.dumps(event_payload, ensure_ascii=False),
                    timestamp.isoformat(),
                ),
            )
            self._commit()
        except Exception:
            self._rollback()
            raise
        return event

    def list_events(self, object_id: str, since: datetime | None = None) -> list[Event]:
        self.get_latest_version(object_id)  # 对象不存在 → GOMNotFoundError 透传

        if since is not None:
            since_naive = since.replace(tzinfo=None) if since.tzinfo else since
            rows = self._conn.execute(
                "SELECT * FROM events WHERE object_id = ? AND timestamp > ? ORDER BY timestamp ASC",
                (object_id, since_naive.isoformat()),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE object_id = ? ORDER BY timestamp ASC",
                (object_id,),
            ).fetchall()
        return [
            Event(
                event_id=r["event_id"],
                object_id=r["object_id"],
                event_type=r["event_type"],
                event_payload=json.loads(r["event_payload"]),
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]

    def search(
        self,
        query: str,
        object_type: ObjectType | None = None,
        limit: int = 50,
    ) -> list[GenomeObject]:
        """Full-text search across all genome objects using FTS5.

        Searches organism, strain_id, and full payload JSON.
        Returns latest version per matching object_id.
        """

        if not query.strip():
            return []

        fts_query = " OR ".join(
            f'"{term.replace('"', '""')}"' for term in query.split() if term.strip()
        )

        # 注：FTS5 的 MATCH 左侧须为表名形式（别名 fts 仅用于 ON 连接）。
        sql = """
            SELECT DISTINCT g.* FROM genome_objects g
            INNER JOIN (
                SELECT rowid, object_id, MAX(version) AS max_v
                FROM genome_objects
                GROUP BY object_id
            ) latest ON g.object_id = latest.object_id AND g.version = latest.max_v
            INNER JOIN genome_objects_fts fts ON fts.rowid = g.rowid
            WHERE genome_objects_fts MATCH ?
        """
        params: list[Any] = [fts_query]

        if object_type is not None:
            sql += " AND g.object_type = ?"
            params.append(object_type.value)

        sql += " ORDER BY g.created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_go(r) for r in rows]

    def close(self) -> None:
        # 幂等关闭：保留已关闭的连接对象（sqlite3 连接可重复 close）。此后再调用
        # 任何方法会得到 sqlite3.ProgrammingError("Cannot operate on a closed
        # database")——比删除属性后的裸 AttributeError 更可定位。
        conn = self.__dict__.get("_conn")
        if conn is not None:
            conn.close()

    def __enter__(self) -> GenomeObjectService:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()


def _new_uuid() -> str:
    return str(uuid4())


def new_object_id() -> str:
    return _new_uuid()


def record_gate_event(
    gom_db: Path, object_id: str, gate_result: dict[str, Any]
) -> Event:
    """把一次门评估写入 GOM ``events``（§4.2 / ADR-07：``gate.<name>``）。

    每道门评估都应留痕；本函数是唯一写入口，由任务引擎在门评估后调用。
    """
    with GenomeObjectService(gom_db) as gos:
        gate = str(gate_result.get("gate", "unknown"))
        return gos.log_event(object_id, f"gate.{gate}", gate_result)


def new_artifact_id() -> str:
    return _new_uuid()


def new_event_id() -> str:
    return _new_uuid()
