"""gside 物种鉴定适配器（ADR-20：bacmap 只留薄适配层）。

调用 `gside species --mode <m>`，把 gside JSON 转成 species_id.json 的
既有形状（species/confidence/detected_markers/...），保持报告与
collect_summary 兼容；原始 gside 输出整体保留在 `gside_raw` 供溯源
（ADR-18：版本以输出内嵌为准）。

gside 恒以退出码 0 结束，单法错误写入对应 method 条目——此处检查
verdict 与 methods 再决定是否降级。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

MODE_MAP = {
    "simple": "marker",
    "marker": "marker",
    "panel": "panel",
    "skani_gtdb": "panel",
    "mash_refseq": "mash_refseq",
    "sourmash": "sourmash",
    "all": "all",
    "standard": "all",
}

FALLBACK = {
    "species": "Unknown",
    "confidence": "low",
    "method": "gside",
    "detected_markers": [],
    "interpretation": "gside species identification failed",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contigs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="simple")
    args = ap.parse_args()

    gside_mode = MODE_MAP.get(args.mode, "marker")
    try:
        proc = subprocess.run(
            ["gside", "species", args.contigs, "--mode", gside_mode],
            capture_output=True,
            text=True,
            timeout=600,
        )
        raw = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        payload = dict(FALLBACK, error=f"gside unavailable: {exc}")
        _write(args.out, payload)
        return 0

    verdict = raw.get("verdict") or {}
    methods = raw.get("methods") or {}
    marker = methods.get("marker") or {}

    if not verdict.get("species"):
        errs = [f"{k}: {v.get('error')}" for k, v in methods.items() if isinstance(v, dict) and v.get("error")]
        payload = dict(FALLBACK, error="; ".join(errs) or "gside returned no verdict")
        _write(args.out, payload)
        return 0

    payload = {
        "species": verdict.get("species"),
        "confidence": verdict.get("confidence"),
        "method": "+".join(verdict.get("basis") or ["gside"]),
        "detected_markers": marker.get("detected_markers") or [],
        "database": marker.get("database"),
        "matched_rule": marker.get("matched_rule"),
        "interpretation": marker.get("interpretation") or f"Identified as {verdict.get('species')} (gside)",
        "gside_version": raw.get("version"),
        "gside_mode": gside_mode,
        "gside_raw": raw,
    }
    _write(args.out, payload)
    return 0


def _write(out: str, payload: dict) -> None:
    from pathlib import Path

    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
