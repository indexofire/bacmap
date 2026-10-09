"""意图分类（ADR-10 supervisor 第一步）：用户文本 → 封闭任务类型。

结构化输出（无工具——Strata 不能混用 response_format 与 tools，ADR-08）；
LlmUnavailableError 时返回 None，上层走人工确认/确定性路径（C3）。
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from bacmap.agent.llm.gateway import LlmGateway, LlmUnavailableError
from bacmap.tools.spec import DataClass

TASK_TYPES = ("analyze", "curate", "mine", "write")

_TASK_TYPE_ZH = {
    "analyze": "基因组分析（QC/组装/物种/分型/耐药等管线）",
    "curate": "本地流行特征库构建",
    "mine": "数据挖掘（探索性分析）",
    "write": "报告或论文撰写",
}


class IntentTask(BaseModel):
    task_type: str
    summary: str = ""

    @field_validator("task_type")
    @classmethod
    def _closed_set(cls, v: str) -> str:
        if v not in TASK_TYPES:
            raise ValueError(f"task_type must be one of {TASK_TYPES}, got {v!r}")
        return v


class IntentResult(BaseModel):
    tasks: list[IntentTask] = []


_PROMPT_TEMPLATE = (
    "你是病原微生物基因组分析系统的任务路由器。把用户的请求拆解为任务列表。\n"
    "task_type 只能取以下四个值之一：\n"
    + "\n".join(f"- {k}: {v}" for k, v in _TASK_TYPE_ZH.items())
    + "\n\n用户请求：{text}\n\n不要发明用户没有要求的任务；无法归类时返回空列表。"
)


def classify_intent(text: str, gateway: LlmGateway) -> IntentResult | None:
    """意图 → 任务列表。无 LLM 可用时返回 None（降级信号）。"""
    try:
        result = gateway.structured(
            purpose="intent_classifier",
            prompt=_PROMPT_TEMPLATE.format(text=text),
            output_type=IntentResult,
            data_class=DataClass.D0,
        )
    except LlmUnavailableError:
        return None
    if isinstance(result, IntentResult):
        return result
    return IntentResult.model_validate(result)
