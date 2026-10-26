"""本地流行特征库（ADR-19）：本辖区菌株流行病学特征的版本化集合。

构成：纳入菌株清单（每株指向 run_id）+ 特征表（分型/耐药/毒力/质粒 +
分离日期/地区/来源，白名单字段——D4 个人信息按构造排除）+ 汇总统计。

发布流程：curate 任务构建候选 → 特征库发布门（tasks.gates）→ 人工签名
→ publish() 写入 baseline_releases（INSERT-ONLY，已发布版本不可修改）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.core.analysis.species_canon import UNKNOWN as SPECIES_UNKNOWN
from bacmap.core.analysis.species_canon import canonical_from_verdict
from bacmap.core.utils import parse_mlst
from bacmap.store.migrations import Migration, migrate

CANDIDATES_DDL = """
CREATE TABLE IF NOT EXISTS baseline_candidates (
    task_id     TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    gate_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL
)
"""

RELEASES_DDL = """
CREATE TABLE IF NOT EXISTS baseline_releases (
    version      INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    signature    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'published',
    n_strains    INTEGER NOT NULL,
    scope_json   TEXT NOT NULL DEFAULT '{}',
    manifest_json TEXT NOT NULL,
    stats_json   TEXT NOT NULL,
    parent_version INTEGER
)
"""

# 特征白名单（ADR-19 特征表；白名单之外一律不进特征库 → D4 按构造排除）
FEATURE_METADATA_FIELDS = (
    "isolation_date", "collection_date",
    "province", "city", "district",
    "sample_source", "sample_type", "food_category", "food_name",
    "outbreak_id",
)


def _summary_species(summary: dict[str, Any]) -> str:
    sp = ((summary.get("steps", {}) or {}).get("species", {})) or {}
    if isinstance(sp, dict):
        return str(sp.get("verdict") or sp.get("species") or "")
    return ""


def _summary_serotype(summary: dict[str, Any]) -> str:
    sero = ((summary.get("steps", {}) or {}).get("serotype", {})) or {}
    return str(sero.get("sistr", "")) if isinstance(sero, dict) else ""


def _summary_mlst_st(summary: dict[str, Any]) -> str:
    raw = (summary.get("steps", {}) or {}).get("mlst", "")
    if not isinstance(raw, str) or not raw:
        return ""
    st = str(parse_mlst(raw).get("st", ""))
    return "" if st in ("N/A", "-") else st


def _gene_names(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if isinstance(r, dict):
            g = r.get("GENE") or r.get("gene")
            if g:
                out.append(str(g))
    return sorted(set(out))


def _qc_ok(summary: dict[str, Any]) -> bool:
    qc = (summary.get("steps", {}) or {}).get("qc")
    return isinstance(qc, dict) and bool(qc)


def strain_checks(summary: dict[str, Any], meta: dict[str, Any]) -> dict[str, bool]:
    """纳入条件逐项检查（发布门消费同一结果，保证一致）。"""
    species = _summary_species(summary)
    dec = ((summary.get("steps", {}) or {}).get("dec", {})) or {}
    ipah = str(dec.get("ipaH", "")) if isinstance(dec, dict) else ""
    return {
        "analysis_ok": bool(species)
        and canonical_from_verdict(species, ipah) != SPECIES_UNKNOWN,
        "qc_ok": _qc_ok(summary),
        "metadata_ok": bool(
            meta.get("isolation_date")
            and (meta.get("province") or meta.get("city"))
            and meta.get("sample_source")
        ),
    }


def _isolate_map(home: Path) -> dict[str, str]:
    """samples.tsv v3：dataset → isolate（表缺失/旧版时回落 dataset 自身）。"""
    tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    if not tsv.is_file():
        return {}
    lines = tsv.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {}
    header = lines[0].split("\t")
    if "isolate" not in header:
        return {}
    idx, iso = header.index("sample"), header.index("isolate")
    out: dict[str, str] = {}
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) > max(idx, iso) and parts[idx]:
            out[parts[idx]] = parts[iso] or parts[idx]
    return out


def build_candidate(
    home: Path,
    scope: dict[str, Any] | None = None,
    metadata_db: Path | None = None,
) -> dict[str, Any]:
    """从 results/ + strain_metadata 构建候选清单（含逐株纳入检查与排除记录）。"""
    from bacmap.store.strain_metadata import StrainMetadataService

    home = Path(home)
    scope = scope or {}
    data_dir = home / "data"
    meta_path = metadata_db or (
        data_dir / "bacmap.sqlite"
        if (data_dir / "bacmap.sqlite").is_file()
        else data_dir / "metadata.sqlite"
    )
    meta_svc = StrainMetadataService(meta_path)
    isolate_of = _isolate_map(home)

    groups: dict[str, list[dict[str, Any]]] = {}
    excluded: list[dict[str, str]] = []
    # 样本 ID 任意（samples.tsv 与 MCP 白名单 [A-Za-z0-9._-]+ 均不限于 SAM-*）；
    # 与 bio_list_samples / Web 的 results 扫描口径一致（*/report/*_summary.json）。
    for sdir in sorted((home / "results").glob("*/report/*_summary.json")):
        strain_id = sdir.parent.parent.name
        isolate = isolate_of.get(strain_id, strain_id)
        if scope.get("strains") and not (
            strain_id in scope["strains"] or isolate in scope["strains"]
        ):
            continue
        summary = json.loads(sdir.read_text(encoding="utf-8"))
        meta_obj = meta_svc.get(isolate) or meta_svc.get(strain_id)
        meta = meta_obj.to_dict() if meta_obj else {}

        species = _summary_species(summary)
        if scope.get("pathogen") and species and scope["pathogen"].lower() not in species.lower():
            continue

        checks = strain_checks(summary, meta)
        if not all(checks.values()):
            failed = [k for k, v in checks.items() if not v]
            excluded.append({"strain_id": strain_id, "reason": ",".join(failed)})
            continue

        features: dict[str, Any] = {
            "species": canonical_from_verdict(
                species,
                str(((summary.get("steps", {}).get("dec", {})) or {}).get("ipaH", "")),
            ),
            "species_raw": species,
            "serotype": _summary_serotype(summary),
            "mlst_st": _summary_mlst_st(summary),
            "amr_genes": _gene_names(
                ((summary.get("steps", {}).get("amr", {})) or {}).get("abricate_card")
            ),
            "virulence_genes": _gene_names(
                ((summary.get("steps", {}).get("amr", {})) or {}).get("abricate_vfdb")
            ),
            "plasmids": _gene_names(
                ((summary.get("steps", {}).get("plasmid", {})) or {}).get("plasmidfinder")
            ),
        }
        for f in FEATURE_METADATA_FIELDS:
            if meta.get(f):
                features[f] = meta[f]

        groups.setdefault(isolate, []).append(
            {
                "strain_id": strain_id,
                "isolate_id": isolate,
                "summary_path": str(sdir.relative_to(home)),
                "features": features,
                "_mtime": sdir.stat().st_mtime,
            }
        )

    explicit = scope.get("representative_dataset") or {}
    strains: list[dict[str, Any]] = []
    representative_runs: dict[str, dict[str, Any]] = {}
    superseded: list[dict[str, str]] = []
    for isolate, entries in sorted(groups.items()):
        wanted = explicit.get(isolate)
        if wanted:
            chosen = [e for e in entries if e["strain_id"] == wanted]
            if not chosen:
                excluded.append(
                    {
                        "strain_id": wanted,
                        "isolate_id": isolate,
                        "reason": "representative_dataset_missing",
                    }
                )
                continue
            pick, reason = chosen[0], "explicit"
        else:
            pick = max(entries, key=lambda e: (e["_mtime"], e["strain_id"]))
            reason = "latest"
        for e in entries:
            if e is not pick:
                superseded.append(
                    {"isolate_id": isolate, "dataset_id": e["strain_id"], "reason": reason}
                )
        representative_runs[isolate] = {
            "dataset_id": pick["strain_id"],
            "summary_path": pick["summary_path"],
            "reason": reason,
        }
        strains.append({k: v for k, v in pick.items() if k != "_mtime"})

    return {
        "home": str(home),
        "scope": scope,
        "strains": strains,
        "excluded": excluded,
        "representative_runs": representative_runs,
        "superseded": superseded,
        "built_at": datetime.now(UTC).isoformat(),
    }


def compute_stats(candidate: dict[str, Any]) -> dict[str, Any]:
    """按 病原 × 年份 × 省份 × 来源 聚合。"""
    stats: dict[str, int] = {}
    for rec in candidate.get("strains", []):
        f = rec["features"]
        year = str(f.get("isolation_date", ""))[:4] or "unknown"
        key = "|".join(
            (f.get("species", "?"), year, f.get("province", "?"), f.get("sample_source", "?"))
        )
        stats[key] = stats.get(key, 0) + 1
    return {
        "n_strains": len(candidate.get("strains", [])),
        "n_excluded": len(candidate.get("excluded", [])),
        "by_species_year_region_source": stats,
    }


# baseline.sqlite 的 schema 迁移（ADR-13，v1.5.2）；只追加。
BASELINE_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline: candidates + releases", (CANDIDATES_DDL, RELEASES_DDL)),
)


def _conn(db_path: Path) -> sqlite3.Connection:
    migrate(Path(db_path), BASELINE_MIGRATIONS)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def save_candidate(db_path: Path, task_id: str, manifest: dict, gate: dict) -> None:
    with _conn(db_path) as conn:
        manifest_json = json.dumps(manifest, ensure_ascii=False)
        gate_json = json.dumps(gate, ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO baseline_candidates"
            " (task_id, manifest_json, gate_json, created_at) VALUES (?,?,?,?)",
            (task_id, manifest_json, gate_json, datetime.now(UTC).isoformat()),
        )


def load_candidate(db_path: Path, task_id: str) -> dict | None:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT manifest_json, gate_json FROM baseline_candidates WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    if row is None:
        return None
    return {"manifest": json.loads(row["manifest_json"]), "gate": json.loads(row["gate_json"])}


def publish(db_path: Path, manifest: dict, created_by: str, signature: str) -> int:
    """写入新发布版本（INSERT-ONLY）。返回版本号。父版本记入 parent_version（ADR-19）。"""
    stats = compute_stats(manifest)
    with _conn(db_path) as conn:
        prev = conn.execute(
            "SELECT MAX(version) AS v FROM baseline_releases"
        ).fetchone()
        parent = int(prev["v"]) if prev is not None and prev["v"] is not None else None
        cur = conn.execute(
            "INSERT INTO baseline_releases (created_at, created_by, signature, n_strains,"
            " scope_json, manifest_json, stats_json, parent_version)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                datetime.now(UTC).isoformat(),
                created_by,
                signature,
                stats["n_strains"],
                json.dumps(manifest.get("scope", {}), ensure_ascii=False),
                json.dumps(manifest, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False),
                parent,
            ),
        )
        return int(cur.lastrowid or 0)


def get_release(db_path: Path, version: int) -> dict | None:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM baseline_releases WHERE version = ?", (version,)
        ).fetchone()
    return dict(row) if row else None


def list_releases(db_path: Path) -> list[dict]:
    with _conn(db_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT version, created_at, created_by, n_strains, status"
                " FROM baseline_releases ORDER BY version"
            ).fetchall()
        ]
