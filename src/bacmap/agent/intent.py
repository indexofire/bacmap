"""意图分类（ADR-10 supervisor 第一步）：用户文本 → 封闭任务类型。

结构化输出（无工具——Strata 不能混用 response_format 与 tools，ADR-08）；
LlmUnavailableError 时返回 None，上层走人工确认/确定性路径（C3）。
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from bacmap.agent.llm.gateway import LlmGateway, LlmUnavailableError
from bacmap.tools.spec import DataClass

TASK_TYPES = ("analyze", "curate", "mine", "write")

# 路由输入上限（字符）：防止超大文本进提示词（Web/TUI 已在入口限长，此处兜底）。
_MAX_TEXT_LEN = 8000

_TASK_TYPE_ZH = {
    "analyze": "基因组分析——对测序数据/装配跑管线：QC、组装、物种鉴定、分型、耐药基因筛查等",
    "curate": "本地流行特征库的构建与比对——结果整理入库、与本地特征库/基线数据比对、更新参考集",
    "mine": (
        "数据挖掘——对已有分析结果的二次操作：统计/汇总/比率计算、"
        "菌株间或与历史数据的比较、聚类、可视化图表"
    ),
    "write": "报告或论文撰写——生成文字产物：简报、报告、论文文本",
}

_PROMPT_RULES = (
    "拆解规则：\n"
    "1. 一句话包含多个意图时，全部列出并保持用户所述顺序；\n"
    "2. 同一任务类型的连续子步骤（如「QC、组装和分型」都属 analyze）合并为一个任务，不重复输出；\n"
    "3. 对分析结果的后续操作（统计率、比较、聚类、可视化）属于 mine，不是 analyze；\n"
    "4. 与本地库/基线比对属于 curate。"
)


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
    + "\n\n"
    + _PROMPT_RULES
    + "\n\n用户请求：{text}\n\n不要发明用户没有要求的任务；无法归类时返回空列表。"
)


def classify_intent(text: str, gateway: LlmGateway) -> IntentResult | None:
    """意图 → 任务列表。无 LLM 可用时返回 None（降级信号）。"""
    bounded = text if len(text) <= _MAX_TEXT_LEN else text[:_MAX_TEXT_LEN]
    try:
        result = gateway.structured(
            purpose="intent_classifier",
            prompt=_PROMPT_TEMPLATE.format(text=bounded),
            output_type=IntentResult,
            data_class=DataClass.D0,
        )
    except LlmUnavailableError:
        return None
    if isinstance(result, IntentResult):
        return result
    return IntentResult.model_validate(result)
