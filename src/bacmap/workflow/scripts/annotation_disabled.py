"""Snakemake 脚本：注释关闭时写明确的 disabled 占位（不伪造注释结果）。"""

from __future__ import annotations

import json
from pathlib import Path

payload = {
    "schema": "bacmap.annotation/1",
    "sample": str(snakemake.wildcards.sample),
    "status": "disabled",
    "reason": "BACMAP_ANNOTATION_ENABLED=0 or annotation.enabled=false",
    "summary": None,
    "features": [],
    "eggnog": [],
}
out = Path(snakemake.output.annotation)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
