"""gside 物种鉴定适配器（ADR-20：bacmap 只留薄适配层）。

调用 `gside species --mode <m>`，把 gside JSON 转成 species_id.json 的
既有形状（species/confidence/detected_markers/...），保持报告与
collect_summary 兼容；原始 gside 输出整体保留在 `gside_raw` 供溯源
（ADR-18：版本以输出内嵌为准）。

**升级阶梯（v1.4.17）**：`--escalation` 时按 `marker → panel → mash_refseq →
sourmash → all` 依次升档，直到拿到可识别 verdict；每档结果记入 `attempts`。
数据库未就绪的档会自行落空（不崩溃）——全档失败则保持 `Unknown` 并带诊断，
提示人工 `gside db setup --tier <tier>`。

gside 恒以退出码 0 结束，单法错误写入对应 method 条目——此处按 verdict 与
attempts 决定是否降级。
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

# gside 档位从弱到强的顺序（决定升级阶梯的区间）。
MODE_ORDER = ("marker", "panel", "mash_refseq", "sourmash", "all")

FALLBACK = {
    "species": "Unknown",
    "confidence": "low",
    "method": "gside",
    "detected_markers": [],
    "interpretation": "gside species identification failed",
}


def _ladder(start: str, escalation: bool, max_mode: str) -> list[str]:
    """起始档 → 最高档的 gside 模式序列（不升级时只跑起始档）。"""
    g_start = MODE_MAP.get(start, "marker")
    if not escalation:
        return [g_start]
    g_max = MODE_MAP.get(max_mode, "all")
    i, j = MODE_ORDER.index(g_start), MODE_ORDER.index(g_max)
    return list(MODE_ORDER[i : max(i, j) + 1])


def _is_identified(species: object) -> bool:
    """gside 给出可识别物种（非空且非占位/Unknown）。"""
    from bacmap.core.species_codes import UNK, species_code

    return bool(species) and species_code(str(species)) != UNK


def _call_gside(contigs: str, mode: str) -> tuple[dict | None, str | None]:
    try:
        proc = subprocess.run(
            ["gside", "species", contigs, "--mode", mode],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"gside unavailable: {exc}"
    if not proc.stdout.strip():
        return None, f"empty output (exit {proc.returncode}): {proc.stderr.strip()[:200]}"
    try:
        raw = json.loads(proc.stdout)
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"
    return (raw if isinstance(raw, dict) else None), None


def _payload_from_raw(raw: dict, mode: str, attempts: list[dict], escalated: bool) -> dict:
    verdict = raw.get("verdict") or {}
    methods = raw.get("methods") or {}
    marker = methods.get("marker") or {}
    interp = marker.get("interpretation") or f"Identified as {verdict.get('species')} (gside)"
    if escalated:
        interp = f"{interp} [escalated to {mode}]"
    return {
        "species": verdict.get("species"),
        "confidence": verdict.get("confidence"),
        "method": "+".join(verdict.get("basis") or ["gside"]),
        "detected_markers": marker.get("detected_markers") or [],
        "database": marker.get("database"),
        "matched_rule": marker.get("matched_rule"),
        "interpretation": interp,
        "gside_version": raw.get("version"),
        "gside_mode": mode,
        "escalated": escalated,
        "attempts": attempts,
        "gside_raw": raw,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contigs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="simple", help="起始档（simple/panel/mash_refseq/...）")
    ap.add_argument(
        "--escalation",
        action="store_true",
        help="未定种时按档位阶梯升级（marker→panel→mash_refseq→sourmash→all）",
    )
    ap.add_argument("--mode-max", default="all", help="升级上限档位")
    args = ap.parse_args()

    ladder = _ladder(args.mode, args.escalation, args.mode_max)
    attempts: list[dict] = []
    chosen: tuple[str, dict] | None = None

    for mode in ladder:
        raw, err = _call_gside(args.contigs, mode)
        if raw is None:
            attempts.append({"mode": mode, "species": None, "confidence": None, "error": err})
            continue
        verdict = raw.get("verdict") or {}
        attempts.append(
            {
                "mode": mode,
                "species": verdict.get("species"),
                "confidence": verdict.get("confidence"),
                "error": None,
            }
        )
        if _is_identified(verdict.get("species")):
            chosen = (mode, raw)
            break

    if chosen is None:
        errors = [a["error"] for a in attempts if a.get("error")]
        payload = dict(
            FALLBACK,
            attempts=attempts,
            escalated=len(ladder) > 1,
            error="; ".join(errors) or "all tiers returned no verdict",
        )
        _write(args.out, payload)
        return 0

    mode, raw = chosen
    _write(args.out, _payload_from_raw(raw, mode, attempts, escalated=(mode != ladder[0])))
    return 0


def _write(out: str, payload: dict) -> None:
    from pathlib import Path

    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
