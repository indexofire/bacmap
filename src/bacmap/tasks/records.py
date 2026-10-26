"""记录类任务的参数模型（v1.7，ADR-06 修订）。

元数据、化验结果与文献知识库都是**写操作**：按 ADR-07 只能经任务提交，
因此引入第五类任务 ``record``（用户裁定，冻结文档 v1.7.0）。它们不进入计划
（``PlanService`` 只接受 analyze/curate），也不经 MCP 暴露（D4 写）。

四种记录：
- ``metadata``：菌株元数据 upsert（字段限 store 的已知列，额外键拒绝）；
- ``lab_result``：一条化验结果；
- ``knowledge_import``：文献入暂存（``approved_by`` 为空，等待人审）；
- ``knowledge_approve``：知识库条目的**人审**（引用门只认已审核条目）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from bacmap.store.strain_metadata import METADATA_FIELDS


class RecordKind(StrEnum):
    METADATA = "metadata"
    LAB_RESULT = "lab_result"
    KNOWLEDGE_IMPORT = "knowledge_import"
    KNOWLEDGE_APPROVE = "knowledge_approve"


class MetadataRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["metadata"] = "metadata"
    strain_id: str = Field(min_length=1, max_length=128)
    sample_id: str = Field(default="", max_length=128)
    fields: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        unknown = sorted(set(self.fields) - set(METADATA_FIELDS))
        if unknown:
            raise ValueError(f"unknown metadata field(s): {unknown}")
        if "strain_id" in self.fields or "sample_id" in self.fields:
            raise ValueError("strain_id/sample_id are top-level, not part of fields")


class LabResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["lab_result"] = "lab_result"
    strain_id: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    test_name: str = Field(min_length=1, max_length=128)
    result: str = Field(min_length=1, max_length=256)
    unit: str = ""
    method: str = ""
    interpretation: str = ""
    standard: str = ""
    tested_date: str = ""
    tested_by: str = ""
    lab: str = ""
    notes: str = ""


class KnowledgeImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["knowledge_import"] = "knowledge_import"
    title: str = Field(min_length=1, max_length=512)
    authors: str = ""
    year: int | None = Field(default=None, ge=1800, le=2200)
    source: str = ""
    identifier: str = ""
    content: str = ""
    entry_kind: Literal["literature", "method", "report"] = "literature"


class KnowledgeApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["knowledge_approve"] = "knowledge_approve"
    entry_id: int = Field(ge=1)


RecordTask = Annotated[
    MetadataRecord | LabResultRecord | KnowledgeImport | KnowledgeApprove,
    Field(discriminator="kind"),
]
RecordModel = MetadataRecord | LabResultRecord | KnowledgeImport | KnowledgeApprove
_ADAPTER: TypeAdapter[RecordModel] = TypeAdapter(RecordTask)


# 引擎注入的字段不属于记录载荷（提交入口校验时剔除，避免误报 extra_forbidden）。
ENGINE_KEYS = frozenset({"home", "cores", "submitted_by", "task_id"})


def parse_record(params: dict[str, Any]) -> RecordModel:
    """不可信参数 → 类型化记录；非法输入抛 ValueError（提交入口拒绝）。"""
    payload = {k: v for k, v in params.items() if k not in ENGINE_KEYS}
    try:
        return _ADAPTER.validate_python(payload)
    except ValidationError as exc:
        detail = exc.errors()
        if detail:
            first = detail[0]
            loc = ".".join(str(x) for x in first["loc"])
            raise ValueError(f"invalid record: {loc}: {first['msg']}") from exc
        raise ValueError("invalid record") from exc
