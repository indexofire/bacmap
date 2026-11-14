# v1.10.14 细菌基因组注释：QUAST → Bakta → eggNOG-mapper → 合并 JSON。
#
# - QUAST 在组装后提供质量指标（report.tsv / transposed_report.tsv）。
# - Bakta 做基因注释（CDS/tRNA/rRNA/CRISPR/sORF 等），输出 GFF3/FAA/TSV/JSON。
# - eggNOG-mapper 对 Bakta 蛋白做功能分类（COG/GO/KEGG/CAZy/Pfam）。
# - genome_annotation 合并为 annotation/annotation.json，供 report_summary 消费。
#
# 数据库默认路径（可用环境变量覆盖，避免 redeploy 丢配置）：
#   BACMAP_BAKTA_DB          → $BACMAP_HOME/refs/bakta/db-light
#   BACMAP_EGGNOG_DATA_DIR   → $BACMAP_HOME/refs/eggnog
#   BACMAP_ANNOTATION_ENABLED=0 关闭 Bakta/eggNOG（仍写 disabled 占位，不伪造结果）
#
# 数据库准备：scripts/setup_annotation_dbs.py（见 scripts/README.md）。

import os
from pathlib import Path

# v1.10.19 修复：annotation 段嵌在 config 的 `tools:` 下（与 quast 同级），
# 此前误在顶层查找——配置从未生效，全靠默认值运行。
_ANN = config.get("tools", {}).get("annotation", {}) or {}
_ANN_ENABLED = bool(_ANN.get("enabled", True)) and os.environ.get(
    "BACMAP_ANNOTATION_ENABLED", "1"
).strip().lower() not in {"0", "false", "no", "off"}
_BAKTA_CFG = _ANN.get("bakta", {}) or {}
_EGGNOG_CFG = _ANN.get("eggnog", {}) or {}
_QUAST_CFG = config.get("tools", {}).get("quast", {}) or {}
_REFS_ROOT = Path(os.environ.get("BACMAP_REFS_DIR", str(PROJECT_ROOT / "refs")))

BAKTA_DB = (
    os.environ.get("BACMAP_BAKTA_DB")
    or _BAKTA_CFG.get("db")
    or str(_REFS_ROOT / "bakta" / "db-light")
)
EGGNOG_DATA_DIR = (
    os.environ.get("BACMAP_EGGNOG_DATA_DIR")
    or _EGGNOG_CFG.get("data_dir")
    or str(_REFS_ROOT / "eggnog")
)
BAKTA_MIN_CONTIG = int(_BAKTA_CFG.get("min_contig_length", 1))
BAKTA_SKIP_PLOT = "--skip-plot" if bool(_BAKTA_CFG.get("skip_plot", True)) else ""
EGGNOG_TAX_SCOPE = str(_EGGNOG_CFG.get("tax_scope", "Bacteria") or "").strip()
EGGNOG_MODE = str(_EGGNOG_CFG.get("mode", "diamond") or "diamond").strip()
# v1.10.19 速度档位（可选）：
#   sensmode: fast / mid-sensitive / sensitive（emapper 默认）/ 更高档
#   iterate:  多轮递增灵敏度搜索（默认开；关闭可提速 ~3-5x，对肠杆菌等
#             覆盖好的物种注释损失极小）
#   usemem:  diamond 库常驻内存（批量分析时省去重复读盘，需 ~10G 空闲内存）
_EGGNOG_SENSMODE_RAW = str(_EGGNOG_CFG.get("sensmode", "") or "").strip()
EGGNOG_SENSMODE = (
    f"--sensmode {_EGGNOG_SENSMODE_RAW}" if _EGGNOG_SENSMODE_RAW else ""
)
# iterate=false → --dmnd_iterate no；默认（true）交给 emapper 自身默认（迭代开）
EGGNOG_ITERATE_FLAG = "" if _EGGNOG_CFG.get("iterate", True) else "--dmnd_iterate no"
EGGNOG_USEMEM = "--usemem" if _EGGNOG_CFG.get("usemem", False) else ""


rule assembly_qc_quast:
    """组装质控：QUAST 统计 contig 数、N50、GC、错配等。"""
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        report = str(WORKDIR) + "/{sample}/assembly/quast/report.tsv",
        transposed = str(WORKDIR) + "/{sample}/assembly/quast/transposed_report.tsv"
    threads: config["threads"]
    params:
        outdir = str(WORKDIR) + "/{sample}/assembly/quast",
        min_contig = int(_QUAST_CFG.get("min_contig", 500)),
    shell:
        "rm -rf {params.outdir} && mkdir -p {params.outdir} && "
        "quast.py -t {threads} -o {params.outdir} --no-html --silent "
        "--min-contig {params.min_contig} {input.contigs}"


rule assembly_contig_stats:
    """逐 contig 长度/GC（seqkit）：Nx 曲线、长度分布与 GC 分布的数据源。

    QUAST 只给汇总指标（N50/GC 等），无法画分布；这里用外部工具 seqkit 产出
    每 contig 的 ``length`` / ``GC``，由 collect_summary 聚合成直方图与 Nx 点。
    """
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        stats = str(WORKDIR) + "/{sample}/assembly/contig_stats.tsv"
    threads: 1
    shell:
        "seqkit fx2tab -n -l -g -H {input.contigs} > {output.stats}"


if _ANN_ENABLED:

    rule bakta_annotate:
        """Bakta 细菌基因组注释（需要 Bakta light/full 数据库）。"""
        input:
            contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta",
            quast = str(WORKDIR) + "/{sample}/assembly/quast/report.tsv",
        output:
            json = str(WORKDIR) + "/{sample}/annotation/bakta/{sample}.json",
            gff3 = str(WORKDIR) + "/{sample}/annotation/bakta/{sample}.gff3",
            faa = str(WORKDIR) + "/{sample}/annotation/bakta/{sample}.faa",
            tsv = str(WORKDIR) + "/{sample}/annotation/bakta/{sample}.tsv",
        threads: config["threads"]
        params:
            outdir = str(WORKDIR) + "/{sample}/annotation/bakta",
            db = BAKTA_DB,
            min_contig_length = BAKTA_MIN_CONTIG,
            skip_plot = BAKTA_SKIP_PLOT,
        shell:
            "set -euo pipefail; "
            "DB=\"{params.db}\"; "
            "if [ ! -d \"$DB\" ]; then "
            "echo \"Bakta database not found: $DB\" >&2; "
            "echo \"Run scripts/setup_annotation_dbs.py or set BACMAP_BAKTA_DB\" >&2; "
            "exit 2; fi; "
            "mkdir -p {params.outdir} && "
            "bakta --db \"$DB\" --output {params.outdir} --prefix {wildcards.sample} "
            "--threads {threads} --min-contig-length {params.min_contig_length} "
            "{params.skip_plot} --force {input.contigs}"

    rule eggnog_annotate:
        """eggNOG-mapper 对 Bakta 蛋白做 COG/GO/KEGG/CAZy/Pfam 功能分类。"""
        input:
            faa = str(WORKDIR) + "/{sample}/annotation/bakta/{sample}.faa"
        output:
            annotations = str(WORKDIR) + "/{sample}/annotation/eggnog/{sample}.emapper.annotations"
        threads: config["threads"]
        params:
            outdir = str(WORKDIR) + "/{sample}/annotation/eggnog",
            data_dir = EGGNOG_DATA_DIR,
            tax_scope = f"--tax_scope {EGGNOG_TAX_SCOPE}" if EGGNOG_TAX_SCOPE else "",
            mode = EGGNOG_MODE,
            sensmode = EGGNOG_SENSMODE,
            iterate = EGGNOG_ITERATE_FLAG,
            usemem = EGGNOG_USEMEM,
        shell:
            "set -euo pipefail; "
            "DATA=\"{params.data_dir}\"; "
            "if [ ! -f \"$DATA/eggnog.db\" ] || [ ! -f \"$DATA/eggnog_proteins.dmnd\" ]; then "
            "echo \"eggNOG-mapper database not found in: $DATA\" >&2; "
            "echo \"Run scripts/setup_annotation_dbs.py or set BACMAP_EGGNOG_DATA_DIR\" >&2; "
            "exit 2; fi; "
            "mkdir -p {params.outdir} && "
            "emapper.py -i {input.faa} -o {wildcards.sample} "
            "--output_dir {params.outdir} --data_dir \"$DATA\" --cpu {threads} "
            "-m {params.mode} {params.tax_scope} {params.sensmode} {params.iterate} "
            "{params.usemem} --override"

    rule genome_annotation:
        """合并 Bakta 注释与 eggNOG 功能分类 → annotation.json。"""
        input:
            bakta = str(WORKDIR) + "/{sample}/annotation/bakta/{sample}.json",
            eggnog = str(WORKDIR) + "/{sample}/annotation/eggnog/{sample}.emapper.annotations",
        output:
            annotation = str(WORKDIR) + "/{sample}/annotation/annotation.json"
        script:
            "../scripts/merge_annotation.py"

else:

    rule genome_annotation:
        """注释关闭：写 disabled 占位，不伪造任何注释结果。"""
        input:
            contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
        output:
            annotation = str(WORKDIR) + "/{sample}/annotation/annotation.json"
        run:
            import json
            from pathlib import Path

            payload = {
                "schema": "bacmap.annotation/1",
                "sample": str(wildcards.sample),
                "status": "disabled",
                "reason": "BACMAP_ANNOTATION_ENABLED=0 or annotation.enabled=false",
                "summary": None,
                "features": [],
                "eggnog": [],
            }
            out = Path(output.annotation)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
