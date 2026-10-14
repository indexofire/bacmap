"""vpara 毒力基因筛查（ADR-20：gapit 自定义库，替代内联 blastn）。

调用 ``gapit screen <contigs> --db vpara_virulence``，把 gapit.report/1 归一化为
本流程既有的 ``virulence.json`` 契约（tdh/trh/tlh 布尔 + 原始命中留档）：

    {"tool": "gapit", "tool_version": "0.5.4", "database": "vpara_virulence",
     "tdh": true, "trh": false, "tlh": true, "n_hits": 2, "hits": [...]}

DB 缺失或 gapit 失败 → 显式非 0 退出（不静默降级；ADR-20 质量门槛要求显式失败）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

TARGET_GENES = ("tdh", "trh", "tlh")

_HIT_FIELDS = (
    "gene",
    "sequence",
    "start",
    "end",
    "strand",
    "coverage_pct",
    "identity_pct",
    "database",
    "accession",
    "product",
)


def normalize(report: dict[str, Any]) -> dict[str, Any]:
    """gapit.report/1 → virulence.json 契约（纯函数，便于单测）。"""
    hits: list[dict[str, Any]] = []
    for entry in report.get("files", []) or []:
        for hit in entry.get("hits", []) or []:
            hits.append({k: hit.get(k) for k in _HIT_FIELDS})
    present = {str(h.get("gene", "")).strip().lower() for h in hits}
    tool = report.get("tool", {}) or {}
    params = report.get("params", {}) or {}
    return {
        "tool": tool.get("name", "gapit"),
        "tool_version": tool.get("version", ""),
        "schema": report.get("schema", ""),
        "database": params.get("db", ""),
        **{gene: (gene in present) for gene in TARGET_GENES},
        "n_hits": len(hits),
        "hits": hits,
    }


def run_screen(contigs: str, db: str, datadir: str | None, timeout: int = 600) -> dict[str, Any]:
    cmd = ["gapit", "screen", str(contigs), "--db", db, "-f", "json"]
    if datadir:
        cmd += ["-D", str(datadir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gapit screen failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vpara virulence screen via gapit")
    parser.add_argument("--contigs", required=True)
    parser.add_argument("--db", default="vpara_virulence")
    parser.add_argument("--datadir", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        report = run_screen(args.contigs, args.db, args.datadir or None)
    except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as exc:
        print(f"ERROR: vpara_virulence screen failed: {exc}", file=sys.stderr)
        return 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(normalize(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
