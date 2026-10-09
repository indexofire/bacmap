from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bacmap.core.utils import parse_mlst


@dataclass
class GenotypeMatch:
    strain_id: str
    organism: str
    species: str
    serotype: str
    serotype_method: str
    mlst_scheme: str
    mlst_st: str
    amr_genes: list[str] = field(default_factory=list)
    match_reasons: list[str] = field(default_factory=list)
    object_id: str = ""
    analysis_date: str = ""


_DDL = [
    """CREATE TABLE IF NOT EXISTS strain_genotype_index (
        strain_id           TEXT PRIMARY KEY,
        organism            TEXT,
        species             TEXT,
        serotype            TEXT,
        serotype_method     TEXT,
        mlst_scheme         TEXT,
        mlst_st             TEXT,
        plasmid_types       TEXT,
        object_id           TEXT,
        analysis_date       TEXT,
        pipeline_version    TEXT,
        updated_at          TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_gi_serotype ON strain_genotype_index(serotype)""",
    """CREATE INDEX IF NOT EXISTS idx_gi_mlst_st ON strain_genotype_index(mlst_st)""",
    """CREATE INDEX IF NOT EXISTS idx_gi_organism ON strain_genotype_index(organism)""",
    """CREATE INDEX IF NOT EXISTS idx_gi_species ON strain_genotype_index(species)""",
    """CREATE TABLE IF NOT EXISTS strain_amr_genes (
        strain_id   TEXT NOT NULL,
        gene_name   TEXT NOT NULL,
        database    TEXT NOT NULL DEFAULT '',
        coverage    REAL,
        identity    REAL,
        product     TEXT,
        PRIMARY KEY (strain_id, gene_name, database)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_ag_gene ON strain_amr_genes(gene_name)""",
    """CREATE INDEX IF NOT EXISTS idx_ag_strain ON strain_amr_genes(strain_id)""",
]


class StrainGenotypeIndex:
    def __init__(self, db_path: str | Path) -> None:
        self._conn: sqlite3.Connection = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        for ddl in _DDL:
            self._conn.execute(ddl)
        self._conn.commit()

    def upsert(
        self,
        *,
        strain_id: str,
        organism: str = "",
        species: str = "",
        serotype: str = "",
        serotype_method: str = "",
        mlst_scheme: str = "",
        mlst_st: str = "",
        plasmid_types: list[str] | None = None,
        amr_genes: list[dict[str, Any]] | None = None,
        object_id: str = "",
        analysis_date: str = "",
        pipeline_version: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()  # noqa: UP017
        self._conn.execute(
            """INSERT INTO strain_genotype_index
               (strain_id, organism, species, serotype, serotype_method,
                mlst_scheme, mlst_st, plasmid_types, object_id,
                analysis_date, pipeline_version, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(strain_id) DO UPDATE SET
                 organism=excluded.organism,
                 species=excluded.species,
                 serotype=excluded.serotype,
                 serotype_method=excluded.serotype_method,
                 mlst_scheme=excluded.mlst_scheme,
                 mlst_st=excluded.mlst_st,
                 plasmid_types=excluded.plasmid_types,
                 object_id=excluded.object_id,
                 analysis_date=excluded.analysis_date,
                 pipeline_version=excluded.pipeline_version,
                 updated_at=excluded.updated_at""",
            (
                strain_id,
                organism,
                species,
                serotype,
                serotype_method,
                mlst_scheme,
                mlst_st,
                json.dumps(plasmid_types or []),
                object_id,
                analysis_date,
                pipeline_version,
                now,
            ),
        )

        self._conn.execute(
            "DELETE FROM strain_amr_genes WHERE strain_id = ?",
            (strain_id,),
        )
        if amr_genes:
            for g in amr_genes:
                gene = g.get("gene", "").strip()
                if not gene:
                    continue
                self._conn.execute(
                    """INSERT OR IGNORE INTO strain_amr_genes
                       (strain_id, gene_name, database, coverage, identity, product)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        strain_id,
                        gene,
                        g.get("database", ""),
                        float(g.get("coverage", 0)),
                        float(g.get("identity", 0)),
                        g.get("product", "")[:200],
                    ),
                )
        self._conn.commit()

    def search(
        self,
        *,
        serotype: str | None = None,
        mlst_st: str | None = None,
        amr_gene: str | None = None,
        organism: str | None = None,
        species: str | None = None,
        limit: int = 50,
    ) -> list[GenotypeMatch]:
        conditions: list[str] = []
        params: list[Any] = []
        amr_join = ""

        if serotype:
            conditions.append("g.serotype = ?")
            params.append(serotype)
        if mlst_st:
            normalized_st = mlst_st.upper().replace(" ", "")
            if not normalized_st.startswith("ST"):
                normalized_st = "ST" + normalized_st
            conditions.append("UPPER(g.mlst_st) = ?")
            params.append(normalized_st)
        if organism:
            conditions.append("g.organism LIKE ?")
            params.append(f"%{organism}%")
        if species:
            conditions.append("g.species = ?")
            params.append(species)
        if amr_gene:
            amr_join = " INNER JOIN strain_amr_genes ag ON ag.strain_id = g.strain_id"
            conditions.append("ag.gene_name = ?")
            params.append(amr_gene)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = (
            "SELECT DISTINCT g.* FROM strain_genotype_index g"
            + amr_join
            + where
            + " ORDER BY g.analysis_date DESC LIMIT ?"
        )
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        results: list[GenotypeMatch] = []
        for row in rows:
            genes = [
                r["gene_name"]
                for r in self._conn.execute(
                    "SELECT gene_name FROM strain_amr_genes WHERE strain_id = ?",
                    (row["strain_id"],),
                ).fetchall()
            ]
            results.append(
                GenotypeMatch(
                    strain_id=row["strain_id"],
                    organism=row["organism"] or "",
                    species=row["species"] or "",
                    serotype=row["serotype"] or "",
                    serotype_method=row["serotype_method"] or "",
                    mlst_scheme=row["mlst_scheme"] or "",
                    mlst_st=row["mlst_st"] or "",
                    amr_genes=genes,
                    object_id=row["object_id"] or "",
                    analysis_date=row["analysis_date"] or "",
                )
            )
        return results

    def find_similar(
        self,
        strain_id: str,
        *,
        match_serotype: bool = True,
        match_mlst: bool = True,
        match_amr: bool = False,
        limit: int = 50,
    ) -> list[GenotypeMatch]:
        row = self._conn.execute(
            "SELECT * FROM strain_genotype_index WHERE strain_id = ?",
            (strain_id,),
        ).fetchone()
        if not row:
            return []

        conditions: list[str] = ["g.strain_id != ?"]
        params: list[Any] = [strain_id]

        if match_serotype and row["serotype"]:
            conditions.append("g.serotype = ?")
            params.append(row["serotype"])
        if match_mlst and row["mlst_st"]:
            conditions.append("UPPER(g.mlst_st) = ?")
            params.append(row["mlst_st"].upper())

        sql = (
            "SELECT DISTINCT g.* FROM strain_genotype_index g"
            + " WHERE "
            + " AND ".join(conditions)
            + " ORDER BY g.analysis_date DESC LIMIT ?"
        )
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        results: list[GenotypeMatch] = []
        for r in rows:
            reasons: list[str] = []
            if match_serotype and r["serotype"] == row["serotype"]:
                reasons.append(f"serotype={r['serotype']}")
            if match_mlst and (r["mlst_st"] or "").upper() == (row["mlst_st"] or "").upper():
                reasons.append(f"MLST ST={r['mlst_st']}")

            genes = [
                gr["gene_name"]
                for gr in self._conn.execute(
                    "SELECT gene_name FROM strain_amr_genes WHERE strain_id = ?",
                    (r["strain_id"],),
                ).fetchall()
            ]
            if match_amr:
                my_genes = {
                    gr["gene_name"]
                    for gr in self._conn.execute(
                        "SELECT gene_name FROM strain_amr_genes WHERE strain_id = ?",
                        (strain_id,),
                    ).fetchall()
                }
                shared = set(genes) & my_genes
                if shared:
                    reasons.append(f"shared AMR: {', '.join(sorted(shared)[:5])}")

            results.append(
                GenotypeMatch(
                    strain_id=r["strain_id"],
                    organism=r["organism"] or "",
                    species=r["species"] or "",
                    serotype=r["serotype"] or "",
                    serotype_method=r["serotype_method"] or "",
                    mlst_scheme=r["mlst_scheme"] or "",
                    mlst_st=r["mlst_st"] or "",
                    amr_genes=genes,
                    match_reasons=reasons,
                    object_id=r["object_id"] or "",
                    analysis_date=r["analysis_date"] or "",
                )
            )
        return results

    def get_profile(self, strain_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM strain_genotype_index WHERE strain_id = ?",
            (strain_id,),
        ).fetchone()
        if not row:
            return None
        genes = [
            {
                "gene": r["gene_name"],
                "database": r["database"],
                "coverage": r["coverage"],
                "identity": r["identity"],
            }
            for r in self._conn.execute(
                "SELECT * FROM strain_amr_genes WHERE strain_id = ? ORDER BY gene_name",
                (strain_id,),
            ).fetchall()
        ]
        return {
            "strain_id": row["strain_id"],
            "organism": row["organism"],
            "species": row["species"],
            "serotype": row["serotype"],
            "serotype_method": row["serotype_method"],
            "mlst_scheme": row["mlst_scheme"],
            "mlst_st": row["mlst_st"],
            "plasmid_types": json.loads(row["plasmid_types"] or "[]"),
            "amr_genes": genes,
            "object_id": row["object_id"],
            "analysis_date": row["analysis_date"],
            "pipeline_version": row["pipeline_version"],
        }

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM strain_genotype_index").fetchone()
        return int(row[0]) if row else 0

    def rebuild_from_gom(self, gom_conn: sqlite3.Connection) -> int:
        rows = gom_conn.execute(
            """SELECT g.object_id, g.strain_id, g.organism, g.payload_json,
                      g.created_at, g.pipeline_version
               FROM genome_objects g
               INNER JOIN (
                   SELECT object_id, MAX(version) AS max_v
                   FROM genome_objects WHERE object_type = 'analysis'
                   GROUP BY object_id
               ) latest ON g.object_id = latest.object_id
                        AND g.version = latest.max_v
               WHERE g.object_type = 'analysis'
                 AND g.strain_id NOT LIKE 'cohort:%'"""
        ).fetchall()

        count = 0
        for row in rows:
            payload = json.loads(row["payload_json"])
            extracted = _extract_genotype(payload)
            self.upsert(
                strain_id=row["strain_id"],
                organism=row["organism"] or "",
                species=extracted["species"],
                serotype=extracted["serotype"],
                serotype_method=extracted["serotype_method"],
                mlst_scheme=extracted["mlst_scheme"],
                mlst_st=extracted["mlst_st"],
                plasmid_types=extracted["plasmid_types"],
                amr_genes=extracted["amr_genes"],
                object_id=row["object_id"],
                analysis_date=row["created_at"],
                pipeline_version=row["pipeline_version"] or "",
            )
            count += 1
        return count

    def close(self) -> None:
        conn = getattr(self, "_conn", None)
        if conn is not None:
            conn.close()


def _extract_genotype(payload: dict[str, Any]) -> dict[str, Any]:
    species = payload.get("species_verdict", "")

    serotype_val = ""
    serotype_method = ""
    serotype_data = payload.get("serotype", {})
    if isinstance(serotype_data, str):
        serotype_val = serotype_data
    elif isinstance(serotype_data, dict):
        serotype_val = serotype_data.get("sistr", "") or serotype_data.get("serotype", "")
        if serotype_val and serotype_val != "N/A":
            serotype_method = "SISTR"
    else:
        serotype_val = ""
    if not serotype_val:
        dec = payload.get("dec", {})
        if isinstance(dec, dict):
            primary = dec.get("primary_serotype", "")
            method = dec.get("serotype_method", "")
            if primary and primary not in ("N/A", "-:-", "Undetermined"):
                serotype_val = primary
                serotype_method = method

    mlst_scheme = ""
    mlst_st = ""
    mlst_raw = payload.get("mlst", "")
    if mlst_raw and isinstance(mlst_raw, str):
        parsed = parse_mlst(mlst_raw)
        mlst_scheme = parsed["alleles"].get("scheme", "")
        raw_st = parsed["st"]
        if raw_st and raw_st not in ("N/A", "-", ""):
            mlst_st = f"ST{raw_st}" if not raw_st.upper().startswith("ST") else raw_st

    amr_genes: list[dict[str, Any]] = []
    amr_data = payload.get("amr", {})
    if isinstance(amr_data, dict):
        for db_name in ("abricate_card", "abricate_vfdb"):
            hits = amr_data.get(db_name, [])
            if isinstance(hits, list):
                db_label = db_name.replace("abricate_", "")
                for hit in hits:
                    if isinstance(hit, dict):
                        gene = hit.get("GENE", "").strip()
                        if gene:
                            amr_genes.append(
                                {
                                    "gene": gene,
                                    "database": db_label,
                                    "coverage": float(hit.get("%COVERAGE", 0) or 0),
                                    "identity": float(hit.get("%IDENTITY", 0) or 0),
                                    "product": hit.get("PRODUCT", ""),
                                }
                            )

    plasmid_types: list[str] = []
    plasmid_data = payload.get("plasmid", {})
    if isinstance(plasmid_data, dict):
        hits = plasmid_data.get("plasmidfinder", [])
        if isinstance(hits, list):
            for hit in hits:
                if isinstance(hit, dict):
                    gene = hit.get("GENE", "").strip()
                    if gene:
                        plasmid_types.append(gene)

    return {
        "species": species,
        "serotype": serotype_val,
        "serotype_method": serotype_method,
        "mlst_scheme": mlst_scheme,
        "mlst_st": mlst_st,
        "amr_genes": amr_genes,
        "plasmid_types": plasmid_types,
    }
