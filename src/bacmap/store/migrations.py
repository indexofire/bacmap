"""SQLite schema 迁移（ADR-13：``PRAGMA user_version`` + 编号迁移）。

每个库声明一组编号连续（自 1 起）的迁移；``migrate`` 在单个 ``BEGIN IMMEDIATE``
事务中按序执行所有高于当前 ``user_version`` 的迁移并推进版本号：

- 幂等：重复调用无副作用（版本已最新即直接返回）；
- 并发安全：IMMEDIATE 事务串行化多进程同时启动的迁移；
- 先备份：已有数据的库在执行迁移前用 SQLite backup API 复制为
  ``<db>.bak-v<当前版本>``，迁移失败整体回滚、旧库不变；
- 拒绝降级：库版本高于代码已知最高版本时抛错（防止旧代码写新库）。

基线迁移（版本 1）使用 ``CREATE TABLE IF NOT EXISTS``，因此早于迁移机制
创建的库（``user_version = 0`` 但表已存在）可无损纳管。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


class MigrationError(RuntimeError):
    """迁移声明非法或库版本与代码不兼容。"""


def _validate(migrations: Sequence[Migration]) -> int:
    expected = 1
    for m in migrations:
        if m.version != expected:
            raise MigrationError(
                f"migrations must be numbered consecutively from 1: got {m.version} "
                f"where {expected} was expected ({m.name})"
            )
        expected += 1
    return expected - 1


def schema_version(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()
    return int(row[0]) > 0


def _backup(conn: sqlite3.Connection, db_path: Path, current: int) -> Path:
    target = db_path.with_name(f"{db_path.name}.bak-v{current}")
    with sqlite3.connect(target) as dst:
        conn.backup(dst)
    return target


def migrate(db_path: Path, migrations: Sequence[Migration]) -> int:
    """把 ``db_path`` 迁移到最新版本，返回迁移后的版本号。"""
    latest = _validate(migrations)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current > latest:
            raise MigrationError(
                f"{db_path.name} schema version {current} is newer than this bacmap "
                f"(knows up to {latest}); refusing to open"
            )
        if current == latest:
            return current
        # 备份在写事务之外进行（backup API 自身取一致快照）；随后在 IMMEDIATE
        # 事务内复核版本——并发进程已完成迁移时直接返回。
        if _has_tables(conn):
            _backup(conn, db_path, current)
        conn.execute("BEGIN IMMEDIATE")
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current >= latest:
            conn.execute("COMMIT")
            if current > latest:
                raise MigrationError(f"{db_path.name} was upgraded concurrently to {current}")
            return current
        try:
            for m in migrations[current:]:
                for stmt in m.statements:
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {latest:d}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return latest
    finally:
        conn.close()
