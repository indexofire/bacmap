"""可计划任务的类型化参数（v1.5.1，ADR-06 补充）。

计划（plans）只接受这里的严格模型：未知字段拒绝、样本 ID 走白名单、目录参数必须是
绝对路径且三种输入二选一。``task_type`` 是判别字段，供 MCP/CLI 生成 JSON Schema。

mine/write 属开放路径（脚本/草稿需在可信界面审阅），暂不进入计划模型——与
MCP/表单/CLI 只收 analyze/curate 的既有规则一致。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bacmap.tasks.spec import TaskType


def _check_sample_ids(values: list[str]) -> list[str]:
    from bacmap.tools._common import _validate_sample_id

    bad = [v for v in values if not _validate_sample_id(v)]
    if bad:
        raise ValueError(f"invalid sample id(s): {bad!r}")
    if len(set(values)) != len(values):
        raise ValueError("duplicate sample ids")
    return values


class AnalyzeParams(BaseModel):
    """标准分析：已登记样本，或一个待登记的 FASTA / reads 目录（三选一）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: Literal["analyze"] = "analyze"
    samples: list[str] = Field(default_factory=list, description="已登记样本 ID")
    fasta_dir: str | None = Field(default=None, description="组装 FASTA 目录（绝对路径）")
    fastq_dir: str | None = Field(default=None, description="reads 目录（绝对路径）")
    species: str | None = Field(
        default=None, description="目录直入时的物种（码或名称；省略则 FASTA 逐株自动识别）"
    )

    @field_validator("samples")
    @classmethod
    def _samples_ok(cls, v: list[str]) -> list[str]:
        return _check_sample_ids(v)

    @field_validator("fasta_dir", "fastq_dir")
    @classmethod
    def _absolute(cls, v: str | None) -> str | None:
        if v is not None and not PurePosixPath(v).is_absolute():
            raise ValueError(f"directory must be an absolute path: {v!r}")
        return v

    @model_validator(mode="after")
    def _one_input(self) -> AnalyzeParams:
        given = sum(bool(x) for x in (self.samples, self.fasta_dir, self.fastq_dir))
        if given != 1:
            raise ValueError("analyze needs exactly one of samples / fasta_dir / fastq_dir")
        if self.species is not None and self.samples:
            raise ValueError("species only applies to fasta_dir / fastq_dir")
        return self


class CurateScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pathogen: str | None = Field(default=None, description="病原（物种码或名称子串）")
    strains: list[str] | None = Field(default=None, description="限定纳入的菌株 ID")

    @field_validator("strains")
    @classmethod
    def _strains_ok(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_sample_ids(v)


class CurateParams(BaseModel):
    """本地流行特征库候选版本构建（ADR-19；发布仍需门 + 人工签名）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: Literal["curate"] = "curate"
    scope: CurateScope = Field(default_factory=CurateScope)


class MineParams(BaseModel):
    """开放路径挖掘：脚本在沙箱内执行（无网络、只读挂载），产物过挖掘门并需签字。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: Literal["mine"] = "mine"
    objective: str = Field(min_length=1, max_length=500)
    script: str = Field(
        min_length=1, max_length=20_000, description="Python 脚本全文（沙箱内执行）"
    )
    input_paths: list[str] = Field(default_factory=list, description="只读挂载的输入（绝对路径）")
    sandbox_image: str = Field(
        default="docker://python:3.12-slim", min_length=1, max_length=200
    )
    input_data_class: Literal["D2", "D3", "D4"] = "D3"

    @field_validator("input_paths")
    @classmethod
    def _absolute_paths(cls, v: list[str]) -> list[str]:
        for p in v:
            if not PurePosixPath(p).is_absolute():
                raise ValueError(f"input path must be absolute: {p!r}")
        return v


class WriteParams(BaseModel):
    """开放路径撰写：成稿过引用门，人工签字后才能导出。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: Literal["write"] = "write"
    objective: str = Field(min_length=1, max_length=500)
    draft: str = Field(min_length=1, max_length=40_000, description="成稿全文")
    known_citations: list[str] = Field(
        default_factory=list, description="可引用标识符；空则由知识库已审核条目决定"
    )


PlannableTask = Annotated[
    AnalyzeParams | CurateParams | MineParams | WriteParams, Field(discriminator="task_type")
]


def task_type_of(task: AnalyzeParams | CurateParams | MineParams | WriteParams) -> TaskType:
    return TaskType(task.task_type)


def engine_params(
    task: AnalyzeParams | CurateParams | MineParams | WriteParams,
) -> dict[str, Any]:
    """转换为引擎参数字典（去掉判别字段与空值）。"""
    data = task.model_dump(mode="json", exclude={"task_type"}, exclude_none=True)
    if isinstance(task, AnalyzeParams) and not task.samples:
        data.pop("samples", None)
    return data
