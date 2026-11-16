"""全库统计的物种分层（v1.10.27）：物种优先，型别/耐药在物种之下。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _gom(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "gom.sqlite")
    conn.execute(
        "CREATE TABLE strain_genotype_index ("
        "strain_id TEXT PRIMARY KEY, species TEXT, serotype TEXT, mlst_st TEXT)"
    )
    conn.execute(
        "CREATE TABLE strain_amr_genes ("
        "strain_id TEXT, gene_name TEXT, database TEXT)"
    )
    conn.executemany(
        "INSERT INTO strain_genotype_index VALUES (?,?,?,?)",
        [
            ("S1", "Salmonella", "Enteritidis", "ST11"),
            ("S2", "Salmonella", "N/A", "ST11"),
            ("V1", "Vibrio_parahaemolyticus", "O3:K6", "ST3"),
        ],
    )
    conn.executemany(
        "INSERT INTO strain_amr_genes VALUES (?,?,?)",
        [
            ("S1", "blaCTX-M", "card"),
            ("S2", "blaCTX-M", "card"),
            ("V1", "tdh", "vfdb"),
        ],
    )
    conn.commit()
    conn.close()


def _data(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "bacmap.sqlite")
    conn.execute("CREATE TABLE isolates (isolate_id TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT INTO isolates VALUES (?)", [("I1",), ("I2",), ("I3",), ("I4",)]
    )
    conn.commit()
    conn.close()


def test_species_breakdown_groups_mlst_serotype_amr(tmp_path: Path):
    from bacmap.interfaces.stats_summary import gather_stats

    _gom(tmp_path)
    _data(tmp_path)
    stats = gather_stats(tmp_path)
    by_species = {group["name"]: group for group in stats["strains"]["by_species"]}
    assert by_species["Salmonella"]["count"] == 2
    assert by_species["Salmonella"]["mlst"][0] == {"name": "ST11", "count": 2}
    assert by_species["Salmonella"]["amr_top"][0] == {"name": "blaCTX-M", "count": 2}
    # VFDB 毒力基因独立成组，不混入耐药 Top
    assert all(row["name"] != "tdh" for row in by_species["Salmonella"]["amr_top"])
    assert by_species["Vibrio_parahaemolyticus"]["virulence_top"] == [
        {"name": "tdh", "count": 1}
    ]
    # 全库字段保留（CLI/兼容）
    assert stats["strains"]["species"][0]["name"] == "Salmonella"
    # v1.10.40：已分析/已入库（strain_genotype_index）与已登记（isolates）分开口径
    assert stats["strains"]["total"] == 3
    assert stats["strains"]["registered"] == 4
