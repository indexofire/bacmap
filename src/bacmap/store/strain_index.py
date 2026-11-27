from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from bacmap.core.utils import parse_mlst
from bacmap.store.schema import STRAIN_INDEX_DDL


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


DDL_STATEMENTS = STRAIN_INDEX_DDL


class StrainGenotypeIndex:
    def __init__(self, db_path: str | Path) -> None:
        from bacmap.store.genome_object_service import ensure_gom_schema

        # 索引与 GOM 同库（gom.sqlite）：先迁移后开连接——迁移走独立连接并
        # 推进 user_version/WAL，先开连接会持有迁移前的陈旧视图。
        ensure_gom_schema(db_path)
        self._conn: sqlite3.Connection = sqlite3.connect(str(db_path), timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

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
        specimen_id: str = "",
        isolate_id: str = "",
        genome_size: int | None = None,
        contigs: int | None = None,
        gc_pct: float | None = None,
        n_card: int = 0,
        n_vfdb: int = 0,
        n_plasmid: int = 0,
        owner_user_id: str = "",
        prelim: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()  # noqa: UP017
        try:
            self._conn.execute(
                """INSERT INTO strain_genotype_index
                   (strain_id, organism, species, serotype, serotype_method,
                    mlst_scheme, mlst_st, plasmid_types, object_id,
                    analysis_date, pipeline_version, updated_at,
                    specimen_id, isolate_id, genome_size, contigs, gc_pct,
                    n_card, n_vfdb, n_plasmid, owner_user_id, prelim)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?)
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
                     updated_at=excluded.updated_at,
                     specimen_id=excluded.specimen_id,
                     isolate_id=excluded.isolate_id,
                     genome_size=excluded.genome_size,
                     contigs=excluded.contigs,
                     gc_pct=excluded.gc_pct,
                     n_card=excluded.n_card,
                     n_vfdb=excluded.n_vfdb,
                     n_plasmid=excluded.n_plasmid,
                     owner_user_id=excluded.owner_user_id,
                     prelim=excluded.prelim""",
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
                    specimen_id or None,
                    isolate_id or None,
                    genome_size,
                    contigs,
                    gc_pct,
                    int(n_card),
                    int(n_vfdb),
                    int(n_plasmid),
                    owner_user_id or None,
                    1 if prelim else 0,
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
        except Exception:
            self._conn.rollback()
            raise
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
            "SELECT DISTINCT g.* FROM strain_genotype_index g"  # noqa: S608 — 片段为模块内常量/占位符拼装，值一律 ? 绑定
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

    # ---- 结果目录（v1.10.x）：服务端分页/检索，替代逐请求扫描 summary JSON ----

    _SORT_FIELDS: ClassVar[dict[str, str]] = {
        "sample_id": "g.strain_id",
        "species": "COALESCE(NULLIF(g.organism,''), g.species)",
        "st": "g.mlst_st",
        "serovar": "g.serotype",
        "genome_size": "g.genome_size",
        "contigs": "g.contigs",
        "gc_pct": "g.gc_pct",
        "analysis_date": "g.analysis_date",
        "n_card": "g.n_card",
        "n_vfdb": "g.n_vfdb",
        "n_plasmid": "g.n_plasmid",
    }

    def sample_page(
        self,
        *,
        query: str = "",
        species: str = "",
        serotype: str = "",
        mlst_st: str = "",
        amr_gene: str = "",
        owner_user_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
        sort: str = "sample_id",
        order: str = "asc",
    ) -> tuple[list[dict[str, Any]], int]:
        """按结果索引分页；返回 (rows, total)。过滤条件全部在 SQL 内完成。"""
        where, params = self._sample_filters(
            query=query,
            species=species,
            serotype=serotype,
            mlst_st=mlst_st,
            amr_gene=amr_gene,
            owner_user_id=owner_user_id,
        )
        column = self._SORT_FIELDS.get(sort)
        if column is None:
            raise ValueError(f"unknown sort field: {sort}")
        direction = "DESC" if order == "desc" else "ASC"
        total_row = self._conn.execute(
            f"SELECT COUNT(*) FROM strain_genotype_index g{where}", params  # noqa: S608 — 同上
        ).fetchone()
        total = int(total_row[0]) if total_row else 0
        rows = self._conn.execute(
            "SELECT g.* FROM strain_genotype_index g"  # noqa: S608 — 排序字段白名单 + 值参数化
            f"{where} ORDER BY ({column} IS NULL) ASC, {column} {direction},"
            " g.strain_id ASC LIMIT ? OFFSET ?",
            (*params, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
        items = [self._sample_dict(row) for row in rows]
        self._attach_genes(items)
        return items, total

    def backfill_metadata(
        self,
        *,
        strain_id: str,
        specimen_id: str = "",
        isolate_id: str = "",
        genome_size: int | None = None,
        contigs: int | None = None,
        gc_pct: float | None = None,
        n_card: int = 0,
        n_vfdb: int = 0,
        n_plasmid: int = 0,
        owner_user_id: str = "",
    ) -> bool:
        """只更新结果目录新增列，保留 object_id/分型/analysis_date 等既有字段。

        用于 v1.10.49 升级：旧索引行已有 GOM 关联，不能用 ``--force`` 全量重写。
        """
        cur = self._conn.execute(
            "UPDATE strain_genotype_index SET specimen_id = ?, isolate_id = ?,"
            " genome_size = ?, contigs = ?, gc_pct = ?, n_card = ?, n_vfdb = ?,"
            " n_plasmid = ?, owner_user_id = ?, updated_at = ? WHERE strain_id = ?",
            (
                specimen_id or None,
                isolate_id or None,
                genome_size,
                contigs,
                gc_pct,
                int(n_card),
                int(n_vfdb),
                int(n_plasmid),
                owner_user_id or None,
                datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),  # noqa: UP017
                strain_id,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_identity(
        self,
        *,
        sample_id: str | None = None,
        isolate_id: str | None = None,
        specimen_id: str = "",
        new_isolate_id: str = "",
    ) -> int:
        """同步 samples.tsv 变更后的 specimen/isolate 映射（关联/回填后调用）。"""
        if sample_id:
            cur = self._conn.execute(
                "UPDATE strain_genotype_index SET specimen_id = ?,"
                " isolate_id = COALESCE(NULLIF(?, ''), isolate_id)"
                " WHERE strain_id = ?",
                (specimen_id or None, new_isolate_id, sample_id),
            )
        elif isolate_id:
            cur = self._conn.execute(
                "UPDATE strain_genotype_index SET specimen_id = ?, isolate_id = ?"
                " WHERE isolate_id = ?",
                (specimen_id or None, new_isolate_id or isolate_id, isolate_id),
            )
        else:
            return 0
        self._conn.commit()
        return int(cur.rowcount)

    def set_owner(
        self,
        owner_user_id: str | None,
        *,
        specimen_id: str | None = None,
        isolate_id: str | None = None,
    ) -> int:
        """把样本/菌株下所有结果行改归属；返回更新行数。"""
        if specimen_id:
            cur = self._conn.execute(
                "UPDATE strain_genotype_index SET owner_user_id = ?"
                " WHERE specimen_id = ?",
                (owner_user_id or None, specimen_id),
            )
        elif isolate_id:
            cur = self._conn.execute(
                "UPDATE strain_genotype_index SET owner_user_id = ?"
                " WHERE isolate_id = ?",
                (owner_user_id or None, isolate_id),
            )
        else:
            return 0
        self._conn.commit()
        return int(cur.rowcount)

    def count_indexed(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM strain_genotype_index").fetchone()
        return int(row[0]) if row else 0

    def species_summary(
        self, *, owner_user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """物种维度聚合（物种页/筛选器）；按结果数降序。"""
        where, params = self._sample_filters(owner_user_id=owner_user_id)
        rows = self._conn.execute(
            "SELECT COALESCE(NULLIF(g.organism,''), g.species) AS species,"  # noqa: S608
            " COUNT(*) AS n_samples,"
            " COUNT(DISTINCT g.specimen_id) AS n_specimens,"
            " COUNT(DISTINCT g.isolate_id) AS n_isolates,"
            " MAX(g.analysis_date) AS last_analysis,"
            " COUNT(g.genome_size) AS n_with_metrics"
            " FROM strain_genotype_index g"
            f"{where} GROUP BY 1 ORDER BY n_samples DESC, 1 ASC",
            params,
        ).fetchall()
        return [
            {
                "species": str(r["species"] or "Unknown"),
                "n_samples": int(r["n_samples"]),
                "n_specimens": int(r["n_specimens"] or 0),
                "n_isolates": int(r["n_isolates"] or 0),
                "last_analysis": str(r["last_analysis"] or ""),
                "n_with_metrics": int(r["n_with_metrics"] or 0),
            }
            for r in rows
        ]

    def specimen_summary(self, specimen_ids: list[str]) -> dict[str, dict[str, Any]]:
        """样本 → 物种/结果数/最近分析（批量查，供样本列表补列）。"""
        if not specimen_ids:
            return {}
        marks = ",".join("?" for _ in specimen_ids)
        rows = self._conn.execute(
            "SELECT specimen_id,"  # noqa: S608 — IN 占位符数量由列表长度决定，值全部参数化
            " GROUP_CONCAT(DISTINCT COALESCE(NULLIF(organism,''), species)) AS species,"
            " COUNT(*) AS n_results, MAX(analysis_date) AS last_analysis"
            " FROM strain_genotype_index"
            f" WHERE specimen_id IN ({marks}) GROUP BY specimen_id",
            tuple(specimen_ids),
        ).fetchall()
        return {
            str(r["specimen_id"]): {
                "species": str(r["species"] or ""),
                "n_results": int(r["n_results"]),
                "last_analysis": str(r["last_analysis"] or ""),
            }
            for r in rows
        }

    def isolate_summary(self, isolate_ids: list[str]) -> dict[str, dict[str, Any]]:
        """菌株 → 物种/型别/结果数/最近分析（批量查）。"""
        if not isolate_ids:
            return {}
        marks = ",".join("?" for _ in isolate_ids)
        rows = self._conn.execute(
            "SELECT isolate_id,"  # noqa: S608 — IN 占位符数量由列表长度决定，值全部参数化
            " GROUP_CONCAT(DISTINCT COALESCE(NULLIF(organism,''), species)) AS species,"
            " GROUP_CONCAT(DISTINCT serotype) AS serotypes,"
            " GROUP_CONCAT(DISTINCT mlst_st) AS sts,"
            " COUNT(*) AS n_results, MAX(analysis_date) AS last_analysis"
            " FROM strain_genotype_index"
            f" WHERE isolate_id IN ({marks}) GROUP BY isolate_id",
            tuple(isolate_ids),
        ).fetchall()
        return {
            str(r["isolate_id"]): {
                "species": str(r["species"] or ""),
                "serotypes": [
                    s for s in str(r["serotypes"] or "").split(",") if s
                ],
                "sts": [s for s in str(r["sts"] or "").split(",") if s],
                "n_results": int(r["n_results"]),
                "last_analysis": str(r["last_analysis"] or ""),
            }
            for r in rows
        }

    def get_sample(self, sample_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM strain_genotype_index WHERE strain_id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            return None
        item = self._sample_dict(row)
        self._attach_genes([item])
        return item

    def _sample_filters(
        self,
        *,
        query: str = "",
        species: str = "",
        serotype: str = "",
        mlst_st: str = "",
        amr_gene: str = "",
        owner_user_id: str | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_user_id is not None:
            clauses.append("g.owner_user_id = ?")
            params.append(owner_user_id)
        if species:
            clauses.append("(g.organism = ? OR g.species = ?)")
            params.extend([species, species])
        if serotype:
            clauses.append("g.serotype LIKE ?")
            params.append(f"%{serotype}%")
        if mlst_st:
            normalized = mlst_st.strip().upper()
            if normalized and not normalized.startswith("ST"):
                normalized = "ST" + normalized
            clauses.append("UPPER(g.mlst_st) = ?")
            params.append(normalized)
        if amr_gene:
            clauses.append(
                "EXISTS (SELECT 1 FROM strain_amr_genes a"
                " WHERE a.strain_id = g.strain_id AND a.gene_name = ?)"
            )
            params.append(amr_gene)
        q = query.strip().lower()
        if q:
            like = f"%{q}%"
            clauses.append(
                "(LOWER(g.strain_id) LIKE ? OR LOWER(COALESCE(g.organism,'')) LIKE ?"
                " OR LOWER(COALESCE(g.species,'')) LIKE ?"
                " OR LOWER(COALESCE(g.serotype,'')) LIKE ?"
                " OR LOWER(COALESCE(g.mlst_st,'')) LIKE ?"
                " OR LOWER(COALESCE(g.specimen_id,'')) LIKE ?"
                " OR LOWER(COALESCE(g.isolate_id,'')) LIKE ?"
                " OR EXISTS (SELECT 1 FROM strain_amr_genes a"
                "   WHERE a.strain_id = g.strain_id AND LOWER(a.gene_name) LIKE ?))"
            )
            params.extend([like] * 8)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, tuple(params)

    @staticmethod
    def _sample_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "sample_id": str(row["strain_id"]),
            "verdict": str(row["organism"] or row["species"] or "N/A"),
            "species_code": str(row["species"] or ""),
            "genome_size": row["genome_size"],
            "contigs": row["contigs"],
            "gc_pct": row["gc_pct"],
            "st": str(row["mlst_st"] or "N/A"),
            "serovar": str(row["serotype"] or "N/A"),
            "n_card": int(row["n_card"] or 0),
            "n_vfdb": int(row["n_vfdb"] or 0),
            "n_plasmid": int(row["n_plasmid"] or 0),
            "specimen_id": str(row["specimen_id"] or ""),
            "isolate_id": str(row["isolate_id"] or ""),
            "owner_user_id": str(row["owner_user_id"] or ""),
            "analysis_date": str(row["analysis_date"] or ""),
            "prelim": bool(row["prelim"]),
            "plasmid_types": row["plasmid_types"] or "[]",
        }

    def _attach_genes(self, items: list[dict[str, Any]]) -> None:
        ids = [str(item["sample_id"]) for item in items]
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            "SELECT strain_id, gene_name, database FROM strain_amr_genes"  # noqa: S608 — IN 占位符数量由列表长度决定，值全部参数化
            f" WHERE strain_id IN ({marks}) ORDER BY gene_name",
            tuple(ids),
        ).fetchall()
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            grouped.setdefault(str(row["strain_id"]), []).append(
                {"gene": str(row["gene_name"]), "database": str(row["database"] or "")}
            )
        for item in items:
            genes = grouped.get(str(item["sample_id"]), [])
            item["card_genes"] = sorted(
                {g["gene"] for g in genes if g["database"].lower() in ("card", "ncbi", "amrfinder")}
            )
            item["vfdb_genes"] = sorted(
                {g["gene"] for g in genes if g["database"].lower() == "vfdb"}
            )
            try:
                plasmids = json.loads(str(item.get("plasmid_types") or "[]"))
            except ValueError:
                plasmids = []
            item["plasmids"] = sorted(
                {str(p) for p in plasmids if str(p).strip()}
            ) if isinstance(plasmids, list) else []

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

        if len(conditions) == 1:
            return []  # 无可用分型键（血清型/MLST 均空）：不得把全库其余菌株当"相似"
        sql = (
            "SELECT DISTINCT g.* FROM strain_genotype_index g"  # noqa: S608 — 片段为模块内常量/占位符拼装，值一律 ? 绑定
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
            "specimen_id": row["specimen_id"],
            "isolate_id": row["isolate_id"],
            "genome_size": row["genome_size"],
            "contigs": row["contigs"],
            "gc_pct": row["gc_pct"],
            "owner_user_id": row["owner_user_id"],
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
            # 仅纳入单样本分析对象；逐样本 cgmlst_profile / 队列对象（可能同 strain_id）
            # 不得污染特征索引。
            if payload.get("analysis_type") not in (None, "sample_analysis"):
                continue
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
            del self._conn  # 幂等关闭：再次 close 时 getattr 取不到即跳过

    def __enter__(self) -> StrainGenotypeIndex:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()


def _extract_serotype(payload: dict[str, Any]) -> tuple[str, str]:
    """血清型 (值, 方法)：统一 value 优先，其次 SISTR，最后回退 DEC 主血清型。"""
    serotype_val = ""
    serotype_method = ""
    serotype_data = payload.get("serotype", {})
    if isinstance(serotype_data, str):
        serotype_val = serotype_data
    elif isinstance(serotype_data, dict):
        # gspec shi_sero / sinh_sero 等统一写入 value+method；旧 summary 只有 sistr。
        serotype_val = str(serotype_data.get("value") or "").strip()
        if serotype_val and serotype_val != "N/A":
            serotype_method = str(serotype_data.get("method") or "gspec")
        else:
            sistr = str(serotype_data.get("sistr") or "").strip()
            if sistr and sistr != "N/A":
                serotype_val = sistr
                serotype_method = "SISTR"
    if not serotype_val or serotype_val == "N/A":
        dec = payload.get("dec", {})
        if isinstance(dec, dict):
            primary = str(dec.get("primary_serotype") or "").strip()
            method = str(dec.get("serotype_method") or "").strip()
            if primary and primary not in ("N/A", "-:-", "Undetermined"):
                serotype_val = primary
                serotype_method = method
    return serotype_val, serotype_method


def _extract_mlst(payload: dict[str, Any]) -> tuple[str, str]:
    """MLST (scheme, ST)：归一 JSON/dict 或旧 TSV 串经 parse_mlst 统一。"""
    mlst_scheme = ""
    mlst_st = ""
    mlst_raw = payload.get("mlst", "")
    if mlst_raw:
        parsed = parse_mlst(mlst_raw)
        mlst_scheme = str(parsed.get("scheme") or parsed["alleles"].get("scheme", ""))
        raw_st = parsed["st"]
        if raw_st and raw_st not in ("N/A", "-", ""):
            mlst_st = f"ST{raw_st}" if not raw_st.upper().startswith("ST") else raw_st
    return mlst_scheme, mlst_st


def _extract_amr_genes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """AMR 基因命中（gspec CARD/VFDB/NCBI；含覆盖率/一致度/产物）。"""
    amr_genes: list[dict[str, Any]] = []
    amr_data = payload.get("amr", {})
    if isinstance(amr_data, dict):
        for db_name in ("abricate_card", "abricate_vfdb", "gspec_ncbi", "amrfinderplus"):
            hits = amr_data.get(db_name, [])
            if isinstance(hits, list):
                db_label = {
                    "abricate_card": "card",
                    "abricate_vfdb": "vfdb",
                    "gspec_ncbi": "ncbi",
                    "amrfinderplus": "amrfinderplus",
                }[db_name]
                for hit in hits:
                    if isinstance(hit, dict):
                        gene = str(hit.get("GENE") or hit.get("Gene symbol") or "").strip()
                        if gene:
                            amr_genes.append(
                                {
                                    "gene": gene,
                                    "database": db_label,
                                    "coverage": float(
                                        hit.get("%COVERAGE")
                                        or hit.get("% Coverage of reference sequence")
                                        or 0
                                    ),
                                    "identity": float(
                                        hit.get("%IDENTITY")
                                        or hit.get("% Identity to reference sequence")
                                        or 0
                                    ),
                                    "product": hit.get("PRODUCT")
                                    or hit.get("Description", ""),
                                }
                            )
    return amr_genes


def _extract_plasmid_types(payload: dict[str, Any]) -> list[str]:
    """质粒复制子类型（plasmidfinder 命中基因名）。"""
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
    return plasmid_types


def _extract_genotype(payload: dict[str, Any]) -> dict[str, Any]:
    """summary payload → 索引列（各字段提取器单独可测）。"""
    serotype_val, serotype_method = _extract_serotype(payload)
    mlst_scheme, mlst_st = _extract_mlst(payload)
    return {
        "species": payload.get("species_verdict", ""),
        "serotype": serotype_val,
        "serotype_method": serotype_method,
        "mlst_scheme": mlst_scheme,
        "mlst_st": mlst_st,
        "amr_genes": _extract_amr_genes(payload),
        "plasmid_types": _extract_plasmid_types(payload),
    }
