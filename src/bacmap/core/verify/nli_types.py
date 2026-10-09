"""NLI Reflector 类型定义（project.md §8.2 Layer 3）。

类型与阈值常量独立成模块，与 ``cgmlst_types.py`` 同一先例——
``nli_reflector.py`` 只保留分解/比对/汇总逻辑。

阈值为何是模块常量而非 config.yaml：0.1 是防御层默认值而非分析阈值，
与 Layer 2 的 ``_CRITICAL_AMR_PATTERNS``（deterministic_verifier 内置
关键耐药模式表）同一先例——防御参数应随代码评审变更而非运行时配置；
调用方可经 ``reflect(text, facts, threshold=...)`` 按次覆盖（工具层
如需暴露再上移 config，届时引用本常量为默认值）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DEFAULT_CONTRADICTION_THRESHOLD = 0.1


class ClaimType(StrEnum):
    SPECIES = "species"
    MLST_ST = "mlst_st"
    SEROTYPE = "serotype"
    AMR_GENE = "amr_gene"
    VIRULENCE_GENE = "virulence_gene"
    PLASMID = "plasmid"


class Verdict(StrEnum):
    ENTAILED = "entailed"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class StrainFacts:
    """Source of Truth：单株管线产物中可被解读文本引用的全部事实。"""

    sample_id: str
    species: str
    mlst_st: str
    serotype: str
    amr_genes: tuple[str, ...]
    virulence_genes: tuple[str, ...]
    plasmids: tuple[str, ...]


@dataclass(frozen=True)
class AtomicClaim:
    claim_type: ClaimType
    value: str
    raw_text: str
    negated: bool = False


@dataclass(frozen=True)
class ClaimVerdict:
    claim: AtomicClaim
    verdict: Verdict
    evidence: str


@dataclass(frozen=True)
class ReflectionResult:
    verdicts: tuple[ClaimVerdict, ...]
    verifiable_count: int
    contradicted_count: int
    contradiction_rate: float
    needs_human_review: bool
    threshold: float
    corroborated_count: int = 0
