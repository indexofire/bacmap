"""可补跑的分析阶段（reanalyze，v1.10.39）。

阶段名是唯一的对外契约；agent 只能选择这里的 stage，不能传 Snakemake rule。
每个 stage 声明：产物路径、补跑前需要从快照中删除的路径（强制重算）。
MVP 先开放 MLST / AMR / 注释三个叶子阶段；cgMLST/SNP 属于队列阶段，后续扩展。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageSpec:
    name: str
    title: str
    targets: tuple[str, ...]  # 相对 sample 目录
    remove: tuple[str, ...]  # 相对 sample 目录；补跑前删除（目录或文件）

    def targets_for(self, sample: str, run_dir: str) -> list[str]:
        return [f"{run_dir}/{sample}/{rel}" for rel in self.targets]

    def removals_for(self, sample: str, run_dir: str) -> list[str]:
        return [f"{run_dir}/{sample}/{rel}" for rel in self.remove]


STAGES: dict[str, StageSpec] = {
    "mlst": StageSpec(
        name="mlst",
        title="MLST 分型",
        targets=("typing/mlst.json",),
        remove=("typing/mlst.json",),
    ),
    "amr": StageSpec(
        name="amr",
        title="AMRFinderPlus 耐药",
        targets=("amr/amrfinderplus.tsv",),
        remove=("amr/amrfinderplus.tsv",),
    ),
    "annotation": StageSpec(
        name="annotation",
        title="Bakta + eggNOG 注释",
        targets=("annotation/annotation.json",),
        remove=("annotation",),
    ),
}

REANALYZABLE = tuple(STAGES)


def get_stage(name: str) -> StageSpec:
    try:
        return STAGES[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown reanalysis stage {name!r}; allowed: {', '.join(REANALYZABLE)}"
        ) from exc
