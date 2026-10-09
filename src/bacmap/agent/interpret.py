"""解读生成（T1 档，ADR-10「生信分析师」的解读职能）。

输入：summary（管线事实）+ 可选本地特征库比对上下文；
输出：结构化解读。**产物必须经分析结论门（tasks.gates.analysis_claims）
校验后才能展示/导出/入库（C5）——本模块只生成，不豁免。**
数据级别 D2（含单株分型结果）：本地端点全量可收，cloud 受限。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from bacmap.agent.llm.gateway import LlmGateway, LlmUnavailableError
from bacmap.tools.spec import DataClass


class InterpretationOutput(BaseModel):
    interpretation_text: str = Field(
        description="给公卫人员读的中文解读，所有结论必须来自给定事实"
    )
    key_findings: list[str] = Field(
        default_factory=list, description="3-5 条关键发现，每条必须有事实支撑"
    )


_PROMPT_TEMPLATE = """你是食源性病原监测的公卫分析师。基于以下管线事实写一份解读。

要求：
- 只使用给定事实中的信息，不得引入外部假设或未经检出的结论
- 牢记阴性结果（未检出耐药基因等）也是结论
- 中文，简洁专业，200 字以内

管线事实（{sample_id}）：
{summary_json}
{baseline_section}
"""


def generate_interpretation(
    summary: dict[str, Any],
    sample_id: str,
    gateway: LlmGateway,
    baseline_context: str | None = None,
) -> InterpretationOutput | None:
    """生成解读；无 LLM 可用（重试耗尽/无端点）时返回 None（C3 降级）。"""
    baseline_section = (
        f"\n本地特征库比对背景（供参考，引用需注明 baseline 版本）：\n{baseline_context}\n"
        if baseline_context
        else ""
    )
    prompt = _PROMPT_TEMPLATE.format(
        sample_id=sample_id,
        summary_json=json.dumps(summary, ensure_ascii=False, indent=1)[:6000],
        baseline_section=baseline_section,
    )
    try:
        result = gateway.structured(
            purpose="interpretation",
            prompt=prompt,
            output_type=InterpretationOutput,
            data_class=DataClass.D2,
        )
    except LlmUnavailableError:
        return None
    if isinstance(result, InterpretationOutput):
        return result
    return InterpretationOutput.model_validate(result)
