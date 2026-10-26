"""schema 迁移框架（ADR-13 v1.5：PRAGMA user_version + 编号迁移）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.store.migrations import Migration, MigrationError, migrate, schema_version
from bacmap.tasks.spec import TASKS_MIGRATIONS

M1 = Migration(1, "t", ("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)",))
M2 = Migration(2, "t.extra", ("ALTER TABLE t ADD COLUMN extra TEXT NOT NULL DEFAULT ''",))


def _columns(db: Path, table: str) -> list[str]:
    with sqlite3.connect(db) as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


class TestMigrate:
    def test_fresh_db_reaches_latest_without_backup(self, tmp_path: Path):
        db = tmp_path / "x.sqlite"
        assert migrate(db, (M1, M2)) == 2
        assert schema_version(db) == 2
        assert _columns(db, "t") == ["id", "v", "extra"]
        assert not list(tmp_path.glob("*.bak-*"))

    def test_idempotent(self, tmp_path: Path):
        db = tmp_path / "x.sqlite"
        migrate(db, (M1, M2))
        assert migrate(db, (M1, M2)) == 2
        assert _columns(db, "t") == ["id", "v", "extra"]

    def test_incremental_upgrade_backs_up_and_keeps_rows(self, tmp_path: Path):
        db = tmp_path / "x.sqlite"
        migrate(db, (M1,))
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO t (v) VALUES ('keep')")
        assert migrate(db, (M1, M2)) == 2
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT v, extra FROM t").fetchall() == [("keep", "")]
        backup = tmp_path / "x.sqlite.bak-v1"
        assert backup.is_file()
        assert schema_version(backup) == 1
        assert _columns(backup, "t") == ["id", "v"]

    def test_legacy_db_without_version_is_adopted(self, tmp_path: Path):
        """早于迁移机制的库（user_version=0、表已存在）由基线迁移无损纳管。"""
        db = tmp_path / "x.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            conn.execute("INSERT INTO t (v) VALUES ('old')")
        assert migrate(db, (M1,)) == 1
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT v FROM t").fetchall() == [("old",)]
        assert (tmp_path / "x.sqlite.bak-v0").is_file()

    def test_failed_migration_rolls_back(self, tmp_path: Path):
        db = tmp_path / "x.sqlite"
        migrate(db, (M1,))
        bad = Migration(2, "bad", ("ALTER TABLE t ADD COLUMN ok TEXT", "NOT VALID SQL"))
        with pytest.raises(sqlite3.OperationalError):
            migrate(db, (M1, bad))
        assert schema_version(db) == 1
        assert _columns(db, "t") == ["id", "v"]

    def test_refuses_newer_db(self, tmp_path: Path):
        db = tmp_path / "x.sqlite"
        migrate(db, (M1, M2))
        with pytest.raises(MigrationError, match="newer"):
            migrate(db, (M1,))

    def test_rejects_non_consecutive_numbering(self, tmp_path: Path):
        with pytest.raises(MigrationError, match="consecutively"):
            migrate(tmp_path / "x.sqlite", (M1, Migration(3, "gap", ())))


class TestTasksDb:
    def test_engine_tables_are_versioned(self, tmp_path: Path):
        db = tmp_path / "tasks.sqlite"
        assert migrate(db, TASKS_MIGRATIONS) == len(TASKS_MIGRATIONS)
        assert "submitted_by" in _columns(db, "tasks")
        assert "approver" in _columns(db, "approvals")


class TestOwnedStoresVersioned:
    """v1.5.2：单一属主的库纳入迁移框架（runs.sqlite / baseline.sqlite）。"""

    def test_baseline_db_versioned(self, tmp_path: Path):
        from bacmap.store import baseline

        db = tmp_path / "baseline.sqlite"
        baseline.save_candidate(db, "t1", {"strains": []}, {"verdict": "pass"})
        assert schema_version(db) == len(baseline.BASELINE_MIGRATIONS) >= 1
        assert baseline.load_candidate(db, "t1")["gate"] == {"verdict": "pass"}
        assert baseline.list_releases(db) == []

    def test_legacy_baseline_db_adopted(self, tmp_path: Path):
        from bacmap.store import baseline

        db = tmp_path / "baseline.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute(baseline.CANDIDATES_DDL)
            conn.execute(
                "INSERT INTO baseline_candidates VALUES ('old', '{}', '{}', 'x')"
            )
        assert baseline.load_candidate(db, "old") == {"manifest": {}, "gate": {}}
        assert schema_version(db) == 1

    def test_runs_db_versioned(self, tmp_path: Path):
        from bacmap.store import runs

        db = tmp_path / "runs.sqlite"
        assert runs.read_run("nope", db) is None
        assert schema_version(db) == len(runs.RUNS_MIGRATIONS) >= 1


class TestGomFileVersioned:
    """v1.5.2：gom.sqlite（GOM 对象/事件/产物 + 数据集登记共用一个文件）按文件统一迁移清单。"""

    def _tables(self, db: Path) -> set[str]:
        with sqlite3.connect(db) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_gom_service_versions_file(self, tmp_path: Path):
        from bacmap.store.genome_object_service import GOM_MIGRATIONS, GenomeObjectService

        db = tmp_path / "gom.sqlite"
        GenomeObjectService(db).close()
        assert schema_version(db) == len(GOM_MIGRATIONS)
        assert {"genome_objects", "events", "file_artifacts", "datasets"} <= self._tables(db)

    def test_dataset_registry_uses_same_list(self, tmp_path: Path):
        from bacmap.store.datasets import DatasetRegistry
        from bacmap.store.genome_object_service import GOM_MIGRATIONS

        db = tmp_path / "gom.sqlite"
        DatasetRegistry(db).close()
        assert schema_version(db) == len(GOM_MIGRATIONS)
        assert "genome_objects" in self._tables(db)

    def test_legacy_gom_adopted_with_data(self, tmp_path: Path):
        from bacmap.store import genome_object_service as gos

        db = tmp_path / "gom.sqlite"
        with sqlite3.connect(db) as conn:
            for ddl in gos._SCHEMA_SQL:
                conn.execute(ddl)
            conn.execute(
                "INSERT INTO events VALUES ('e1', 'o1', 'uploaded', '{}', 'x')"
            )
        gos.GenomeObjectService(db).close()
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT event_id FROM events").fetchall() == [("e1",)]
        assert schema_version(db) == len(gos.GOM_MIGRATIONS) == 2
        assert (tmp_path / "gom.sqlite.bak-v0").is_file()


class TestDataDbVersioned:
    """v1.6：data/bacmap.sqlite 由菌株索引/元数据/检验三个服务共用 → 按文件统一清单。"""

    def _tables(self, db: Path) -> set[str]:
        with sqlite3.connect(db) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_shared_file_gets_all_tables_and_version(self, tmp_path: Path):
        from bacmap.store.lab_results import LabResultService
        from bacmap.store.schema import data_migrations
        from bacmap.store.strain_metadata import StrainMetadataService

        db = tmp_path / "bacmap.sqlite"
        StrainMetadataService(db).close()
        LabResultService(db).close()
        assert schema_version(db) == len(data_migrations()) >= 1
        assert {"strain_metadata", "lab_results"} <= self._tables(db)
        assert "strain_genotype_index" not in self._tables(db)  # 索引在 gom.sqlite

    def test_legacy_data_db_adopted_with_rows(self, tmp_path: Path):
        from bacmap.store import lab_results, strain_metadata

        db = tmp_path / "bacmap.sqlite"
        with sqlite3.connect(db) as conn:
            for ddl in (*strain_metadata.DDL_STATEMENTS, *lab_results.DDL_STATEMENTS):
                conn.execute(ddl)
            conn.execute(
                "INSERT INTO strain_metadata (strain_id, sample_id, created_at, updated_at)"
                " VALUES ('S1','S1','x','x')"
            )
        assert strain_metadata.StrainMetadataService(db).get("S1") is not None
        from bacmap.store.schema import data_migrations

        assert schema_version(db) == len(data_migrations()) == 2
        assert (tmp_path / "bacmap.sqlite.bak-v0").is_file()


class TestGomHoldsStrainIndex:
    def test_index_shares_gom_file(self, tmp_path: Path):
        from bacmap.store.genome_object_service import GOM_MIGRATIONS
        from bacmap.store.strain_index import StrainGenotypeIndex

        db = tmp_path / "gom.sqlite"
        StrainGenotypeIndex(db).upsert(strain_id="S1", organism="SAL")
        assert schema_version(db) == len(GOM_MIGRATIONS) == 2
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT strain_id FROM strain_genotype_index").fetchall() == [
                ("S1",)
            ]
            assert conn.execute("SELECT count(*) FROM genome_objects").fetchone()[0] == 0


class TestKnowledgeDbVersioned:
    def test_versioned_and_fts_works(self, tmp_path: Path):
        from bacmap.store.knowledge import KnowledgeStore
        from bacmap.store.schema import knowledge_migrations

        db = tmp_path / "knowledge.sqlite"
        store = KnowledgeStore(db)
        store.import_candidate(
            {"title": "Salmonella outbreak", "content": "cluster in 2025"}, imported_by="t"
        )
        assert schema_version(db) == len(knowledge_migrations()) == 1
        assert store.search("Salmonella"), "FTS 触发器必须随迁移建好"

    def test_legacy_knowledge_adopted(self, tmp_path: Path):
        from bacmap.store import knowledge

        db = tmp_path / "knowledge.sqlite"
        with sqlite3.connect(db) as conn:
            conn.executescript(knowledge.LEGACY_DDL)
        store = knowledge.KnowledgeStore(db)
        assert schema_version(db) == 1
        assert store.search("anything") == []
