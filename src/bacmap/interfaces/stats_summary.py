"""``bacmap stats``——全库统计汇总（PLAN.md #18）。

只读遍历 ``$BACMAP_HOME`` 下的持久化库，输出各库的行数/状态分布/文件大小/
schema 版本，等价于 Web 首页信息汇总的 CLI 版。缺库如实标注 missing，
不创建任何文件。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0
    except sqlite3.Error:
        return None


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def _file_info(path: Path) -> dict[str, Any]:
    return {
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "size_human": _human(path.stat().st_size) if path.is_file() else "",
    }


def _human(size: int) -> str:
    n = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def _open_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def gather_stats(home: str | Path) -> dict[str, Any]:
    """收集 $BACMAP_HOME 下所有库的统计（只读；缺库标 missing）。"""
    root = Path(home)
    out: dict[str, Any] = {"schema": "bacmap.stats/1", "home": str(root)}

    tasks_db = root / "tasks.sqlite"
    info = _file_info(tasks_db)
    if info["exists"]:
        conn = _open_ro(tasks_db)
        try:
            states = dict(_rows(conn, "SELECT state, COUNT(*) FROM tasks GROUP BY state"))
            out["tasks"] = {
                **info,
                "total": _count(conn, "SELECT COUNT(*) FROM tasks"),
                "by_state": states,
                "plans": _count(conn, "SELECT COUNT(DISTINCT plan_id) FROM plans"),
            }
        finally:
            conn.close()
    else:
        out["tasks"] = {**info, "total": 0, "by_state": {}, "plans": 0}

    runs_db = root / "runs.sqlite"
    info = _file_info(runs_db)
    if info["exists"]:
        conn = _open_ro(runs_db)
        try:
            out["runs"] = {
                **info,
                "total": _count(conn, "SELECT COUNT(*) FROM analysis_runs"),
            }
        finally:
            conn.close()
    else:
        out["runs"] = {**info, "total": 0}

    gom_db = root / "gom.sqlite"
    info = _file_info(gom_db)
    if info["exists"]:
        conn = _open_ro(gom_db)
        try:
            out["gom"] = {
                **info,
                "genome_objects": _count(conn, "SELECT COUNT(*) FROM genome_objects"),
                "isolates": _count(conn, "SELECT COUNT(DISTINCT strain_id) FROM strain_amr_genes"),
                "amr_genes": _count(conn, "SELECT COUNT(*) FROM strain_amr_genes"),
            }
            out["strains"] = {
                "total": _count(conn, "SELECT COUNT(*) FROM strain_genotype_index") or 0,
                "species": [
                    {"name": r[0], "count": r[1]}
                    for r in _rows(
                        conn,
                        "SELECT species, COUNT(*) AS n FROM strain_genotype_index"
                        " WHERE species != '' GROUP BY species ORDER BY n DESC LIMIT 12",
                    )
                ],
                "serotypes": [
                    {"name": r[0], "count": r[1]}
                    for r in _rows(
                        conn,
                        "SELECT serotype, COUNT(*) AS n FROM strain_genotype_index"
                        " WHERE serotype != '' GROUP BY serotype ORDER BY n DESC LIMIT 12",
                    )
                ],
                "mlst": [
                    {"name": r[0], "count": r[1]}
                    for r in _rows(
                        conn,
                        "SELECT mlst_st, COUNT(*) AS n FROM strain_genotype_index"
                        " WHERE mlst_st != '' GROUP BY mlst_st ORDER BY n DESC LIMIT 12",
                    )
                ],
                "amr_top": [
                    {"name": r[0], "count": r[1]}
                    for r in _rows(
                        conn,
                        "SELECT gene_name, COUNT(*) AS n FROM strain_amr_genes"
                        " GROUP BY gene_name ORDER BY n DESC LIMIT 15",
                    )
                ],
            }
            # v1.10.27：物种优先的分层统计——全库混合的 ST/血清型/耐药
            # 无生物学意义；每个物种下再给 MLST / 血清型 / AMR Top。
            by_species: list[dict[str, Any]] = []
            for entry in out["strains"]["species"]:
                species = str(entry["name"])
                count = int(entry["count"])
                by_species.append(
                    {
                        "name": species,
                        "count": count,
                        "mlst": [
                            {"name": r[0], "count": r[1]}
                            for r in _rows(
                                conn,
                                "SELECT mlst_st, COUNT(*) AS n FROM strain_genotype_index"
                                " WHERE species = ? AND mlst_st != ''"
                                " GROUP BY mlst_st ORDER BY n DESC LIMIT 8",
                                (species,),
                            )
                        ],
                        "serotypes": [
                            {"name": r[0], "count": r[1]}
                            for r in _rows(
                                conn,
                                "SELECT serotype, COUNT(*) AS n FROM strain_genotype_index"
                                " WHERE species = ? AND serotype != ''"
                                " GROUP BY serotype ORDER BY n DESC LIMIT 8",
                                (species,),
                            )
                        ],
                        "amr_top": [
                            {"name": r[0], "count": r[1]}
                            for r in _rows(
                                conn,
                                "SELECT g.gene_name, COUNT(*) AS n"
                                " FROM strain_amr_genes g"
                                " JOIN strain_genotype_index s"
                                "   ON s.strain_id = g.strain_id"
                                " WHERE s.species = ? AND g.database != 'vfdb'"
                                " GROUP BY g.gene_name ORDER BY n DESC LIMIT 10",
                                (species,),
                            )
                        ],
                        "virulence_top": [
                            {"name": r[0], "count": r[1]}
                            for r in _rows(
                                conn,
                                "SELECT g.gene_name, COUNT(*) AS n"
                                " FROM strain_amr_genes g"
                                " JOIN strain_genotype_index s"
                                "   ON s.strain_id = g.strain_id"
                                " WHERE s.species = ? AND g.database = 'vfdb'"
                                " GROUP BY g.gene_name ORDER BY n DESC LIMIT 10",
                                (species,),
                            )
                        ],
                    }
                )
            out["strains"]["by_species"] = by_species
        finally:
            conn.close()
    else:
        out["gom"] = {**info, "genome_objects": 0, "isolates": 0, "amr_genes": 0}
        out["strains"] = {
            "total": 0,
            "species": [],
            "serotypes": [],
            "mlst": [],
            "amr_top": [],
            "by_species": [],
        }

    data_db = root / "data" / "bacmap.sqlite"
    info = _file_info(data_db)
    if info["exists"]:
        conn = _open_ro(data_db)
        try:
            out["lab_results"] = {
                **info,
                "total": _count(conn, "SELECT COUNT(*) FROM lab_results"),
                "strains": _count(conn, "SELECT COUNT(DISTINCT strain_id) FROM lab_results"),
            }
        finally:
            conn.close()
    else:
        out["lab_results"] = {**info, "total": 0, "strains": 0}

    knowledge_db = root / "data" / "knowledge.sqlite"
    info = _file_info(knowledge_db)
    if info["exists"]:
        conn = _open_ro(knowledge_db)
        try:
            tables = {
                r[0]
                for r in _rows(
                    conn, "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            entry_table = "entries" if "entries" in tables else None
            n_entries = 0
            if entry_table:
                # entry_table 只可能是字面量 "entries"，无注入面
                n_entries = _count(conn, f"SELECT COUNT(*) FROM {entry_table}")  # noqa: S608
            out["knowledge"] = {**info, "entries": n_entries}
        finally:
            conn.close()
    else:
        out["knowledge"] = {**info, "entries": 0}

    research_db = root / "research.sqlite"
    info = _file_info(research_db)
    if info["exists"]:
        conn = _open_ro(research_db)
        try:
            out["research"] = {
                **info,
                "sessions": _count(conn, "SELECT COUNT(*) FROM analysis_sessions"),
                "studies": _count(conn, "SELECT COUNT(*) FROM studies"),
                "cohorts": _count(conn, "SELECT COUNT(*) FROM cohorts"),
                "claims": _count(conn, "SELECT COUNT(*) FROM claims"),
                "requests": _count(conn, "SELECT COUNT(*) FROM research_requests"),
                "analyses": _count(conn, "SELECT COUNT(*) FROM research_analyses"),
                "advstats_results": len(
                    list((root / "research" / "advstats").glob("*/result.json"))
                ),
            }
        finally:
            conn.close()
    else:
        out["research"] = {
            **info, "sessions": 0, "studies": 0, "cohorts": 0,
            "claims": 0, "requests": 0, "analyses": 0, "advstats_results": 0,
        }

    results_dir = root / "results"
    n_results = (
        sum(1 for _ in results_dir.glob("*/report/*_summary.json"))
        if results_dir.is_dir()
        else 0
    )
    out["results"] = {"exists": results_dir.is_dir(), "sample_reports": n_results}
    return out


def stats_markdown(stats: dict[str, Any]) -> str:
    """人类可读的 Markdown 版（CLI 非 --json 输出 / 报告嵌入）。"""
    lines = [f"# bacmap stats — {stats['home']}", ""]
    tasks = stats["tasks"]
    state = json.dumps(tasks["by_state"], ensure_ascii=False)
    lines.append(
        f"- 任务: {tasks['total']}（{state}）"
        f"计划 {tasks['plans']} · {tasks['size_human']}"
    )
    lines.append(f"- 运行: {stats['runs']['total']} · {stats['runs']['size_human']}")
    gom = stats["gom"]
    lines.append(
        f"- GOM: 对象 {gom['genome_objects']} · 菌株 {gom['isolates']} ·"
        f" AMR 基因 {gom['amr_genes']} · {gom['size_human']}"
    )
    lab = stats["lab_results"]
    lines.append(f"- 化验: {lab['total']} 条（{lab['strains']} 株）· {lab['size_human']}")
    kn = stats["knowledge"]
    lines.append(f"- 知识库: {kn['entries']} 条 · {kn['size_human']}")
    r = stats["research"]
    lines.append(
        f"- 研究: 会话 {r['sessions']} · 研究 {r['studies']} · 队列 {r['cohorts']} · "
        f"断言 {r['claims']} · 请求 {r['requests']} · 分析 {r['analyses']} · "
        f"advstats {r['advstats_results']} · {r['size_human']}"
    )
    lines.append(f"- 结果报告: {stats['results']['sample_reports']}")
    return "\n".join(lines)
