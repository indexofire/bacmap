"""湿实验导入的 AI 映射建议（v1.10.54，P2）。

定位：**顾问，不写数据**。输入是已解析的 ``record`` 批次（列名/自动映射/
未识别列/可选样例行），输出是“某列可能对应哪个目标字段”的建议与风险提示；
调用方（Web 审核页）只展示，不据此修改文件或直接写 GOM。

数据分级：

- 默认只发送**schema 与聚合统计**（列名、非空数、去重数、最大长度），载荷 D1；
  云端点在任何情况下都只能看到这一层。
- 仅当端点为 ``local``/``lan`` 且 ``[llm.data_policy] ai_max_data_class >= D4``
  时，才附带最多 3 行截断样例值（载荷 D4）。网关还会复核 AI 总上限、端点
  位置策略与角色上限；任一更严即拒绝，advisor 自动退回 D1 schema 模式。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from bacmap.agent.llm.endpoints import LlmConfig
from bacmap.agent.llm.gateway import DataClassViolationError, LlmUnavailableError
from bacmap.tasks.records import (
    BatchRecord,
    LabResultRecord,
    LibraryMetadataRecord,
    MetadataRecord,
    SpecimenMetadataRecord,
)
from bacmap.tools.spec import DataClass

MAX_SAMPLE_ROWS = 3
MAX_PROMPT_SAMPLES = 60

# 目标字段目录：用于提示模型，不用于本地强制（写入仍由 record 模型校验）。
_LAYER_FIELDS: dict[str, list[str]] = {
    "isolate": [
        "strain_id",
        "sample_id",
        "submitting_lab",
        "submit_date",
        "receiver",
        "patient_id",
        "patient_name",
        "patient_age",
        "patient_gender",
        "patient_phone",
        "isolation_date",
        "province",
        "city",
        "district",
        "facility",
        "sample_source",
        "sample_type",
        "food_category",
        "food_name",
        "collection_date",
        "symptoms",
        "onset_date",
        "diagnosis",
        "outcome",
        "hospital",
        "outbreak_id",
        "cluster_note",
    ],
    "specimen": [
        "specimen_id",
        "patient_id",
        "patient_name",
        "patient_age",
        "patient_gender",
        "patient_phone",
        "collection_date",
        "specimen_type",
        "sample_source",
        "province",
        "city",
        "district",
        "facility",
        "hospital",
        "symptoms",
        "onset_date",
        "diagnosis",
        "outcome",
        "outbreak_id",
        "cluster_note",
    ],
    "library": [
        "library_id",
        "specimen_id",
        "isolate_id",
        "platform",
        "instrument",
        "layout",
        "read_length",
        "run_id",
        "library_type",
        "library_prep",
        "concentration",
        "volume",
        "qc_status",
        "notes",
    ],
    "lab": [
        "subject_type",
        "subject_id",
        "category",
        "test_name",
        "result",
        "unit",
        "method",
        "interpretation",
        "standard",
        "tested_date",
        "tested_by",
        "lab",
        "notes",
    ],
}


class StructuredGateway(Protocol):
    """advisor 依赖的最小网关面（真实 ``LlmGateway`` 结构兼容，便于测试）。"""

    def structured(
        self,
        purpose: str,
        prompt: str,
        output_type: type[BaseModel],
        data_class: DataClass = DataClass.D0,
        role: str | None = None,
    ) -> BaseModel: ...


class ColumnSuggestion(BaseModel):
    layer: Literal["isolate", "specimen", "library", "lab"] = Field(
        description="该列所属层级"
    )
    source_column: str = Field(description="输入文件中的列名（原样）")
    suggested_field: str = Field(
        default="",
        description="目标字段名；不确定或应保留自定义列时留空",
    )
    action: Literal["map", "keep_extra", "ignore"] = Field(
        default="keep_extra",
        description="map=映射到已知字段；keep_extra=保留为自定义扩展列；ignore=建议忽略",
    )
    confidence: Literal["high", "medium", "low"] = Field(default="medium")
    reason: str = Field(default="", description="一句话理由（中文，≤80 字）")


class ImportMappingAdvice(BaseModel):
    columns: list[ColumnSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description="数据质量/隐私/单位/格式风险（中文，每条≤120 字）",
    )
    notes: str = Field(default="", description="总体说明（中文，≤200 字）")


@dataclass(frozen=True)
class MappingAdviceResult:
    advice: ImportMappingAdvice
    endpoint: str
    location: str
    data_class: DataClass
    included_values: bool


def _layer_rows(record: BatchRecord) -> dict[str, list[dict[str, Any]]]:
    """把 batch 行按层级拆成 {列名: 值} 列表（只读，不改 record）。"""
    out: dict[str, list[dict[str, Any]]] = {
        "isolate": [],
        "specimen": [],
        "library": [],
        "lab": [],
    }
    for row in record.rows:
        if isinstance(row, MetadataRecord):
            isolate_base: dict[str, Any] = {"strain_id": row.strain_id}
            if row.sample_id:
                isolate_base["sample_id"] = row.sample_id
            out["isolate"].append({**isolate_base, **row.fields, **row.extra})
        elif isinstance(row, SpecimenMetadataRecord):
            out["specimen"].append(
                {"specimen_id": row.specimen_id, **row.data}
            )
        elif isinstance(row, LibraryMetadataRecord):
            base: dict[str, Any] = {"library_id": row.library_id}
            if row.specimen_id:
                base["specimen_id"] = row.specimen_id
            if row.isolate_id:
                base["isolate_id"] = row.isolate_id
            out["library"].append({**base, **row.data})
        elif isinstance(row, LabResultRecord):
            out["lab"].append(
                {
                    "subject_type": row.subject_type,
                    "subject_id": row.subject_id or row.strain_id,
                    "category": row.category,
                    "test_name": row.test_name,
                    "result": row.result,
                    "unit": row.unit,
                    "method": row.method,
                    "interpretation": row.interpretation,
                    "standard": row.standard,
                    "tested_date": row.tested_date,
                    "tested_by": row.tested_by,
                    "lab": row.lab,
                    "notes": row.notes,
                    **row.extra,
                }
            )
    return out


def _safe_value(value: Any) -> str:
    text = str(value if value is not None else "").strip().replace("\n", " ")
    if not text:
        return ""
    if len(text) > 200:
        letters = set(text[:200].upper())
        if letters <= set("ACGTN"):
            return "[sequence omitted]"
        return text[:160] + "…"
    return text


def _column_stats(values: list[Any]) -> dict[str, Any]:
    texts = [_safe_value(v) for v in values]
    non_empty = [t for t in texts if t]
    return {
        "non_empty": len(non_empty),
        "distinct": len(set(non_empty)),
        "max_length": max((len(t) for t in non_empty), default=0),
    }


def _layer_payload(
    layer: str, rows: list[dict[str, Any]], *, include_values: bool
) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "columns": [], "per_column": {}}
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    per_column = {
        name: _column_stats([row.get(name) for row in rows]) for name in columns
    }
    payload: dict[str, Any] = {
        "rows": len(rows),
        "columns": columns,
        "known": [c for c in columns if c in _LAYER_FIELDS.get(layer, [])],
        "per_column": per_column,
    }
    if include_values:
        payload["samples"] = {
            name: [v for v in (_safe_value(row.get(name)) for row in rows[:MAX_SAMPLE_ROWS]) if v]
            for name in columns
        }
    return payload


def build_mapping_prompt(record: BatchRecord, *, include_values: bool) -> str:
    layers = _layer_rows(record)
    target_catalog = {
        layer: fields
        for layer, fields in _LAYER_FIELDS.items()
        if layers.get(layer)
    }
    payload: dict[str, Any] = {
        "scope": "raw-sample-values" if include_values else "schema-and-aggregates",
        "target_fields": target_catalog,
        "layers": {
            layer: _layer_payload(layer, rows, include_values=include_values)
            for layer, rows in layers.items()
            if rows
        },
    }
    sample_note = (
        "已附带最多 3 行截断样例值（本地/局域网端点，D4）；这些值仅用于判断列含义。"
        if include_values
        else "未附带任何原始值，只有列名与聚合统计（D1）；不要臆测具体值。"
    )
    return f"""你是湿实验表格字段映射顾问。请检查下列已解析的导入批次，指出哪些列
应映射到目标字段、哪些应保留为自定义扩展列（extra）、哪些建议忽略。

硬性规则：
- 你只给建议，绝不执行写入、绝不声称已写入、绝不猜测 GOM 对象或数据库 ID。
- 只使用给定信息；不确定时 action=keep_extra、confidence=low，并在 reason 说明。
- 已知字段名必须来自 target_fields；自定义列不要强行改名。
- 重点提示：患者姓名/电话等 D4 字段是否放错层级、日期/数值/单位格式风险、
  同一列在不同层级重复、明显无关或全空的列。
- 中文输出；每列一条建议；warnings 只列真正需要人工复核的问题。
- {sample_note}

批次（JSON）：
{json.dumps(payload, ensure_ascii=False, indent=1)[:12000]}
"""


def advise_import_mapping(
    record: BatchRecord,
    config: LlmConfig,
    gateway: StructuredGateway,
) -> MappingAdviceResult:
    """调用 LLM 生成映射建议；无端点或调用失败时抛 LlmUnavailableError。"""
    endpoint = config.resolve("import_mapping")
    if endpoint is None:
        raise LlmUnavailableError("no enabled endpoint for purpose 'import_mapping'")
    raw_allowed = (
        endpoint.location in {"local", "lan"}
        and config.policy.ai_max_data_class >= DataClass.D4
    )
    data_class = DataClass.D4 if raw_allowed else DataClass.D1
    prompt = build_mapping_prompt(record, include_values=raw_allowed)
    try:
        output = gateway.structured(
            purpose="import_mapping",
            prompt=prompt,
            output_type=ImportMappingAdvice,
            data_class=data_class,
        )
    except DataClassViolationError:
        if not raw_allowed:
            raise
        # 运行期策略更严（例如端点/角色/调试开关变化）：退回 schema-only D1。
        raw_allowed = False
        data_class = DataClass.D1
        prompt = build_mapping_prompt(record, include_values=False)
        output = gateway.structured(
            purpose="import_mapping",
            prompt=prompt,
            output_type=ImportMappingAdvice,
            data_class=data_class,
        )
    advice = (
        output
        if isinstance(output, ImportMappingAdvice)
        else ImportMappingAdvice.model_validate(output)
    )
    # 模型输出不可信：截断长度/条数，前端只读展示，绝不回写解析器。
    advice = advice.model_copy(
        update={
            "columns": [
                item.model_copy(
                    update={
                        "source_column": item.source_column[:200],
                        "suggested_field": item.suggested_field[:120],
                        "reason": item.reason[:200],
                    }
                )
                for item in advice.columns[:200]
            ],
            "warnings": [item[:300] for item in advice.warnings[:20]],
            "notes": advice.notes[:500],
        }
    )
    return MappingAdviceResult(
        advice=advice,
        endpoint=endpoint.name,
        location=endpoint.location,
        data_class=data_class,
        included_values=raw_allowed,
    )
