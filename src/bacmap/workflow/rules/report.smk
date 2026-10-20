# 汇总报告：聚合所有步骤结果为 JSON
#
# v1.4.24：按病原注册表**条件依赖**——只请求该物种适用的步骤产物，不适用者
#   既不进入 DAG、也不触发外部工具（SISTR 只属沙门菌；ShigaTyper 只属志贺菌；
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
    )


rule report_summary:
    input:
        unpack(_report_inputs)
    output:
        summary = str(WORKDIR) + "/{sample}/report/{sample}_summary.json"
    script:
        "../scripts/collect_summary.py"
