"""gapit 分型编排（ADR-20：bacmap 只编排 + 适配）。

对样本声明的每个 gapit 分型库（`pathogens.yaml` 的 `gapit_screens`）执行
`gapit screen --db <db>` → `gapit typing -f json`，把每库结果与状态汇总为一个
JSON：

    {
      "status": "ran" | "skipped" | "empty",
      "databases": {
        "lm_doumith": {"status": "ran", "schemes": {"doumith_serogroup": "IIa"},
                        "confidence": "high", "genes": [...], "raw": {...}},
        "ecoh":       {"status": "no_scheme", "error": "database 'ecoh' carries no typing scheme"}
      }
    }

状态语义（**绝不猜测**）：
- ``ran``        该库有 typing scheme 并给出表型；
- ``no_scheme``  库存在但未 build --typing（gapit 报 TYPING_NO_SCHEME）——如实记录；
- ``skipped``    gapit 不在 PATH；
- ``failed``     screen/typing 执行失败（带 stage/error）。

`ecoli_dec` 由 `run_dec_typing.py` 专门处理（DEC 致病型有独立契约），此处排除。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# 由专用步骤承担的库（避免重复执行）：DEC 致病型走 run_dec_typing.py。
_HANDLED_ELSEWHERE = frozenset({"ecoli_dec"})

_NO_SCHEME_CODES = frozenset({"TYPING_NO_SCHEME"})


def _phenotypes(payload: dict) -> dict[str, str]:
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


def _first_confidence(payload: dict) -> str:
    files = payload.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    phenotypes = entry.get("phenotypes")
    if not isinstance(phenotypes, dict) or not phenotypes:
        return ""
    first = next(iter(phenotypes.values()))
    return str((first or {}).get("confidence") or "") if isinstance(first, dict) else ""


def _first_genes(payload: dict) -> list[str]:
    files = payload.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    genes = entry.get("genes")
    return [str(g) for g in genes] if isinstance(genes, list) else []


def _gapit_error(text: str | None) -> tuple[str, str] | None:
    """从 gapit 输出里取 ``gapit.error/1`` 的 (code, message)；非错误 → None。"""
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
        if isinstance(payload, dict) and payload.get("schema") == "gapit.error/1":
            return str(payload.get("code", "")), str(payload.get("message", ""))
    return None


def _screen_and_type(gapit: str, contigs: Path, db: str, workdir: Path, timeout: int) -> dict:
    screen = workdir / f"{db}_screen.tsv"
    sp = subprocess.run(
        [gapit, "screen", str(contigs), "--db", db, "-o", str(screen)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if sp.returncode != 0 or not screen.is_file():
        # gapit 缺库时以退出码 0 返回 gapit.error/1（DATABASE_NOT_FOUND）——如实记 unavailable，
        # 与真正的执行失败（failed）区分开。
        code, message = _gapit_error(sp.stdout) or _gapit_error(sp.stderr) or ("", "")
        if code == "DATABASE_NOT_FOUND":
            return {"status": "unavailable", "error": message or f"database {db} not installed"}
        return {
            "status": "failed",
            "stage": "screen",
            "error": (message or sp.stderr or "")[-500:],
        }
    tp = subprocess.run(
        [gapit, "typing", str(screen), "-f", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        payload = json.loads(tp.stdout) if tp.stdout.strip() else {}
    except ValueError:
        return {"status": "failed", "stage": "typing", "error": "non-JSON output"}
    if isinstance(payload, dict) and payload.get("schema") == "gapit.error/1":
        code = str(payload.get("code", ""))
        return {
            "status": "no_scheme" if code in _NO_SCHEME_CODES else "failed",
            "error": str(payload.get("message", code)),
        }
    if tp.returncode != 0:
        return {"status": "failed", "stage": "typing", "error": (tp.stderr or "")[-500:]}
    schemes = _phenotypes(payload)
    if not schemes:
        return {"status": "failed", "stage": "typing", "error": "no phenotypes in typing result"}
    return {
        "status": "ran",
        "schemes": schemes,
        "confidence": _first_confidence(payload),
        "genes": _first_genes(payload),
        "raw": payload,
    }


def run(contigs: Path, out: Path, workdir: Path, *, databases: list[str], timeout: int) -> int:
    dbs = [d for d in databases if d and d not in _HANDLED_ELSEWHERE]
    gapit = shutil.which("gapit")
    if not dbs:
        out.write_text(
            json.dumps({"status": "empty", "databases": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    if gapit is None:
        out.write_text(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "gapit not found in PATH",
                    "databases": {d: {"status": "skipped"} for d in dbs},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    workdir.mkdir(parents=True, exist_ok=True)
    results = {db: _screen_and_type(gapit, contigs, db, workdir, timeout) for db in dbs}
    status = "ran" if any(r["status"] == "ran" for r in results.values()) else "empty"
    out.write_text(
        json.dumps({"status": status, "databases": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="gapit typing orchestration (registry-driven)")
    ap.add_argument("--contigs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--databases", required=True, help="逗号分隔的 gapit 库名")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    return run(
        Path(args.contigs),
        Path(args.out),
        Path(args.workdir),
        databases=[d.strip() for d in args.databases.split(",") if d.strip()],
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
