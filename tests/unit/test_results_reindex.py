"""``bacmap results reindex``：历史 final summary → strain_genotype_index 回填。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bacmap.interfaces.cli import ops
from bacmap.store.strain_index import StrainGenotypeIndex


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    rep = home / "results" / "S1" / "report"
    rep.mkdir(parents=True)
    (rep / "S1_summary.json").write_text(
        json.dumps(
            {
                "pipeline_version": "test-v1",
                "steps": {
                    "species": {"species": "Vibrio_parahaemolyticus"},
                    "mlst": {"st": "ST3", "scheme": "vparahaemolyticus_1", "alleles": {}},
                    "serotype": {"value": "O10:K4", "method": "gspec vpa_ok", "o_antigen": "O10"},
                    "amr": {"abricate_card": [{"GENE": "blaCTX-M"}]},
                    "plasmid": {},
                },
            }
        ),
        encoding="utf-8",
    )
    return home


def _args(
    home: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    backfill_metadata: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        home=str(home),
        dry_run=dry_run,
        force=force,
        backfill_metadata=backfill_metadata,
        json=True,
    )


def test_reindex_backfills_and_skips_existing(tmp_path: Path, capsys):
    home = _home(tmp_path)
    ops.results_reindex(_args(home))
    out = json.loads(capsys.readouterr().out)
    assert out["indexed"] == 1 and out["failed"] == 0

    db = home / "gom.sqlite"
    with StrainGenotypeIndex(db) as idx:
        profile = idx.get_profile("S1")
        assert profile is not None
        assert profile["species"] == "Vibrio_parahaemolyticus"
        assert profile["mlst_st"] == "ST3"

    ops.results_reindex(_args(home))
    out = json.loads(capsys.readouterr().out)
    assert out["indexed"] == 0 and out["skipped_existing"] == 1

    ops.results_reindex(_args(home, force=True))
    out = json.loads(capsys.readouterr().out)
    assert out["indexed"] == 1


def test_reindex_dry_run_does_not_write(tmp_path: Path, capsys):
    home = _home(tmp_path)
    ops.results_reindex(_args(home, dry_run=True))
    out = json.loads(capsys.readouterr().out)
    assert out["indexed"] == 1 and out["dry_run"] is True
    with StrainGenotypeIndex(home / "gom.sqlite") as idx:
        assert idx.get_profile("S1") is None


def test_reindex_backfills_new_metadata_without_losing_gom_links(
    tmp_path: Path, capsys
):
    """v1.10.49 升级：只补 specimen/isolate/组装指标，不覆盖 object_id/分型。"""
    import sqlite3

    from bacmap.store.isolates import IsolateService
    from bacmap.store.specimens import SpecimenService

    home = _home(tmp_path)
    (home / "workflows" / "bacmap" / "config").mkdir(parents=True)
    (home / "workflows" / "bacmap" / "config" / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
        "\tchecksum\tspecimen\n"
        "S1\tvpa\t\t\t\t\tISO-1\tilm\t\tSP-1\n",
        encoding="utf-8",
    )
    with SpecimenService(home / "data" / "bacmap.sqlite") as specimens:
        specimens.ensure("SP-1", owner_user_id="alice")
    with IsolateService(home / "data" / "bacmap.sqlite") as isolates:
        isolates.ensure("ISO-1", specimen_id="SP-1", owner_user_id="alice")
    ops.results_reindex(_args(home))
    capsys.readouterr()
    db = home / "gom.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE strain_genotype_index SET object_id='analysis:S1:run1',"
            " pipeline_version='v1', specimen_id=NULL, isolate_id=NULL,"
            " genome_size=NULL, owner_user_id=NULL WHERE strain_id='S1'"
        )
    ops.results_reindex(_args(home, backfill_metadata=True))
    out = json.loads(capsys.readouterr().out)
    assert out["backfilled_metadata"] == 1 and out["indexed"] == 0
    with StrainGenotypeIndex(db) as idx:
        profile = idx.get_profile("S1")
        assert profile is not None
        assert profile["object_id"] == "analysis:S1:run1"
        assert profile["pipeline_version"] == "v1"
        assert profile["specimen_id"] == "SP-1"
        assert profile["isolate_id"] == "ISO-1"
        assert profile["owner_user_id"] == "alice"
