"""样本（specimen）身份模型 P1（v1.10.27）。

覆盖：影子样本迁移、SpecimenService、isolate↔specimen 关联、samples.tsv
specimen 列升级与 assign_specimens 补录、CLI 导入 TSV 解析。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.store import schema as store_schema
from bacmap.store.isolates import IsolateService
from bacmap.store.migrations import migrate
from bacmap.store.specimens import SpecimenService, validate_specimen_id


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "data" / "bacmap.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


def _legacy_db_with_isolate(tmp_path: Path, isolate_id: str = "HZCPE-01") -> Path:
    """模拟 v3 之前的库：只跑到迁移 2，然后直接插入一条 isolate。"""
    db = _db(tmp_path)
    migrate(db, store_schema.data_migrations()[:2])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO isolates (isolate_id, created_at, updated_at)"
            " VALUES (?,?,?)",
            (isolate_id, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
    return db


class TestShadowMigration:
    def test_legacy_isolates_get_shadow_specimen(self, tmp_path):
        db = _legacy_db_with_isolate(tmp_path)
        store_schema.ensure_data_schema(db)  # 应用迁移 3
        with SpecimenService(db) as specimens:
            row = specimens.get("HZCPE-01")
            assert row is not None
            assert row["origin"] == "legacy"
            assert specimens.isolates("HZCPE-01")[0]["specimen_id"] == "HZCPE-01"
        assert store_schema.data_migrations()[-1].version == 3

    def test_migration_is_idempotent(self, tmp_path):
        db = _legacy_db_with_isolate(tmp_path)
        store_schema.ensure_data_schema(db)
        store_schema.ensure_data_schema(db)  # 再跑一次不报错、不重复
        with SpecimenService(db) as specimens:
            assert len(specimens.list()) == 1


class TestSpecimenService:
    def test_ensure_get_list_and_isolate_count(self, tmp_path):
        db = _db(tmp_path)
        with SpecimenService(db) as specimens, IsolateService(db) as isolates:
            specimens.ensure("A03-SN-001")
            specimens.ensure("A03-SN-001", origin="external")  # 幂等
            row = specimens.get("A03-SN-001")
            assert row is not None and row["origin"] == ""
            isolates.ensure("A03-ISO-01", specimen_id="A03-SN-001")
            isolates.ensure("A03-ISO-02", specimen_id="A03-SN-001")
            listed = specimens.list()
            assert listed[0]["specimen_id"] == "A03-SN-001"
            assert listed[0]["n_isolates"] == 2
            assert [i["isolate_id"] for i in specimens.isolates("A03-SN-001")] == [
                "A03-ISO-01",
                "A03-ISO-02",
            ]

    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a b", "x" * 200])
    def test_invalid_ids_rejected(self, bad):
        assert validate_specimen_id(bad) is False

    def test_valid_ids(self):
        assert validate_specimen_id("A03-SN-001")
        assert validate_specimen_id("26SAL0501.spec_2")


class TestIsolateSpecimenLink:
    def test_ensure_sets_specimen_but_does_not_overwrite(self, tmp_path):
        db = _db(tmp_path)
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-1", specimen_id="SPEC-A")
            isolates.ensure("ISO-1", specimen_id="SPEC-B")  # 不覆盖已有样本
            assert isolates.get("ISO-1")["specimen_id"] == "SPEC-A"
            assert isolates.set_specimen("ISO-1", "SPEC-B") is True
            assert isolates.get("ISO-1")["specimen_id"] == "SPEC-B"
            assert isolates.set_specimen("NOPE", "SPEC-B") is False

    def test_isolate_without_specimen_allowed(self, tmp_path):
        db = _db(tmp_path)
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-2")
            assert isolates.get("ISO-2")["specimen_id"] is None


class TestAssignSpecimens:
    def _home(self, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        cfg = home / "workflows" / "bacmap" / "config"
        cfg.mkdir(parents=True)
        (cfg / "samples.tsv").write_text(
            "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform\tchecksum\n"
            "DS-1\tSAL\t\t\t\ta.fasta\tISO-1\tunknown\t\n"
            "DS-2\tSAL\t\t\t\tb.fasta\tISO-2\tunknown\t\n",
            encoding="utf-8",
        )
        with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
            isolates.ensure("ISO-1")
            isolates.ensure("ISO-2")
        return home

    def test_assign_updates_tsv_isolates_and_specimens(self, tmp_path):
        from bacmap.workflow.samples_registry import assign_specimens

        home = self._home(tmp_path)
        result = assign_specimens(home, {"DS-1": "A03-SN-001"}, by="dataset")
        assert result["updated"] == 1
        assert result["specimens"] == ["A03-SN-001"]
        assert result["missing"] == []
        tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
        header = tsv.read_text().splitlines()[0].split("\t")
        assert "specimen" in header
        assert "A03-SN-001" in tsv.read_text()
        with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
            assert isolates.get("ISO-1")["specimen_id"] == "A03-SN-001"
            assert isolates.get("ISO-2")["specimen_id"] is None
        with SpecimenService(home / "data" / "bacmap.sqlite") as specimens:
            assert specimens.get("A03-SN-001") is not None

    def test_assign_reports_missing_and_accepts_isolate_key(self, tmp_path):
        from bacmap.workflow.samples_registry import assign_specimens

        home = self._home(tmp_path)
        result = assign_specimens(
            home, {"ISO-2": "A03-SN-002", "NOPE": "A03-SN-003"}, by="isolate"
        )
        assert result["updated"] == 1
        assert result["missing"] == ["NOPE"]
        with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
            assert isolates.get("ISO-2")["specimen_id"] == "A03-SN-002"


class TestDeleteSpecimen:
    """删除样本（v1.10.27）：默认仅空样本；force 先解除关联，不删菌株/数据。"""

    def test_delete_empty_specimen(self, tmp_path):
        db = _db(tmp_path)
        with SpecimenService(db) as specimens:
            specimens.ensure("A03-SN-001")
            result = specimens.delete("A03-SN-001")
            assert result == {"deleted": True, "unlinked_isolates": 0}
            assert specimens.get("A03-SN-001") is None

    def test_linked_specimen_requires_force(self, tmp_path):
        db = _db(tmp_path)
        with SpecimenService(db) as specimens, IsolateService(db) as isolates:
            specimens.ensure("A03-SN-001")
            isolates.ensure("ISO-1", specimen_id="A03-SN-001")
            with pytest.raises(ValueError, match="linked isolate"):
                specimens.delete("A03-SN-001")
            # 拒绝时不动任何数据
            assert specimens.get("A03-SN-001") is not None
            assert isolates.get("ISO-1")["specimen_id"] == "A03-SN-001"

    def test_force_unlinks_isolates_and_keeps_them(self, tmp_path):
        db = _db(tmp_path)
        with SpecimenService(db) as specimens, IsolateService(db) as isolates:
            specimens.ensure("A03-SN-001")
            isolates.ensure("ISO-1", specimen_id="A03-SN-001")
            isolates.ensure("ISO-2", specimen_id="A03-SN-001")
            result = specimens.delete("A03-SN-001", force=True)
            assert result == {"deleted": True, "unlinked_isolates": 2}
            assert specimens.get("A03-SN-001") is None
            # 菌株仍在，只是失去样本归属
            assert isolates.get("ISO-1")["specimen_id"] is None
            assert isolates.get("ISO-2")["specimen_id"] is None

    def test_missing_specimen_reports_not_deleted(self, tmp_path):
        db = _db(tmp_path)
        with SpecimenService(db) as specimens:
            assert specimens.delete("NOPE") == {"deleted": False, "unlinked_isolates": 0}

    def test_registry_delete_clears_tsv_specimen_cells(self, tmp_path):
        from bacmap.workflow.samples_registry import assign_specimens, delete_specimen

        home = TestAssignSpecimens()._home(tmp_path)
        assign_specimens(home, {"DS-1": "A03-SN-001"}, by="dataset")
        result = delete_specimen(home, "A03-SN-001", force=True)
        assert result["deleted"] is True
        assert result["unlinked_isolates"] == 1
        assert result["updated_tsv_rows"] == 1
        tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
        text = tsv.read_text()
        assert "A03-SN-001" not in text
        # 测序数据行本身仍在
        assert "DS-1" in text
        with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
            assert isolates.get("ISO-1")["specimen_id"] is None

    def test_registry_delete_rejects_linked_without_force(self, tmp_path):
        from bacmap.workflow.samples_registry import assign_specimens, delete_specimen

        home = TestAssignSpecimens()._home(tmp_path)
        assign_specimens(home, {"DS-1": "A03-SN-001"}, by="dataset")
        with pytest.raises(ValueError):
            delete_specimen(home, "A03-SN-001")


class TestDeleteCli:
    """``bacmap specimen delete``：解析与端到端（--home 指向临时根）。"""

    def _run(self, capsys, *argv: str) -> str:
        import bacmap.interfaces.cli.main as cli

        cli.main(list(argv))
        return capsys.readouterr().out

    def test_delete_empty_specimen(self, tmp_path, capsys):
        db = tmp_path / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("A03-SN-001")
        out = self._run(
            capsys, "specimen", "delete", "A03-SN-001", "--home", str(tmp_path)
        )
        assert "A03-SN-001" in out
        with SpecimenService(db) as specimens:
            assert specimens.get("A03-SN-001") is None

    def test_linked_without_force_exits(self, tmp_path):
        import bacmap.interfaces.cli.main as cli

        db = tmp_path / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens, IsolateService(db) as isolates:
            specimens.ensure("A03-SN-001")
            isolates.ensure("ISO-1", specimen_id="A03-SN-001")
        with pytest.raises(SystemExit):
            cli.main(["specimen", "delete", "A03-SN-001", "--home", str(tmp_path)])
        with SpecimenService(db) as specimens:
            assert specimens.get("A03-SN-001") is not None

    def test_missing_specimen_exits(self, tmp_path):
        import bacmap.interfaces.cli.main as cli

        with pytest.raises(SystemExit):
            cli.main(["specimen", "delete", "NOPE", "--home", str(tmp_path)])


class TestImportTsv:
    def test_dataset_mapping(self, tmp_path):
        from bacmap.interfaces.cli.specimens import _read_assignments

        path = tmp_path / "map.tsv"
        path.write_text("specimen\tdataset\nA03-SN-001\tDS-1\nA03-SN-001\tDS-2\n")
        assert _read_assignments(path, "dataset") == {
            "DS-1": "A03-SN-001",
            "DS-2": "A03-SN-001",
        }

    def test_sample_header_accepted_and_isolate_mode(self, tmp_path):
        from bacmap.interfaces.cli.specimens import _read_assignments

        path = tmp_path / "map.tsv"
        path.write_text("specimen\tsample\nA03-SN-001\tDS-1\n")
        assert _read_assignments(path, "dataset") == {"DS-1": "A03-SN-001"}
        path.write_text("specimen\tisolate\nA03-SN-001\tISO-1\n")
        assert _read_assignments(path, "isolate") == {"ISO-1": "A03-SN-001"}

    def test_bad_header_rejected(self, tmp_path):
        from bacmap.interfaces.cli.specimens import _read_assignments

        path = tmp_path / "map.tsv"
        path.write_text("specimen\tfoo\nA03-SN-001\tDS-1\n")
        with pytest.raises(SystemExit):
            _read_assignments(path, "dataset")
