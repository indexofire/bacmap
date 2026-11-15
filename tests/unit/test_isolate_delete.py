"""安全删除菌株（v1.10.33）：仅空菌株，有关联时拒绝。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.store.isolates import IsolateService
from bacmap.store.lab_results import LabResultService
from bacmap.store.strain_metadata import StrainMetadataService
from bacmap.workflow.samples_registry import delete_isolate, isolate_links


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    cfg = home / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform\tchecksum\tspecimen\n"
        "LIB-1\tSAL\t\t\t\ta.fasta\tISO-1\tilm\t\t\n",
        encoding="utf-8",
    )
    with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
        isolates.ensure("ISO-1")
        isolates.ensure("ISO-2")
    return home


def test_empty_isolate_can_be_deleted(tmp_path: Path):
    home = _home(tmp_path)
    assert isolate_links(home, "ISO-2") == {
        "libraries": 0,
        "metadata": 0,
        "lab_results": 0,
        "gom": 0,
        "runs": 0,
    }
    assert delete_isolate(home, "ISO-2")["deleted"] is True
    with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
        assert isolates.get("ISO-2") is None
    assert delete_isolate(home, "ISO-2")["deleted"] is False


def test_library_link_blocks_delete(tmp_path: Path):
    home = _home(tmp_path)
    with pytest.raises(ValueError, match="libraries=1"):
        delete_isolate(home, "ISO-1")
    with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
        assert isolates.get("ISO-1") is not None


def test_metadata_and_lab_links_block_delete(tmp_path: Path):
    home = _home(tmp_path)
    db = home / "data" / "bacmap.sqlite"
    with StrainMetadataService(db) as meta:
        meta.upsert("ISO-2", {"province": "ZJ"})
    with pytest.raises(ValueError, match="metadata=1"):
        delete_isolate(home, "ISO-2")
    with StrainMetadataService(db) as meta:
        meta.delete("ISO-2")
    with LabResultService(db) as lab:
        lab.add("ISO-2", "antimicrobial", "meropenem", "R")
    with pytest.raises(ValueError, match="lab_results=1"):
        delete_isolate(home, "ISO-2")


def test_gom_and_run_links_block_delete(tmp_path: Path):
    home = _home(tmp_path)
    import sqlite3

    gom = home / "gom.sqlite"
    with sqlite3.connect(gom) as conn:
        conn.execute(
            "CREATE TABLE strain_genotype_index (strain_id TEXT PRIMARY KEY,"
            " organism TEXT, species TEXT, serotype TEXT, serotype_method TEXT,"
            " mlst_scheme TEXT, mlst_st TEXT, plasmid_types TEXT, object_id TEXT,"
            " analysis_date TEXT, pipeline_version TEXT, updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE genome_objects (object_id TEXT, strain_id TEXT)"
        )
        conn.execute("INSERT INTO strain_genotype_index (strain_id) VALUES ('ISO-2')")
    with pytest.raises(ValueError, match="gom=1"):
        delete_isolate(home, "ISO-2")

    gom.unlink()
    runs = home / "runs.sqlite"
    with sqlite3.connect(runs) as conn:
        conn.execute(
            "CREATE TABLE analysis_runs (run_id TEXT, strain_ids TEXT)"
        )
        conn.execute(
            "INSERT INTO analysis_runs VALUES (?,?)",
            ("r1", '["ISO-2"]'),
        )
    with pytest.raises(ValueError, match="runs=1"):
        delete_isolate(home, "ISO-2")


def test_cli_delete_and_missing(tmp_path: Path, capsys):
    from bacmap.interfaces.cli import main as cli

    home = _home(tmp_path)
    cli.main(["isolate", "delete", "ISO-2", "--home", str(home)])
    assert "ISO-2" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["isolate", "delete", "ISO-2", "--home", str(home)])
    with pytest.raises(SystemExit):
        cli.main(["isolate", "delete", "ISO-1", "--home", str(home)])
