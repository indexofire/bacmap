# 汇总报告：聚合所有步骤结果为 JSON
#
# v1.4.24：按病原注册表**条件依赖**——只请求该物种适用的步骤产物，不适用者
#   既不进入 DAG、也不触发外部工具（SISTR 只属沙门菌；志贺菌血清型走 gspec shi_sero；
#   ecoh 只属大肠埃希菌；vpara 只属副溶血弧菌；DEC 致病型只属 ECO/SHI）。


from bacmap.core.analysis.routing import report_inputs as _routing_report_inputs  # noqa: E402


def _report_inputs(wc):
    """该样本适用的步骤产物（按 registry 路由；不适用者不进入 DAG）。

    assembly 直入样本（无 reads）不依赖 fastp 产物（v1.4.33）。
    """
    return _routing_report_inputs(
        wc.sample,
        SAMPLES_DF.loc[wc.sample, "species"],
        str(WORKDIR),
        has_qc=wc.sample in READS_SAMPLES,
        selection=TOOL_SELECTION,
    )


def _prelim_inputs(wc):
    """v1.10.23 流式首屏：同 _report_inputs 但**不含注释**——分钟级完成，
    供引擎生成初步 summary/报告（web 先看到分型与 AMR 结果；注释后升级）。
    """
    files = _report_inputs(wc)
    return {k: v for k, v in files.items() if k != "annotation"}


rule report_summary_prelim:
    """初步汇总（不含注释）：快步骤（物种/MLST/血清型/AMR/质粒）完成即产出。"""
    input:
        unpack(_prelim_inputs)
    output:
        summary = str(WORKDIR) + "/{sample}/report/{sample}_summary.prelim.json"
    script:
        "../scripts/collect_summary.py"


rule report_summary:
    input:
        unpack(_report_inputs)
    output:
        summary = str(WORKDIR) + "/{sample}/report/{sample}_summary.json"
    script:
        "../scripts/collect_summary.py"
