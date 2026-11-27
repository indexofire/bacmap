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
    SPECIMEN_METADATA = "specimen_metadata"
    LIBRARY_METADATA = "library_metadata"
    LAB_RESULT = "lab_result"
    LAB_RESULT_UPDATE = "lab_result_update"
    LAB_RESULT_DELETE = "lab_result_delete"
    METADATA_DELETE = "metadata_delete"
    SPECIMEN_METADATA_DELETE = "specimen_metadata_delete"
    LIBRARY_METADATA_DELETE = "library_metadata_delete"
    SPECIMEN_CREATE = "specimen_create"
    ISOLATE_CREATE = "isolate_create"
    BATCH = "batch"
    KNOWLEDGE_IMPORT = "knowledge_import"
    KNOWLEDGE_APPROVE = "knowledge_approve"
    SPECIMEN_ASSIGN = "specimen_assign"


class MetadataRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["metadata"] = "metadata"
    strain_id: str = Field(min_length=1, max_length=128)
    sample_id: str = Field(default="", max_length=128)
    fields: dict[str, Any] = Field(default_factory=dict)
    # Excel/CSV 中不在白名单内的自定义湿实验列（JSON 存储）；不得覆盖已知列。
    extra: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    # Web 编辑用：true = 全量替换（未给出的核心列/extra 清空），false = 合并。
    replace: bool = False
    # 审核通过后把无主数据归属到提交人（空值不改变归属）。
    owner_user_id: str = Field(default="", max_length=64)

    def model_post_init(self, __context: Any) -> None:
        unknown = sorted(set(self.fields) - set(METADATA_FIELDS))
        if unknown:
            raise ValueError(f"unknown metadata field(s): {unknown}")
        if "strain_id" in self.fields or "sample_id" in self.fields:
            raise ValueError("strain_id/sample_id are top-level, not part of fields")
        reserved = set(METADATA_FIELDS) | {"strain_id", "sample_id", "extra"}
        bad_extra = sorted(set(self.extra) & reserved)
        if bad_extra:
            raise ValueError(f"extra cannot override known field(s): {bad_extra}")


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
    subject_type: Literal["isolate", "specimen"] = "isolate"
    subject_id: str = ""
    extra: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    owner_user_id: str = Field(default="", max_length=64)


class LabResultUpdate(BaseModel):
    """部分更新一条化验结果；只改给出的字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["lab_result_update"] = "lab_result_update"
    result_id: str = Field(min_length=1, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    test_name: str | None = Field(default=None, max_length=128)
    result: str | None = Field(default=None, max_length=256)
    unit: str | None = None
    method: str | None = None
    interpretation: str | None = None
    standard: str | None = None
    tested_date: str | None = None
    tested_by: str | None = None
    lab: str | None = None
    notes: str | None = None
    subject_type: Literal["isolate", "specimen"] | None = None
    subject_id: str | None = None
    extra: dict[str, str | int | float | bool | None] | None = None

    def model_post_init(self, __context: Any) -> None:
        changed = [
            value
            for name, value in self.model_dump(exclude={"kind", "result_id"}).items()
            if value is not None
        ]
        if not changed:
            raise ValueError("lab_result_update requires at least one field")


class LabResultDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["lab_result_delete"] = "lab_result_delete"
    result_id: str = Field(min_length=1, max_length=64)


class MetadataDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["metadata_delete"] = "metadata_delete"
    strain_id: str = Field(min_length=1, max_length=128)


class SpecimenMetadataDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["specimen_metadata_delete"] = "specimen_metadata_delete"
    specimen_id: str = Field(min_length=1, max_length=128)


class LibraryMetadataDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["library_metadata_delete"] = "library_metadata_delete"
    library_id: str = Field(min_length=1, max_length=128)


class SpecimenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["specimen_create"] = "specimen_create"
    specimen_id: str = Field(min_length=1, max_length=128)
    origin: str = Field(default="manual", max_length=64)
    note: str = Field(default="", max_length=2000)
    owner_user_id: str = Field(default="", max_length=64)


class IsolateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["isolate_create"] = "isolate_create"
    isolate_id: str = Field(min_length=1, max_length=128)
    specimen_id: str = Field(default="", max_length=128)
    lineage_id: str | None = Field(default=None, max_length=128)
    passage: int | None = Field(default=None, ge=0)
    owner_user_id: str = Field(default="", max_length=64)


class SpecimenMetadataRecord(BaseModel):
    """样本级湿实验信息（患者/采样/来源）；与 specimen 挂钩。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["specimen_metadata"] = "specimen_metadata"
    specimen_id: str = Field(min_length=1, max_length=128)
    data: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    replace: bool = False
    owner_user_id: str = Field(default="", max_length=64)


class LibraryMetadataRecord(BaseModel):
    """测序数据级元数据；WGS 可挂 isolate，mNGS 只挂 specimen。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["library_metadata"] = "library_metadata"
    library_id: str = Field(min_length=1, max_length=128)
    specimen_id: str = ""
    isolate_id: str = ""
    data: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    replace: bool = False
    owner_user_id: str = Field(default="", max_length=64)


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


class SpecimenAssign(BaseModel):
    """把测序数据/菌株关联到样本（v1.10.27 身份模型，经任务层审计写入）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["specimen_assign"] = "specimen_assign"
    specimen_id: str = Field(min_length=1, max_length=128)
    isolates: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    owner_user_id: str = Field(default="", max_length=64)

    def model_post_init(self, __context: Any) -> None:
        if not self.isolates and not self.datasets:
            raise ValueError("give at least one isolate or dataset to assign")


class KnowledgeApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["knowledge_approve"] = "knowledge_approve"
    entry_id: int = Field(ge=1)


class BatchRecord(BaseModel):
    """Excel/CSV 批量导入：一个任务写多行元数据/化验结果（仍经 record 工作流）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["batch"] = "batch"
    rows: list[
        Annotated[
            MetadataRecord
            | SpecimenMetadataRecord
            | LibraryMetadataRecord
            | LabResultRecord,
            Field(discriminator="kind"),
        ]
    ] = Field(min_length=1, max_length=5000)


RecordTask = Annotated[
    MetadataRecord
    | SpecimenMetadataRecord
    | LibraryMetadataRecord
    | LabResultRecord
    | LabResultUpdate
    | LabResultDelete
    | MetadataDelete
    | SpecimenMetadataDelete
    | LibraryMetadataDelete
    | SpecimenCreate
    | IsolateCreate
    | BatchRecord
    | KnowledgeImport
    | KnowledgeApprove
    | SpecimenAssign,
    Field(discriminator="kind"),
]
RecordModel = (
    MetadataRecord
    | SpecimenMetadataRecord
    | LibraryMetadataRecord
    | LabResultRecord
    | LabResultUpdate
    | LabResultDelete
    | MetadataDelete
    | SpecimenMetadataDelete
    | LibraryMetadataDelete
    | SpecimenCreate
    | IsolateCreate
    | BatchRecord
    | KnowledgeImport
    | KnowledgeApprove
    | SpecimenAssign
)
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
