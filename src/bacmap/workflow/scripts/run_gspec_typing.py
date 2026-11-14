"""gspec 分型编排（ADR-20：bacmap 只编排 + 适配）。

对样本生效的每个 gspec 库执行 screen（gene 库再 typing），把每库结果与状态
汇总为一个 JSON：

    {
      "status": "ran" | "skipped" | "empty",
      "species": {"verdict": "V_parahaemolyticus", "code": "VPA", "confidence": "high"},
      "databases": {
        "lmo_sero": {"kind": "gene", "status": "ran",
                        "schemes": {"doumith_serogroup": "IIa"},
                        "confidence": "high", "genes": [...]},
        "ecoh":       {"kind": "gene", "status": "no_scheme",
                        "error": "database 'ecoh' carries no typing scheme"},
        "vpa_ok":     {"kind": "cluster", "status": "ran",
                        "best_locus": "OL3", "type": "O3",
                        "phenotype": "O3:K6",
                        "phenotypes": {"o_group": {...}, "k_group": {...}}},
        "vpa_pai":    {"kind": "cluster", "status": "ran", "best_locus": "VPaI-5",
                        "loci_count": 8, "loci": [{"locus": "VPaI-5", ...}]}
      }
    }

库清单来源（v1.4.40）：
- 有 ``--species``（工作流路径）时，按 gside verdict → 物种码 → 用户
  ``tool_selection.yaml`` 的 gspec 段 → 生效库列表；低置信度/未识别不路由物种特异库。
- 无 ``--species`` 时沿用 ``--databases``（兼容旧调用/单测）。

状态语义（**绝不猜测**）：
- ``ran``        成功（gene 库有 typing scheme 并给出表型；cluster 库完成 screen）；
- ``no_scheme``  gene 库存在但未 build --typing（gspec 报 TYPING_NO_SCHEME）；
- ``unavailable`` 库未安装（gspec 报 DATABASE_NOT_FOUND）——能力未就绪，不是失败；
- ``skipped``    gspec 不在 PATH；
- ``failed``     screen/typing 执行失败（带 stage/error）。

``eco_dec`` 由 DEC 专用步骤处理，在此排除以避免重复执行；cluster 库的 typing
已在 screen 内完成，绝不再对 TSV 跑 ``gspec typing``。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# 由 DEC 专用步骤承担的库（避免重复执行）：eco_dec 走 run_dec_typing.py。
_HANDLED_ELSEWHERE = frozenset({"eco_dec"})

_NO_SCHEME_CODES = frozenset({"TYPING_NO_SCHEME"})


def _phenotypes(payload: dict[str, Any]) -> dict[str, str]:
    files = payload.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    phenotypes = entry.get("phenotypes")
    if not isinstance(phenotypes, dict):
        return {}
    return {
        str(k): str((v or {}).get("phenotype") or "")
        for k, v in phenotypes.items()
        if isinstance(v, dict)
    }


def _first_confidence(payload: dict[str, Any]) -> str:
    files = payload.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    phenotypes = entry.get("phenotypes")
    if not isinstance(phenotypes, dict) or not phenotypes:
        return ""
    first = next(iter(phenotypes.values()))
    return str((first or {}).get("confidence") or "") if isinstance(first, dict) else ""


def _first_genes(payload: dict[str, Any]) -> list[str]:
    files = payload.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    genes = entry.get("genes")
    if isinstance(genes, list):
        return [str(g) for g in genes]
    # gspec ≥0.10 的 screen JSON 没有 genes 键：从 hits 的 gene 字段去重收集
    # （保持首次出现顺序），供毒力标记（tdh/trh/tlh）等判定使用。
    seen: list[str] = []
    for hit in entry.get("hits") or []:
        if isinstance(hit, dict):
            gene = str(hit.get("gene", "")).strip()
            if gene and gene not in seen:
                seen.append(gene)
    return seen


def _gspec_error(text: str | None) -> tuple[str, str] | None:
    """从 gspec 输出里取 ``gspec.error/1`` 的 (code, message)；非错误 → None。"""
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == "gspec.error/1":
            return str(payload.get("code", "")), str(payload.get("message", ""))
    return None


def _route(species_json: Path) -> tuple[str, str, str]:
    """gside verdict → (物种码, verdict, confidence)；低置信度归 UNK。

    ``UNK`` 仍会查用户覆盖层的 ``UNK`` 段：显式配置了 fallback 库时才跑，
    未配置则返回空列表（不会误用 species-specific 库）。
    """
    from bacmap.core.pathogen_registry import resolve_species
    from bacmap.core.species_codes import UNK

    try:
        payload = json.loads(species_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNK, "", "low"
    if not isinstance(payload, dict):
        return UNK, "", "low"
    verdict = str(payload.get("species") or "")
    confidence = str(payload.get("confidence") or "low")
    # 兼容直接传入 gside 原始 JSON（物种/置信度嵌在 verdict 对象里）。
    raw_verdict = payload.get("verdict")
    if not verdict and isinstance(raw_verdict, dict):
        verdict = str(raw_verdict.get("species") or "")
        confidence = str(raw_verdict.get("confidence") or confidence)
    if verdict in {"", "Unknown", "Mixed/Unknown"} or confidence == "low":
        return UNK, verdict, confidence
    return resolve_species(verdict) or UNK, verdict, confidence


def _effective_databases(
    species_json: Path | None, selection_path: Path | None, sample: str
) -> tuple[list[str], dict[str, str], bool]:
    """Return (databases, species block, routed).

    ``routed=False`` means "no species verdict available, use --databases";
    ``routed=True`` with an empty list means "verdict available but no
    species-specific databases" (low confidence / unknown / user override).
    """
    if species_json is None or not species_json.is_file():
        return [], {}, False
    from bacmap.core.tool_selection import load_selection

    code, verdict, confidence = _route(species_json)
    species_block = {"verdict": verdict, "code": code, "confidence": confidence}
    selection = load_selection(selection_path)
    return selection.effective_gspec_databases(code, sample=sample), species_block, True


def _screen_tsv_genes(path: Path) -> list[str]:
    """从 gene 库的 screen 结果去重收集基因名（gspec ≥0.10 JSON 无 genes 键）。

    v1.10.21：screen 产物为 JSON（``<db>_screen.json``）；旧运行的 TSV 布局
    自动回退。派生给 ``gspec typing`` 的临时 TSV 也走本函数。
    """
    from bacmap.core.utils import parse_abricate_tsv, parse_gspec_report

    try:
        if path.suffix == ".json":
            rows = parse_gspec_report(path.read_text(encoding="utf-8"))
        else:
            rows = parse_abricate_tsv(path.read_text(encoding="utf-8"))
    except OSError:
        return []
    seen: list[str] = []
    for row in rows:
        gene = str(row.get("GENE", "")).strip()
        if gene and gene not in seen:
            seen.append(gene)
    return seen


def _derive_typing_tsv(screen_json: Path) -> Path | None:
    """screen JSON 报告 → ``gspec typing`` 所需的表格（临时文件，调用方删）。

    ``gspec typing`` 只接受 abricate 形状表（FILE/%IDENTITY/%COVERAGE…），
    不认 ``gspec.report/1``——这里用共享解析层把 JSON 命中行写回 TSV。
    """
    import tempfile

    from bacmap.core.utils import parse_gspec_report

    try:
        rows = parse_gspec_report(screen_json.read_text(encoding="utf-8"))
    except OSError:
        return None
    header = [
        "#FILE", "SEQUENCE", "START", "END", "STRAND", "GENE", "COVERAGE",
        "COVERAGE_MAP", "GAPS", "%COVERAGE", "%IDENTITY", "DATABASE",
        "ACCESSION", "PRODUCT", "RESISTANCE",
    ]
    fd, name = tempfile.mkstemp(suffix=".tsv", prefix=f"{screen_json.stem}_", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for row in rows:
            fh.write("\t".join(str(row.get(col, "")) for col in header) + "\n")
    return Path(name)


def _catalog(datadir: str) -> dict[str, Any]:
    from bacmap.tools.tool_catalog import fetch_gspec_catalog

    return fetch_gspec_catalog(datadir=datadir or None)


def _db_kind(catalog: dict[str, Any], db: str) -> str:
    entry = catalog.get(db)
    kind = str(getattr(entry, "kind", "") or "gene")
    # 复合分析库（如 cje_penner）在 screen 内完成 cluster 判定，按 cluster 处理。
    return "cluster" if kind in {"cluster", "composite"} else "gene"


def _cluster_result(document: dict[str, Any]) -> dict[str, Any]:
    files = document.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    best = entry.get("best") if isinstance(entry.get("best"), dict) else {}
    raw_phenotypes = entry.get("phenotypes")
    phenotypes: dict[str, dict[str, Any]] = {}
    if isinstance(raw_phenotypes, dict):
        for name, call in raw_phenotypes.items():
            if isinstance(call, dict):
                detail: dict[str, Any] = {
                    "phenotype": str(call.get("phenotype") or ""),
                    "confidence": str(call.get("confidence") or ""),
                }
                # v1.10.28：保留位点证据（如 VPA 的 OL10/KL4），供报告给出
                # 物种特异的抗原式（旧实现只有 O/H1/H2，副溶血显示为空 H）。
                if call.get("winner_locus"):
                    detail["winner_locus"] = str(call.get("winner_locus"))
                if call.get("winner_coverage_pct") is not None:
                    detail["winner_coverage_pct"] = call.get("winner_coverage_pct")
                if call.get("winner_identity_pct") is not None:
                    detail["winner_identity_pct"] = call.get("winner_identity_pct")
                if isinstance(call.get("notes"), list):
                    detail["notes"] = [str(note) for note in call["notes"]]
                phenotypes[str(name)] = detail
    phenotype = str(best.get("phenotype") or "")
    if not phenotype and phenotypes:
        serotype = phenotypes.get("serotype", {}).get("phenotype", "")
        if serotype:
            phenotype = serotype
        else:
            parts = [
                phenotypes.get(key, {}).get("phenotype", "")
                for key in ("o_group", "k_group")
            ]
            phenotype = ":".join(part for part in parts if part)
    loci = entry.get("loci")
    # 保留 gspec 给出的**全部**位点：PAI 等集合型库一个基因组可携带多个位点，
    # 只留 best 会把其余命中丢掉（v1.10.28，用户报告 VPaI 只剩一个）。
    loci_rows: list[dict[str, Any]] = []
    for item in loci if isinstance(loci, list) else []:
        if not isinstance(item, dict):
            continue
        genes = item.get("genes")
        calls = [g for g in genes if isinstance(g, dict)] if isinstance(genes, list) else []
        present = sum(1 for g in calls if g.get("verdict") == "present")
        partial = sum(1 for g in calls if g.get("verdict") == "partial")
        loci_rows.append(
            {
                "locus": str(item.get("locus") or ""),
                "label": str(item.get("label") or ""),
                "type": str(item.get("type") or ""),
                "coverage_pct": float(item.get("coverage_pct") or 0.0),
                "identity_pct": float(item.get("identity_pct") or 0.0),
                "genes_present": present,
                "genes_partial": partial,
                "genes_absent": max(0, len(calls) - present - partial),
            }
        )
    return {
        "kind": "cluster",
        "status": "ran",
        "best_locus": str(best.get("locus") or ""),
        "type": str(best.get("type") or ""),
        "phenotype": phenotype,
        "phenotypes": phenotypes,
        "loci_count": len(loci_rows) if isinstance(loci, list) else 0,
        "loci": loci_rows,
        "raw_schema": str(document.get("schema") or ""),
    }


def _screen_and_type(
    gspec: str,
    contigs: Path,
    db: str,
    workdir: Path,
    timeout: int,
    *,
    kind: str = "gene",
    threads: int = 1,
    datadir: str = "",
) -> dict[str, Any]:
    common = [gspec, "screen", str(contigs), "--db", db, "-t", str(threads)]
    if datadir:
        common += ["--datadir", datadir]

    if kind == "cluster":
        screen_json = workdir / f"{db}_screen.json"
        sp = subprocess.run(
            [*common, "--format", "json", "-o", str(screen_json)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if sp.returncode != 0 or not screen_json.is_file():
            code, message = _gspec_error(sp.stdout) or _gspec_error(sp.stderr) or ("", "")
            if code == "DATABASE_NOT_FOUND":
                return {"kind": "cluster", "status": "unavailable",
                        "error": message or f"database {db} not installed"}
            return {"kind": "cluster", "status": "failed", "stage": "screen",
                    "error": (message or sp.stderr or "")[-500:]}
        try:
            document = json.loads(screen_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"kind": "cluster", "status": "failed", "stage": "screen",
                    "error": f"invalid cluster JSON: {exc}"}
        if not isinstance(document, dict):
            return {"kind": "cluster", "status": "failed", "stage": "screen",
                    "error": "cluster JSON is not an object"}
        return _cluster_result(document)

    # v1.10.21：gene 库 screen 以 JSON 为结果产物（gspec.report/1，含工具
    # 版本/参数 provenance，供智能体与读取层消费）；`gspec typing` 只吃表格
    # （FILE/%IDENTITY/%COVERAGE），故从 JSON 派生 TSV 到临时文件喂给它，
    # 用完即删——结果目录不再残留机器难读的 TSV 中间产物。
    screen_json = workdir / f"{db}_screen.json"
    sp = subprocess.run(
        [*common, "--format", "json", "-o", str(screen_json)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if sp.returncode != 0 or not screen_json.is_file():
        code, message = _gspec_error(sp.stdout) or _gspec_error(sp.stderr) or ("", "")
        if code == "DATABASE_NOT_FOUND":
            return {"kind": "gene", "status": "unavailable",
                    "error": message or f"database {db} not installed"}
        return {"kind": "gene", "status": "failed", "stage": "screen",
                "error": (message or sp.stderr or "")[-500:]}
    screen = _derive_typing_tsv(screen_json)
    if screen is None:
        return {"kind": "gene", "status": "failed", "stage": "screen",
                "error": f"cannot derive typing table from {screen_json.name}"}
    typing_cmd = [gspec, "typing", str(screen), "--format", "json"]
    if datadir:
        typing_cmd += ["--datadir", datadir]
    tp = subprocess.run(
        typing_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    screen.unlink(missing_ok=True)  # 派生表格用完即删（结果目录只留 JSON）
    payload: dict[str, Any] = {}
    if tp.stdout.strip():
        try:
            raw = json.loads(tp.stdout)
        except ValueError:
            raw = None
        if isinstance(raw, dict):
            payload = raw
    # gspec 0.5.4 的 `typing` 在无 scheme 时把 error JSON 放到 stderr（stdout 为空、
    # 退出码非 0）——必须先识别错误码再判失败，否则 TYPING_NO_SCHEME 会被误记成 failed。
    if payload.get("schema") == "gspec.error/1":
        err: tuple[str, str] | None = (
            str(payload.get("code", "")),
            str(payload.get("message", "")),
        )
    else:
        err = _gspec_error(tp.stderr)
    if err is not None:
        code, message = err
        if code in _NO_SCHEME_CODES:
            status = "no_scheme"
        elif code == "DATABASE_NOT_FOUND":
            status = "unavailable"
        else:
            status = "failed"
        out: dict[str, Any] = {"kind": "gene", "status": status, "error": message or code}
        if status == "failed":
            out["stage"] = "typing"
        if status == "no_scheme":
            # 库可筛查（screen 已成功）、仅无表型 scheme —— 基因命中仍然有效
            # （如 vpa_vf 的 tdh/trh/tlh 存在性判定只依赖 screen）。
            out["genes"] = _screen_tsv_genes(screen_json)
        return out
    if tp.returncode != 0:
        return {"kind": "gene", "status": "failed", "stage": "typing",
                "error": (tp.stderr or "")[-500:]}
    if not payload:
        return {"kind": "gene", "status": "failed", "stage": "typing",
                "error": "non-JSON output"}
    schemes = _phenotypes(payload)
    if not schemes:
        return {"kind": "gene", "status": "failed", "stage": "typing",
                "error": "no phenotypes in typing result"}
    return {
        "kind": "gene",
        "status": "ran",
        "schemes": schemes,
        "confidence": _first_confidence(payload),
        "genes": _first_genes(payload),
        "raw": payload,
    }


def run(
    contigs: Path,
    out: Path,
    workdir: Path,
    *,
    databases: list[str],
    timeout: int,
    species_json: Path | None = None,
    sample: str = "",
    selection_path: Path | None = None,
    threads: int = 1,
    datadir: str = "",
) -> int:
    dbs, species_block, routed = _effective_databases(species_json, selection_path, sample)
    if not routed:
        dbs = list(databases)
    dbs = [d for d in dbs if d and d not in _HANDLED_ELSEWHERE]

    gspec = shutil.which("gspec")
    payload: dict[str, Any] = {}
    if species_block:
        payload["species"] = species_block

    if not dbs:
        out.write_text(
            json.dumps({**payload, "status": "empty", "databases": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    if gspec is None:
        out.write_text(
            json.dumps(
                {
                    **payload,
                    "status": "skipped",
                    "reason": "gspec not found in PATH",
                    "databases": {d: {"status": "skipped"} for d in dbs},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    workdir.mkdir(parents=True, exist_ok=True)
    catalog = _catalog(datadir) if species_json is not None else {}
    results = {
        db: _screen_and_type(
            gspec,
            contigs,
            db,
            workdir,
            timeout,
            kind=_db_kind(catalog, db),
            threads=threads,
            datadir=datadir,
        )
        for db in dbs
    }
    status = "ran" if any(r["status"] == "ran" for r in results.values()) else "empty"
    out.write_text(
        json.dumps({**payload, "status": status, "databases": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="gspec typing orchestration (registry-driven)")
    ap.add_argument("--contigs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--databases", default="", help="逗号分隔的 gspec 库名（旧路径）")
    ap.add_argument("--species", default="", help="gside species_id.json（工作流路径）")
    ap.add_argument("--sample", default="", help="样本 ID（单样本覆盖）")
    ap.add_argument("--selection", default="", help="tool_selection.yaml 路径")
    ap.add_argument("--datadir", default="", help="gspec datadir")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    return run(
        Path(args.contigs),
        Path(args.out),
        Path(args.workdir),
        databases=[d.strip() for d in args.databases.split(",") if d.strip()],
        timeout=args.timeout,
        species_json=Path(args.species) if args.species else None,
        sample=args.sample,
        selection_path=Path(args.selection) if args.selection else None,
        threads=args.threads,
        datadir=args.datadir,
    )


if __name__ == "__main__":
    sys.exit(main())
