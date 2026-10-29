"""外部数据登记（A 方案：零拷贝只读挂载 + SHA256 证据链，ADR-11/ADR-18）。

设计要点：
- **不复制**原始数据：登记其身份（源路径、逐文件 SHA256、清单哈希、大小、来源
  描述符 dev/inode/mtime），沙箱以只读 bind-mount 原始路径（ADR-11"数据只读挂载"）。
- **按需物化**（materialize）留作可选（默认关），仅当用户要求可移植/防删除时使用。
- 哈希用 SHA256（与 file_artifacts / ADR-18 input_files / ref_databases 一致），
  用于完整性、去重与证据链；它是"指纹"不是"定位器"——原始数据删除后无法据此找回。
- 目录不能整体哈希 → 逐文件 SHA256 + 清单哈希（manifest_sha256）；同内容按清单哈希去重。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CHUNK = 8 * 1024 * 1024
_CLASS_RANK = {"D0": 0, "D1": 1, "D2": 2, "D3": 3, "D4": 4}

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS datasets (
        dataset_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        source_path TEXT NOT NULL,
        resolved_path TEXT NOT NULL,
        entries_json TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        total_size INTEGER NOT NULL,
        mtime TEXT NOT NULL,
        device INTEGER NOT NULL,
        inode INTEGER NOT NULL,
        data_class TEXT NOT NULL,
        registered_by TEXT NOT NULL,
        registered_at TEXT NOT NULL,
        status TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_datasets_manifest ON datasets(manifest_sha256)",
    "CREATE INDEX IF NOT EXISTS idx_datasets_resolved ON datasets(resolved_path)",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_sha256(entries: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x["relpath"]):
        h.update(f"{e['relpath']}\t{e['size']}\t{e['sha256']}\n".encode())
    return h.hexdigest()


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    kind: str  # "file" | "dir"
    source_path: str
    resolved_path: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    manifest_sha256: str = ""
    total_size: int = 0
    mtime: str = ""
    device: int = 0
    inode: int = 0
    data_class: str = "D3"
    registered_by: str = ""
    registered_at: str = ""
    status: str = "registered"  # registered | missing | changed

    @property
    def mount_guest(self) -> str:
        """沙箱内挂载点（容器后端）：目录挂到 /input/<id>，单文件挂到 /input/<id>/<name>。"""
        base = f"/input/{self.dataset_id}"
        return base if self.kind == "dir" else f"{base}/{Path(self.resolved_path).name}"


class DatasetRegistry:
    """数据集登记表（存 GOM 库，与 GOM 同库便于只读工具读取）。"""

    def __init__(self, db_path: Path | str) -> None:
        from bacmap.store.genome_object_service import ensure_gom_schema

        self.db_path = Path(db_path)
        ensure_gom_schema(db_path)  # 与 GOM 共用 gom.sqlite 的按文件迁移清单
        self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        for ddl in _SCHEMA:
            self._conn.execute(ddl)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DatasetRegistry:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    # ------------------------------------------------------------------ 登记
    def register(
        self, source_path: str | Path, *, registered_by: str, data_class: str = "D3"
    ) -> Dataset:
        """登记一份本地数据（零拷贝）：算逐文件 SHA256 + 清单哈希后入库。"""
        src = Path(source_path).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"dataset path not found: {src}")
        resolved = src.resolve()
        if resolved.is_dir():
            kind = "dir"
            files = sorted(p for p in resolved.rglob("*") if p.is_file())
        else:
            kind = "file"
            files = [resolved]
        if not files:
            raise ValueError(f"dataset path has no files: {resolved}")

        entries: list[dict[str, Any]] = []
        for f in files:
            st = f.stat()
            rel = str(f.relative_to(resolved)) if kind == "dir" else f.name
            entries.append({"relpath": rel, "size": st.st_size, "sha256": _sha256_file(f)})
        manifest = _manifest_sha256(entries)
        total = sum(int(e["size"]) for e in entries)

        existing = self._conn.execute(
            "SELECT dataset_id FROM datasets WHERE manifest_sha256 = ? AND status != 'missing'",
            (manifest,),
        ).fetchone()
        if existing:
            found = self.get(existing["dataset_id"])
            if found is None:  # pragma: no cover — 刚登记即读不回，库损坏
                raise RuntimeError(f"dataset {existing['dataset_id']} vanished after insert")
            # 内容去重不能降低数据级别：同一份内容先按 D3 登记、后按 D4 登记时，
            # 必须升到更敏感者（ADR-16：D4 不得因登记顺序被当成 D3 外发）。
            updates: list[str] = []
            values: list[object] = []
            if _CLASS_RANK.get(data_class, 0) > _CLASS_RANK.get(found.data_class, 0):
                updates.append("data_class = ?")
                values.append(data_class)
            if found.status != "registered":
                # 本次内容哈希与登记清单一致，说明此前 "changed" 已恢复。
                updates.append("status = 'registered'")
            if updates:
                values.append(found.dataset_id)
                self._conn.execute(
                    f"UPDATE datasets SET {', '.join(updates)} WHERE dataset_id = ?",  # noqa: S608
                    values,
                )
                found = self.get(found.dataset_id) or found
            return found  # 内容去重：同清单复用既有 dataset_id

        st = resolved.stat()
        dataset_id = f"ds-{manifest[:16]}"
        self._conn.execute(
            """INSERT OR REPLACE INTO datasets
               (dataset_id, kind, source_path, resolved_path, entries_json, manifest_sha256,
                total_size, mtime, device, inode, data_class, registered_by, registered_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                dataset_id,
                kind,
                str(src),
                str(resolved),
                json.dumps(entries, ensure_ascii=False),
                manifest,
                total,
                datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
                int(st.st_dev),
                int(st.st_ino),
                data_class,
                registered_by,
                datetime.now(UTC).isoformat(),
                "registered",
            ),
        )
        found = self.get(dataset_id)
        if found is None:  # pragma: no cover — 刚插入即读不回，库损坏
            raise RuntimeError(f"dataset {dataset_id} vanished after insert")
        return found

    # ------------------------------------------------------------------ 读取
    def get(self, dataset_id: str) -> Dataset | None:
        row = self._conn.execute(
            "SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)
        ).fetchone()
        return self._row(row) if row else None

    def list_all(self) -> list[Dataset]:
        rows = self._conn.execute(
            "SELECT * FROM datasets ORDER BY registered_at DESC"
        ).fetchall()
        return [self._row(r) for r in rows]

    def verify(self, dataset_id: str) -> bool:
        """重算清单并比对；路径缺失/内容变化时更新 status，返回是否与登记一致。"""
        ds = self.get(dataset_id)
        if ds is None:
            return False
        root = Path(ds.resolved_path)
        if not root.exists():
            self._set_status(dataset_id, "missing")
            return False
        files = (
            sorted(p for p in root.rglob("*") if p.is_file())
            if ds.kind == "dir"
            else ([root] if root.is_file() else [])
        )
        entries: list[dict[str, Any]] = []
        for f in files:
            st = f.stat()
            rel = str(f.relative_to(root)) if ds.kind == "dir" else f.name
            entries.append({"relpath": rel, "size": st.st_size, "sha256": _sha256_file(f)})
        ok = _manifest_sha256(entries) == ds.manifest_sha256
        self._set_status(dataset_id, "registered" if ok else "changed")
        return ok

    def _set_status(self, dataset_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE datasets SET status = ? WHERE dataset_id = ?", (status, dataset_id)
        )

    def mount_map(self, dataset_id: str) -> dict[str, str]:
        """宿主路径 → 容器内挂载点（供 SandboxSpec.readonly_mounts）。"""
        ds = self.get(dataset_id)
        if ds is None:
            raise KeyError(f"unknown dataset: {dataset_id}")
        return {ds.resolved_path: ds.mount_guest}

    def _row(self, row: sqlite3.Row) -> Dataset:
        return Dataset(
            dataset_id=row["dataset_id"],
            kind=row["kind"],
            source_path=row["source_path"],
            resolved_path=row["resolved_path"],
            entries=json.loads(row["entries_json"]),
            manifest_sha256=row["manifest_sha256"],
            total_size=int(row["total_size"]),
            mtime=row["mtime"],
            device=int(row["device"]),
            inode=int(row["inode"]),
            data_class=row["data_class"],
            registered_by=row["registered_by"],
            registered_at=row["registered_at"],
            status=row["status"],
        )
