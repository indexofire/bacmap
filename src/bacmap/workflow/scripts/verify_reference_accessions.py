"""核验参考基因组 accession 清单（NCBI esummary，部署/评审用）。

对 `reference_accessions.yaml` 的每个 accession 取 NCBI esummary 标题，检查其是否
包含该条目 `organism` 的关键词（属名 + 种名），避免**张冠李戴的 accession** 进入清单
（错误的参考基因组会污染 SNP 树）。

用法：
    python verify_reference_accessions.py --manifest <yaml> [--email x@y] [--strict]
退出码：默认 0（报告性质）；`--strict` 时任一失败 → 1。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _tokens(organism: str) -> list[str]:
    """取属名 + 种名两个关键词（跳过 strain/serovar 等非分类词）。"""
    words = [w.strip(".,") for w in organism.split() if w.strip(".,")]
    return [w.lower() for w in words[:2]]


def _title(accession: str, email: str | None, timeout: int) -> str | None:
    base = accession.split(".")[0]
    params = f"db=nuccore&id={base}&retmode=json&tool=bacmap"
    if email:
        params += f"&email={email}"
    req = urllib.request.Request(  # noqa: S310 —— 公网 NCBI 只读查询
        f"{_ESUMMARY}?{params}", headers={"User-Agent": "bacmap/ref-verify"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    result = data.get("result") or {}
    uids = result.get("uids") or []
    if not uids:
        return None
    return str(result.get(uids[0], {}).get("title", "")) or None


def verify(manifest: dict, *, email: str | None, timeout: int) -> list[dict]:
    report: list[dict] = []
    for group, spec in (manifest.get("genomes") or {}).items():
        organism = str(spec.get("organism", ""))
        expected = _tokens(organism)
        for accession in spec.get("accessions") or []:
            try:
                title = _title(str(accession), email, timeout)
            except (OSError, ValueError) as exc:
                report.append({"group": group, "accession": accession, "status": "error", "detail": str(exc)})
                continue
            if not title:
                report.append({"group": group, "accession": accession, "status": "not_found"})
                continue
            low = title.lower()
            ok = all(tok in low for tok in expected)
            report.append(
                {
                    "group": group,
                    "accession": accession,
                    "status": "ok" if ok else "mismatch",
                    "title": title,
                    "expected": expected,
                }
            )
    return report


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser(description="Verify reference accessions against NCBI")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--email", default="")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8")) or {}
    report = verify(manifest, email=(args.email or None), timeout=args.timeout)
    bad = 0
    for row in report:
        mark = {"ok": "✅", "mismatch": "❌", "not_found": "❔", "error": "⚠️"}[row["status"]]
        detail = row.get("title") or row.get("detail") or ""
        print(f"{mark} {row['group']:14} {row['accession']:16} {row['status']:10} {detail[:70]}", file=sys.stderr)
        if row["status"] != "ok":
            bad += 1
    print(f"\n{len(report)} accession(s), {len(report) - bad} ok, {bad} problem(s)", file=sys.stderr)
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
