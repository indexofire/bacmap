"""ToolSpec 注册表（ADR-04：唯一事实来源）。

由 hermes-bacmap 的 29 项 legacy 表迁移而来，现存 23 项。
v1.4.5 去 bio_vpa_serotype（typing→gapit）；v1.4.7 去
bio_validate_taxonomy / bio_species_compare / bio_db_setup / bio_db_status（物种鉴定→gside）。

trust_layer / effect / output_data_class 为首版判定（ADR-04 冻结字段，
取值可经评审修订；字段本身不可删改）。D 级依据 ADR-16。
"""

from __future__ import annotations

from bacmap.tools import cli, pipeline, schemas, seq, services
from bacmap.tools.spec import DataClass, Effect, ToolSpec, TrustLayer

_V = "0.1.0"  # 迁移期统一版本；改写为类型化输入时逐工具起版本

HandlerEntry = tuple[str, dict, object]

_TOOL_REGISTRY: list[HandlerEntry] = [
    ("bio_seq_stats", schemas.SEQ_STATS, seq.seq_stats),
    ("bio_seq_ops", schemas.SEQ_OPS, seq.seq_ops),
    ("bio_fastq_qc", schemas.FASTQ_QC, seq.fastq_qc),
    ("bio_seq_convert", schemas.SEQ_CONVERT, seq.seq_convert),
    ("bio_blast", schemas.BLAST, cli.blast),
    ("bio_align", schemas.ALIGN, cli.align),
    ("bio_samtools", schemas.SAMTOOLS, cli.samtools_op),
    ("bio_variant", schemas.VARIANT, cli.variant),
    ("bio_analyze_pathogen", schemas.ANALYZE_PATHOGEN, pipeline.analyze_pathogen),
    ("bio_get_result", schemas.GET_RESULT, pipeline.get_result),
    ("bio_verify_result", schemas.VERIFY_RESULT, pipeline.verify_result),
    ("bio_generate_report", schemas.GENERATE_REPORT, pipeline.generate_report),
    ("bio_list_samples", schemas.LIST_SAMPLES, pipeline.list_samples),
    ("bio_gene_scan", schemas.GENE_SCAN, pipeline.gene_scan),
    ("bio_snp_tree", schemas.SNP_TREE, services.snp_tree),
    ("bio_cgmlst", schemas.CGLST_TRACEBACK, services.cgmlst_traceback),
    ("bio_search_samples", schemas.SEARCH_SAMPLES, services.search_samples),
    ("bio_review_flags", schemas.REVIEW_FLAGS, services.review_flags),
    ("bio_diagnose", schemas.DIAGNOSE, pipeline.diagnose_failure),
    ("bio_query_metadata", schemas.QUERY_METADATA, services.query_metadata),
    ("bio_add_metadata", schemas.ADD_METADATA, services.add_metadata),
    ("bio_query_lab_results", schemas.QUERY_LAB_RESULTS, services.query_lab_results),
    ("bio_add_lab_result", schemas.ADD_LAB_RESULT, services.add_lab_result),
]

_META: dict[str, tuple[TrustLayer, Effect, DataClass, bool]] = {
    "bio_seq_stats": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_seq_ops": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_fastq_qc": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_seq_convert": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_blast": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_align": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_samtools": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_variant": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
    "bio_analyze_pathogen": (TrustLayer.L1, Effect.WRITE, DataClass.D2, True),
    "bio_get_result": (TrustLayer.L1, Effect.READ, DataClass.D2, False),
    "bio_verify_result": (TrustLayer.L1, Effect.COMPUTE, DataClass.D2, False),
    "bio_generate_report": (TrustLayer.L1, Effect.COMPUTE, DataClass.D2, False),
    "bio_list_samples": (TrustLayer.L1, Effect.READ, DataClass.D2, False),
    "bio_gene_scan": (TrustLayer.L1, Effect.COMPUTE, DataClass.D2, False),
    "bio_snp_tree": (TrustLayer.L1, Effect.COMPUTE, DataClass.D2, False),
    "bio_cgmlst": (TrustLayer.L1, Effect.COMPUTE, DataClass.D2, False),
    "bio_search_samples": (TrustLayer.L3, Effect.READ, DataClass.D2, False),
    "bio_review_flags": (TrustLayer.L1, Effect.READ, DataClass.D2, False),
    "bio_diagnose": (TrustLayer.L1, Effect.READ, DataClass.D0, False),
    "bio_query_metadata": (TrustLayer.L3, Effect.READ, DataClass.D4, False),
    "bio_add_metadata": (TrustLayer.L3, Effect.WRITE, DataClass.D4, False),
    "bio_query_lab_results": (TrustLayer.L3, Effect.READ, DataClass.D4, False),
    "bio_add_lab_result": (TrustLayer.L3, Effect.WRITE, DataClass.D4, False),
}

_SPECS: dict[str, ToolSpec] = {
    name: ToolSpec(
        name=name,
        version=_V,
        description=str(schema.get("description", name)),
        trust_layer=meta[0],
        effect=meta[1],
        output_data_class=meta[2],
        long_running=meta[3],
        legacy_schema=schema,
        legacy_handler=handler,
    )
    for name, schema, handler in _TOOL_REGISTRY
    if (meta := _META.get(name)) is not None
}


def get(name: str) -> ToolSpec:
    return _SPECS[name]


def list_specs() -> list[ToolSpec]:
    return list(_SPECS.values())


def by_effect(effect: Effect) -> list[ToolSpec]:
    return [s for s in _SPECS.values() if s.effect == effect]


def by_trust_layer(layer: TrustLayer) -> list[ToolSpec]:
    return [s for s in _SPECS.values() if s.trust_layer == layer]


def legacy_table() -> list[HandlerEntry]:
    """Hermes 插件适配器消费的 (name, schema, handler) 三元组（即 _TOOL_REGISTRY 本体）。"""
    return _TOOL_REGISTRY
