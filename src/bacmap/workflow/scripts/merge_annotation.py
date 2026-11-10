"""Snakemake 脚本：Bakta JSON + eggNOG-mapper annotations → annotation.json。

注意：本脚本经 Snakemake ``script:`` 指令执行——preamble 会被注入到文件
最前面，**不能使用 ``from __future__ import annotations``**（不再是首条
语句 → SyntaxError，v1.10.14 起潜伏、首次启用注释时引爆）。
"""

import json
from pathlib import Path

from bacmap.core.annotation_parse import merge_annotation, parse_eggnog

bakta = json.loads(Path(snakemake.input.bakta).read_text(encoding="utf-8"))
eggnog_text = Path(snakemake.input.eggnog).read_text(encoding="utf-8", errors="replace")
annotation = merge_annotation(
    bakta,
    parse_eggnog(eggnog_text),
    sample=str(snakemake.wildcards.sample),
)
out = Path(snakemake.output.annotation)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
