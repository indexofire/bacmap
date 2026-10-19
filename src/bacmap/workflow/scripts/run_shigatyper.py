"""Shigella 血清型判定（ShigaTyper 外部化；ADR-20：bacmap 只编排 + 适配）。

ShigaTyper 从 Illumina reads 预测志贺菌血清型（含 ipaB 状态）；未来计划迁到
gapit（届时替换本脚本，输出契约保持不变）。

用法：
    python run_shigatyper.py --r1 R1.fastq.gz --r2 R2.fastq.gz \
        --sample NAME --out out.json --workdir <dir>

输出 JSON（与既有 `shigella_serotype.json` 契约兼容）：
    {"engine": "shigatyper", "version": "...", "sample": "...",
     "species": "<prediction>"|"N/A", "serotype": "<prediction>"|"N/A",
     "status": "ran"|"not_shigella"|"unavailable"|"failed",
     "ipaB": "+"|"-"|"", "notes": "..."}

状态语义（**绝不猜测**）：
- ``ran``          给出志贺菌血清型；
- ``not_shigella`` ShigaTyper 判为 "Not Shigella or EIEC"（如实记录，不是失败）；
- ``unavailable``  shigatyper 未安装；
- ``failed``       执行/解析失败（带 stderr 尾部）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _tool_version(shigatyper: str) -> str:
    try:
        proc = subprocess.run(
            [shigatyper, "--version"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def summarize_row(row: dict[str, str]) -> dict[str, str]:
    """ShigaTyper 结果行 → 契约字段（纯函数，便于单测）。"""
    prediction = (row.get("prediction") or "").strip()
    ipab = (row.get("ipaB") or "").strip()
    notes = (row.get("notes") or "").strip()
    if not prediction:
        return {
            "species": "N/A",
            "serotype": "N/A",
            "status": "failed",
            "ipaB": ipab,
            "notes": notes or "ShigaTyper 未输出 prediction 列",
        }
    low = prediction.lower()
    if "not shigella" in low:
        return {
            "species": prediction,
            "serotype": "N/A",
            "status": "not_shigella",
            "ipaB": ipab,
            "notes": notes,
        }
    if low.startswith("shigella"):
        return {
            "species": prediction,
            "serotype": prediction,
            "status": "ran",
            "ipaB": ipab,
            "notes": notes,
        }
    # 非预期文本：如实透传，不臆测
    return {
        "species": prediction,
        "serotype": "N/A",
        "status": "failed",
        "ipaB": ipab,
        "notes": notes or f"未识别的 ShigaTyper prediction: {prediction}",
    }


def _read_tsv(path: Path) -> dict[str, str]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < 2:
        return {}
    header = lines[0].split("\t")
    values = lines[1].split("\t")
    return dict(zip(header, values, strict=False))


def run(
    r1: Path, r2: Path, sample: str, out: Path, workdir: Path, timeout: int = 3600
) -> int:
    tool = shutil.which("shigatyper")
    base: dict[str, str] = {"engine": "shigatyper", "sample": sample}
    if tool is None:
        result = {
            **base,
            "version": "",
            "species": "N/A",
            "serotype": "N/A",
            "status": "unavailable",
            "ipaB": "",
            "notes": "shigatyper 未安装（pixi add shigatyper 后重跑）",
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [tool, "--R1", str(r1), "--R2", str(r2), "-n", sample, "-o", str(workdir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = {
            **base,
            "version": _tool_version(tool),
            "species": "N/A",
            "serotype": "N/A",
            "status": "failed",
            "ipaB": "",
            "notes": f"{type(exc).__name__}: {exc}",
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    tsv = workdir / f"{sample}.tsv"
    if proc.returncode != 0 or not tsv.is_file():
        result = {
            **base,
            "version": _tool_version(tool),
            "species": "N/A",
            "serotype": "N/A",
            "status": "failed",
            "ipaB": "",
            "notes": (proc.stderr or proc.stdout or "")[-500:].strip() or "无输出",
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    result = {**base, "version": _tool_version(tool), **summarize_row(_read_tsv(tsv))}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Shigella serotyping via ShigaTyper")
    ap.add_argument("--r1", required=True)
    ap.add_argument("--r2", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()
    return run(
        Path(args.r1),
        Path(args.r2),
        args.sample,
        Path(args.out),
        Path(args.workdir),
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
