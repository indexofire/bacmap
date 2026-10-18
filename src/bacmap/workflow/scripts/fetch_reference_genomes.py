"""部署期参考基因组供给（NCBI，ADR-18/20）。

读 `reference_accessions.yaml`（group → 输出文件 + NCBI accession 列表），经
NCBI E-utilities `efetch` 取 FASTA，拼成单库参考（多复制子按顺序拼接），写入
`--out-dir`；并把 name/version/sha256 合并进 `--refs-dir/manifest.json`
（运行时经 ADR-18 `ref_databases` 记入运行记录）。

**离线/失败不中断**：逐条记录 error 并继续；`--strict` 时只要有一条失败即非零退出。
已有文件默认跳过（`--force` 重取）。**只做编排/取回，不做任何生信算法**（ADR-20）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _fetch_fasta(accession: str, *, email: str | None = None, timeout: int = 120) -> str:
    """取单个 accession 的 FASTA（NCBI efetch）。失败抛 OSError。"""
    params = f"db=nuccore&id={accession}&rettype=fasta&retmode=text&tool=bacmap"
    if email:
        params += f"&email={email}"
    url = f"{_EFETCH}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "bacmap/ref-fetch"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        text = resp.read().decode("utf-8", errors="replace")
    if not text.lstrip().startswith(">"):
        raise OSError(f"NCBI returned no FASTA for {accession}")
    return text.strip() + "\n"


def _compose(accessions: list[str], *, email: str | None, timeout: int) -> str:
    return "".join(_fetch_fasta(acc, email=email, timeout=timeout) for acc in accessions)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _register_manifest(refs_dir: Path, entries: list[dict[str, str]]) -> None:
    """把参考基因组登记进 refs/manifest.json（保留既有条目）。"""
    path = refs_dir / "manifest.json"
    payload: dict[str, Any] = {"databases": []}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("databases"), list):
                payload = loaded
        except (ValueError, OSError):
            pass
    names = {e["name"] for e in entries}
    payload["databases"] = [d for d in payload["databases"] if d.get("name") not in names]
    payload["databases"].extend(entries)
    refs_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser(description="Fetch reference genomes from NCBI (deploy-time)")
    ap.add_argument("--manifest", required=True, help="reference_accessions.yaml")
    ap.add_argument("--out-dir", required=True, help="输出目录（data/reference/genomes）")
    ap.add_argument("--refs-dir", default="", help="refs 目录（登记 manifest.json）")
    ap.add_argument("--only", default="", help="只处理这些 group（逗号分隔）")
    ap.add_argument("--force", action="store_true", help="已存在也重取")
    ap.add_argument("--strict", action="store_true", help="任一失败即非零退出")
    ap.add_argument("--email", default="", help="NCBI 建议的联络邮箱")
    args = ap.parse_args()

    manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8")) or {}
    genomes = manifest.get("genomes") or {}
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    registered: list[dict[str, str]] = []
    for group, spec in genomes.items():
        if only and group not in only:
            continue
        out = out_dir / str(spec["out"])
        version = str(spec.get("version", ""))
        if out.is_file() and not args.force:
            results.append({"group": group, "out": str(out), "status": "present"})
            registered.append(
                {"name": f"ref:{group}", "version": version, "checksum": _sha256_file(out)}
            )
            continue
        accessions = [str(a) for a in spec.get("accessions", [])]
        try:
            fasta = _compose(accessions, email=(args.email or None), timeout=120)
        except (OSError, ValueError) as exc:
            results.append({"group": group, "out": str(out), "status": "failed", "error": str(exc)})
            continue
        out.write_text(fasta, encoding="utf-8")
        results.append({"group": group, "out": str(out), "status": "fetched"})
        registered.append(
            {"name": f"ref:{group}", "version": version, "checksum": _sha256_file(out)}
        )

    if args.refs_dir and registered:
        _register_manifest(Path(args.refs_dir), registered)

    for r in results:
        line = f"{r['group']}: {r['status']}"
        if r.get("error"):
            line += f" ({r['error']})"
        print(line, file=sys.stderr)

    failed = [r for r in results if r["status"] == "failed"]
    return 1 if (args.strict and failed) else 0


if __name__ == "__main__":
    sys.exit(main())
