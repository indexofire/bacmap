"""DEC 致病型结果归一（gapit `ecoli_dec` → 摘要字段）。

纯格式适配（ADR-20：判定由 gapit 做，bacmap 只整理形状）。输入是
``gapit.typing_result/1``（见 `gapit typing -f json`）或我们的 skipped/failed 信封；
输出用于 summary 的 `steps.dec`：

    {"pathotype": "EHEC", "pathotype_scheme": "gb4789_6", "pathotype_confidence": "high",
     "pathotype_genes": ["escV","stx1a","uidA"], "pathotype_runner_up": "STEC",
     "pathotype_schemes": {"gb4789_6": "EHEC", "risk_monitoring": "EHEC"}}

首选 scheme 为 ``gb4789_6``（GB 4789.6-2016）；缺失时取第一个声明的方案。
"""

from __future__ import annotations

from typing import Any

_PREFERRED_SCHEME = "gb4789_6"

_EMPTY: dict[str, Any] = {
    "pathotype": "N/A",
    "pathotype_scheme": "",
    "pathotype_confidence": "",
    "pathotype_genes": [],
    "pathotype_runner_up": "",
    "pathotype_schemes": {},
}


def summarize(payload: Any) -> dict[str, Any]:
    """gapit typing 结果 → 摘要字段；非 ran / 畸形输入 → 空摘要（fail-safe）。"""
    if not isinstance(payload, dict) or payload.get("status") != "ran":
        return dict(_EMPTY)
    files = payload.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    phenotypes = entry.get("phenotypes")
    phenotypes = phenotypes if isinstance(phenotypes, dict) else {}

    scheme = _PREFERRED_SCHEME if _PREFERRED_SCHEME in phenotypes else next(iter(phenotypes), "")
    chosen_raw = phenotypes.get(scheme)
    chosen: dict[str, Any] = chosen_raw if isinstance(chosen_raw, dict) else {}
    runner = chosen.get("runner_up")
    runner_name = runner.get("phenotype") if isinstance(runner, dict) else ""

    genes = entry.get("genes")
    return {
        "pathotype": str(chosen.get("phenotype") or "N/A"),
        "pathotype_scheme": str(scheme),
        "pathotype_confidence": str(chosen.get("confidence") or ""),
        "pathotype_genes": [str(g) for g in genes] if isinstance(genes, list) else [],
        "pathotype_runner_up": str(runner_name or ""),
        "pathotype_schemes": {
            str(k): str((v or {}).get("phenotype") or "")
            for k, v in phenotypes.items()
            if isinstance(v, dict)
        },
    }
