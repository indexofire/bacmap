"""AI 湿实验映射建议（v1.10.54，P2）：只读顾问与数据分级。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from bacmap.agent.llm.endpoints import DataPolicy, LlmConfig, LlmEndpoint
from bacmap.agent.llm.gateway import DataClassViolationError
from bacmap.agent.llm.import_mapping import (
    ColumnSuggestion,
    ImportMappingAdvice,
    MappingAdviceResult,
    advise_import_mapping,
    build_mapping_prompt,
)
from bacmap.tasks.records import BatchRecord, MetadataRecord, SpecimenMetadataRecord
from bacmap.tools.spec import DataClass


@dataclass
class FakeGateway:
    fail_d4: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def structured(
        self,
        purpose: str,
        prompt: str,
        output_type: Any,
        data_class: DataClass = DataClass.D0,
        role: str | None = None,
    ) -> ImportMappingAdvice:
        self.calls.append(
            {"purpose": purpose, "prompt": prompt, "data_class": data_class}
        )
        if self.fail_d4 and data_class > DataClass.D2:
            raise DataClassViolationError("runtime ceiling")
        return ImportMappingAdvice(
            columns=[
                ColumnSuggestion(
                    layer="isolate",
                    source_column="联系电话",
                    suggested_field="patient_phone",
                    action="map",
                    confidence="high",
                    reason="列名与目标字段同义",
                )
            ],
            warnings=["联系电话属于 D4，请确认仅在本机使用"],
            notes="建议人工复核后写入",
        )


def _record() -> BatchRecord:
    return BatchRecord(
        rows=[
            MetadataRecord(
                strain_id="ISO-1",
                fields={"patient_name": "张三", "province": "广东"},
                extra={"联系电话": "13800000000"},
            ),
            SpecimenMetadataRecord(
                specimen_id="SP-1",
                data={"patient_name": "张三", "sample_type": " stool "},
            ),
        ]
    )


def _config(
    location: Literal["local", "lan", "cloud"],
    ai_max: DataClass = DataClass.D4,
) -> LlmConfig:
    return LlmConfig(
        endpoints={
            "mapper": LlmEndpoint(
                name="mapper",
                location=location,
                base_url="http://127.0.0.1:9/v1",
                model="test",
            )
        },
        routing={"import_mapping": "mapper"},
        policy=DataPolicy(ai_max_data_class=ai_max),
    )


def test_local_endpoint_sees_truncated_values_as_d4():
    gateway = FakeGateway()
    record = _record()
    before = record.model_dump(mode="json")
    result = advise_import_mapping(record, _config("local"), gateway)
    assert result.data_class is DataClass.D4
    assert result.included_values is True
    assert result.location == "local"
    assert gateway.calls and gateway.calls[0]["data_class"] is DataClass.D4
    prompt = gateway.calls[0]["prompt"]
    assert "张三" in prompt and "13800000000" in prompt
    assert "raw-sample-values" in prompt
    # 顾问不改动输入记录
    assert record.model_dump(mode="json") == before


def test_cloud_endpoint_only_gets_schema_and_aggregates():
    gateway = FakeGateway()
    result = advise_import_mapping(_record(), _config("cloud"), gateway)
    assert result.data_class is DataClass.D1
    assert result.included_values is False
    prompt = gateway.calls[0]["prompt"]
    assert "schema-and-aggregates" in prompt
    assert "张三" not in prompt
    assert "13800000000" not in prompt
    assert '"distinct"' in prompt and '"max_length"' in prompt


def test_ai_ceiling_downgrades_values_even_on_local_endpoint():
    gateway = FakeGateway()
    result = advise_import_mapping(
        _record(), _config("local", DataClass.D2), gateway
    )
    assert result.included_values is False
    assert result.data_class is DataClass.D1
    assert "张三" not in gateway.calls[0]["prompt"]


def test_gateway_rejection_falls_back_to_schema_only():
    gateway = FakeGateway(fail_d4=True)
    result = advise_import_mapping(_record(), _config("local"), gateway)
    assert result.included_values is False
    assert result.data_class is DataClass.D1
    assert [c["data_class"] for c in gateway.calls] == [DataClass.D4, DataClass.D1]


def test_prompt_avoids_plain_sequence_values():
    prompt = build_mapping_prompt(
        BatchRecord(
            rows=[
                MetadataRecord(
                    strain_id="ISO-2",
                    fields={"cluster_note": "ACGT" * 80},
                )
            ]
        ),
        include_values=True,
    )
    assert "[sequence omitted]" in prompt
    assert "ACGTACGTACGT" not in prompt


def test_mapping_advice_result_is_serializable():
    result = MappingAdviceResult(
        advice=ImportMappingAdvice(warnings=["x"]),
        endpoint="mapper",
        location="local",
        data_class=DataClass.D1,
        included_values=False,
    )
    assert result.advice.columns == []
    assert isinstance(result.advice.warnings, list)
