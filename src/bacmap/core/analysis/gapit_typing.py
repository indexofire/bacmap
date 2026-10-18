"""gapit 分型结果归一（`run_gapit_typing.py` 输出 → summary 字段）。

纯适配（ADR-20：判定由 gapit 做）。把每库结果整形成
``{status, databases: {db: {status, schemes, confidence, genes, error}},
serogroup, serogroup_scheme}``；`serogroup` 从 scheme 名含 ``serogroup`` 且给出
表型者取（如 ``doumith_serogroup`` → L. monocytogenes 血清群）。
"""

from __future__ import annotations

from typing import Any


def _db_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"status": "", "schemes": {}, "confidence": "", "genes": [], "error": ""}
    schemes_raw = raw.get("schemes")
    schemes = (
        {str(k): str(v) for k, v in schemes_raw.items()}
        if isinstance(schemes_raw, dict)
        else {}
    )
    genes = raw.get("genes")
    return {
        "status": str(raw.get("status", "")),
        "schemes": schemes,
        "confidence": str(raw.get("confidence", "")),
        "genes": [str(g) for g in genes] if isinstance(genes, list) else [],
        "error": str(raw.get("error", "")) if raw.get("error") else "",
    }


def summarize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "", "databases": {}, "serogroup": "", "serogroup_scheme": ""}
    raw_dbs = payload.get("databases")
    databases: dict[str, Any] = {}
    serogroup = ""
    serogroup_scheme = ""
    if isinstance(raw_dbs, dict):
        for db, raw in raw_dbs.items():
            entry = _db_entry(raw)
            databases[str(db)] = entry
            for scheme_name, phenotype in entry["schemes"].items():
                if "serogroup" in scheme_name.lower() and phenotype:
                    serogroup, serogroup_scheme = phenotype, scheme_name
    return {
        "status": str(payload.get("status", "")),
        "databases": databases,
        "serogroup": serogroup,
        "serogroup_scheme": serogroup_scheme,
    }
