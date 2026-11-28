"""管线步级产物的轻量解析（纯函数层）。

供任务引擎的 StepWatcher 在每个 Snakemake 子步骤产物落盘时提取**展示用摘要**。
设计约束：

- 本模块在 ``bacmap.workflow`` 命名空间内，按 ADR-02 不得导入
  ``agent/tasks/interfaces``——因此这里只做纯解析，不写事件、不碰数据库；
- 所有解析都是防御性的：产物格式变化、文件残缺、编码异常一律返回 ``{}``，
  绝不让展示层影响分析本身（事件是观察，不是真相）;
- 返回的摘要字典保持小体积（只取关键字段），避免把大对象塞进事件载荷。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

_MAX_BYTES = 2 * 1024 * 1024  # 摘要解析只读前 2MB，避免巨型产物拖慢监听线程


def _read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def _num(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return None
    return None


def parse_species(path: Path) -> dict[str, Any]:
    """gside 物种鉴定：物种名 + 判定方式。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    species = data.get("species") or data.get("verdict")
    if isinstance(species, str) and species.strip():
        out["species"] = species.strip()
    # gside 多模式结果可能嵌在 methods.<mode>.result.species
    methods = data.get("methods")
    if "species" not in out and isinstance(methods, dict):
        for entry in methods.values():
            if isinstance(entry, dict):
                result = entry.get("result")
                if isinstance(result, dict) and isinstance(result.get("species"), str):
                    out["species"] = str(result["species"]).strip()
                    break
    for key in ("method", "mode"):
        if isinstance(data.get(key), str):
            out["method"] = str(data[key])
            break
    return out


def parse_assembly_stats(path: Path) -> dict[str, Any]:
    """seqkit stats -T：contig 数、总长、N50、GC。

    表头形如 ``file format type num_seqs sum_len min_len avg_len max_len ... N50 ... GC(%)``，
    列随版本可能增减，按表头名定位。
    """
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as fh:
            rows = list(csv.reader(fh, delimiter="\t"))
    except OSError:
        return {}
    if len(rows) < 2:
        return {}
    header = [h.strip() for h in rows[0]]
    values = rows[1]

    def col(*names: str) -> str | None:
        for name in names:
            if name in header:
                idx = header.index(name)
                if idx < len(values):
                    return values[idx]
        return None

    out: dict[str, Any] = {}
    contigs = _num(col("num_seqs"))
    total = _num(col("sum_len"))
    n50 = _num(col("N50"))
    gc = _num(col("GC(%)", "GC%", "GC"))
    if contigs is not None:
        out["contigs"] = int(contigs)
    if total is not None:
        out["total_length"] = int(total)
    if n50 is not None:
        out["n50"] = int(n50)
    if gc is not None:
        out["gc_pct"] = round(float(gc), 2)
    return out


def parse_mlst(path: Path) -> dict[str, Any]:
    """gmlst MLST：ST 与方案名。"""
    data = _read_json(path)
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("st", "ST", "sequence_type"):
        value = data.get(key)
        if value is not None and str(value).strip():
            out["st"] = str(value).strip()
            break
    for key in ("scheme", "scheme_name", "pubmlst_scheme"):
        if isinstance(data.get(key), str) and data[key].strip():
            out["scheme"] = str(data[key]).strip()
            break
    return out


def parse_gspec_typing(path: Path) -> dict[str, Any]:
    """gspec typing（血清型/基因型）：血清型与各库命中概览。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("serotype", "serogroup"):
        if isinstance(data.get(key), str) and data[key].strip():
            out[key] = str(data[key]).strip()
    databases = data.get("databases")
    if isinstance(databases, dict):
        hits: dict[str, int] = {}
        for name, entry in databases.items():
            count = _count_hits(entry)
            if count is not None:
                hits[str(name)] = count
        if hits:
            out["database_hits"] = hits
        # 血清型常见嵌在物种专用库结果内
        if "serotype" not in out:
            for entry in databases.values():
                if isinstance(entry, dict):
                    for key in ("serotype", "serogroup"):
                        value = entry.get(key)
                        if isinstance(value, str) and value.strip():
                            out[key] = value.strip()
                            break
                if "serotype" in out:
                    break
    return out


def _count_hits(entry: Any) -> int | None:
    """gspec screen/typing 单个库结果的命中计数（尽力而为）。"""
    if isinstance(entry, list):
        return len(entry)
    if isinstance(entry, dict):
        for key in ("hits", "results", "matches", "genes"):
            value = entry.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return len(value)
        count = _num(entry.get("hit_count"))
        if count is not None:
            return int(count)
    return None


def parse_amrfinder(path: Path) -> dict[str, Any]:
    """AMRFinderPlus TSV：命中条数。"""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = sum(1 for line in fh if line.strip())
    except OSError:
        return {}
    hits = max(0, lines - 1)  # 首行表头
    return {"hits": hits}


def parse_screen(path: Path) -> dict[str, Any]:
    """gspec screen（vfdb/card/plasmidfinder）：命中计数。"""
    data = _read_json(path)
    count = _count_hits(data)
    if count is None and isinstance(data, dict):
        count = _count_hits(data.get("databases"))
    return {"hits": count} if count is not None else {}


def parse_summary(path: Path) -> dict[str, Any]:
    """prelim/final summary：关键结论字段的窄带子集。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    steps = data.get("steps")
    if isinstance(steps, dict):
        done = sorted(k for k, v in steps.items() if v not in (None, {}, []))
        if done:
            out["steps_done"] = done
        species = steps.get("species")
        if isinstance(species, dict):
            name = species.get("species") or species.get("verdict")
            if isinstance(name, str) and name.strip():
                out["species"] = name.strip()
        serotype = steps.get("serotype")
        if isinstance(serotype, dict) and isinstance(serotype.get("serotype"), str):
            out["serotype"] = str(serotype["serotype"]).strip()
        mlst = steps.get("mlst")
        if isinstance(mlst, dict):
            st = mlst.get("st") or mlst.get("ST")
            if st is not None and str(st).strip():
                out["st"] = str(st).strip()
        amr = steps.get("amr")
        if isinstance(amr, dict):
            count = _num(amr.get("hit_count")) or _num(amr.get("hits"))
            if count is not None:
                out["amr_count"] = int(count)
    if isinstance(data.get("prelim"), bool):
        out["prelim"] = data["prelim"]
    return out


def parse_report_html(path: Path) -> dict[str, Any]:
    """完整报告 HTML：只取大小作为存在证据（内容不进事件）。"""
    try:
        return {"bytes": path.stat().st_size}
    except OSError:
        return {}


def parse_cgmlst_summary(path: Path) -> dict[str, Any]:
    """cgMLST cohort 摘要：样本数等队列级概览。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("n_samples", "sample_count", "n"):
        count = _num(data.get(key))
        if count is not None:
            out["n_samples"] = int(count)
            break
    samples = data.get("samples")
    if "n_samples" not in out and isinstance(samples, list):
        out["n_samples"] = len(samples)
    group = data.get("group") or data.get("name")
    if isinstance(group, str) and group.strip():
        out["group"] = group.strip()
    return out


def parse_step_result(parser_key: str, path: Path) -> dict[str, Any]:
    """按步键分发解析；任何异常都吞掉返回 ``{}``（展示绝不影响分析）。"""
    parsers = {
        "species": parse_species,
        "assembly": parse_assembly_stats,
        "mlst": parse_mlst,
        "serotype": parse_gspec_typing,
        "amr": parse_amrfinder,
        "vfdb": parse_screen,
        "card": parse_screen,
        "plasmid": parse_screen,
        "prelim_summary": parse_summary,
        "final_summary": parse_summary,
        "report": parse_report_html,
        "cgmlst": parse_cgmlst_summary,
    }
    parser = parsers.get(parser_key)
    if parser is None:
        return {}
    try:
        result = parser(path)
    except Exception:
        return {}
    return result if isinstance(result, dict) else {}
