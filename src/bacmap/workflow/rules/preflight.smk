# 数据库/参考基因组预检（v1.10.38）：只检查，不下载。
# 引擎在任务提交/工作流入口已做同一预检；此规则是直接 `snakemake` 的兜底。

rule database_preflight:
    output:
        str(WORKDIR) + "/.database_preflight.json"
    params:
        home=str(PROJECT_ROOT),
        workdir=str(WORKDIR),
        samples=" ".join(SAMPLES),
    script:
        "../scripts/preflight_databases.py"
