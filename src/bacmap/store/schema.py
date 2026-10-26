"""按文件的 SQLite schema 迁移清单（ADR-13，v1.6）。

同一物理库可能被多个服务共用，因此清单以**文件**为单位声明，各服务共用同一份：

- ``tasks.sqlite``     → ``bacmap.tasks.spec.TASKS_MIGRATIONS``（任务/审批/计划/事件）
- ``gom.sqlite``       → ``GOM_MIGRATIONS``（GOM + 数据集 + 菌株索引）
- ``runs.sqlite``      → ``bacmap.store.runs.RUNS_MIGRATIONS``
- ``baseline.sqlite``  → ``bacmap.store.baseline.BASELINE_MIGRATIONS``
- ``data/bacmap.sqlite`` → ``data_migrations()``（菌株元数据、检验结果）
- ``data/knowledge.sqlite`` → ``knowledge_migrations()``（文献知识库 + FTS5 触发器）

DDL 的唯一来源仍是各 store 模块（本模块只做**文件级**汇总，避免复制粘贴漂移）；
延迟导入避免循环依赖。只追加，不修改已发布的迁移；旧库由基线迁移
（``CREATE … IF NOT EXISTS``）无损纳管并自动备份。
"""

from __future__ import annotations

from pathlib import Path

from bacmap.store.migrations import Migration, migrate

# 菌株基因型索引与 GOM 同库（gom.sqlite）：DDL 在此声明，供 GOM 迁移 2 与索引服务共用。
STRAIN_INDEX_DDL = (
    """CREATE TABLE IF NOT EXISTS strain_genotype_index (
        strain_id           TEXT PRIMARY KEY,
        organism            TEXT,
        species             TEXT,
        serotype            TEXT,
        serotype_method     TEXT,
        mlst_scheme         TEXT,
        mlst_st             TEXT,
        plasmid_types       TEXT,
        object_id           TEXT,
        analysis_date       TEXT,
        pipeline_version    TEXT,
        updated_at          TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_gi_serotype ON strain_genotype_index(serotype)",
    "CREATE INDEX IF NOT EXISTS idx_gi_mlst_st ON strain_genotype_index(mlst_st)",
    "CREATE INDEX IF NOT EXISTS idx_gi_organism ON strain_genotype_index(organism)",
    "CREATE INDEX IF NOT EXISTS idx_gi_species ON strain_genotype_index(species)",
    """CREATE TABLE IF NOT EXISTS strain_amr_genes (
        strain_id   TEXT NOT NULL,
        gene_name   TEXT NOT NULL,
        database    TEXT NOT NULL DEFAULT '',
        coverage    REAL,
        identity    REAL,
        product     TEXT,
        PRIMARY KEY (strain_id, gene_name, database)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ag_gene ON strain_amr_genes(gene_name)",
    "CREATE INDEX IF NOT EXISTS idx_ag_strain ON strain_amr_genes(strain_id)",
)




def data_migrations() -> tuple[Migration, ...]:
    """data/bacmap.sqlite 的清单：菌株元数据与检验结果共用同一文件。"""
    from bacmap.store.lab_results import DDL_STATEMENTS as LAB_DDL
    from bacmap.store.strain_metadata import DDL_STATEMENTS as META_DDL

    return (
        Migration(1, "baseline: strain metadata, lab results", (*META_DDL, *LAB_DDL)),
    )


def knowledge_migrations() -> tuple[Migration, ...]:
    """data/knowledge.sqlite 的清单（触发器是单条语句，经 execute 逐条执行）。"""
    from bacmap.store.knowledge import DDL_STATEMENTS

    return (Migration(1, "baseline: knowledge entries + fts", DDL_STATEMENTS),)


def ensure_data_schema(db_path: Path | str) -> None:
    """迁移 data/bacmap.sqlite 这一物理文件（三个服务共用）。"""
    migrate(Path(db_path), data_migrations())


def ensure_knowledge_schema(db_path: Path) -> None:
    migrate(db_path, knowledge_migrations())
