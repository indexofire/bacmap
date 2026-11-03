"""Research Workbench（v1.10，P1 薄链路）。

把现有 run 的已产生结果转换为可复核的研究对象：AnalysisSession → StatResult →
Figure / Report / Manuscript。第一阶段只做确定性的 AMR 关联示例，不调用 LLM，
不改变 GOM/Snakemake/DBOS 语义。
"""

from bacmap.research.models import (
    AnalysisSession,
    Artifact,
    ResearchCapabilities,
    ResearchProfile,
    StatResult,
)
from bacmap.research.service import ResearchObjectService, ResearchService

__all__ = [
    "AnalysisSession",
    "Artifact",
    "ResearchCapabilities",
    "ResearchObjectService",
    "ResearchProfile",
    "ResearchService",
    "StatResult",
]
