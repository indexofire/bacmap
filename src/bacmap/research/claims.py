"""P2 Claim 门：类型、证据等级与措辞的最小一致性检查。

不是完整科学评审，只阻止最明显的越级：
- association 至少 E2；
- transmission 至少 E3，且需要时间/流行病学证据；
- causal 至少 E3，且需要实验/干预/自然实验设计；
- mechanism 至少 E4，且需要功能证据；
- observation/association 的措辞不得直接写因果/机制/传播。
"""

from __future__ import annotations

from bacmap.research.models import Claim, ClaimType, EvidenceLevel

_RANK = {
    EvidenceLevel.E0: 0,
    EvidenceLevel.E1: 1,
    EvidenceLevel.E2: 2,
    EvidenceLevel.E3: 3,
    EvidenceLevel.E4: 4,
}

_CAUSAL_WORDS = ("cause", "causes", "causal", "导致", "因果", "引起")
_MECHANISM_WORDS = ("mechanism", "mediates", "drives", "介导", "机制", "驱动")
_TRANSMISSION_WORDS = ("transmitted", "transmission", "传播", "传给")


def validate_claim(claim: Claim, decision: str) -> None:
    """在 support/approve 前检查；challenge/reject 不要求证据等级。"""
    from bacmap.config import debug_mode

    if debug_mode():
        return
    if decision not in {"support", "approve"}:
        return
    _validate_level(claim)
    _validate_wording(claim)


def _validate_level(claim: Claim) -> None:
    level = _RANK[claim.evidence_level]
    if claim.claim_type is ClaimType.ASSOCIATION and level < _RANK[EvidenceLevel.E2]:
        raise ValueError("association claim requires evidence level >= E2")
    if claim.claim_type is ClaimType.TRANSMISSION:
        if level < _RANK[EvidenceLevel.E3]:
            raise ValueError("transmission claim requires evidence level >= E3")
        if not (claim.evidence.get("temporal") and claim.evidence.get("epidemiological")):
            raise ValueError(
                "transmission claim requires temporal and epidemiological evidence"
            )
    if claim.claim_type is ClaimType.CAUSAL:
        if level < _RANK[EvidenceLevel.E3]:
            raise ValueError("causal claim requires evidence level >= E3")
        design = str(claim.evidence.get("design", "")).casefold()
        if design not in {"experimental", "interventional", "natural_experiment"}:
            raise ValueError("causal claim requires an experimental/interventional design")
    if claim.claim_type is ClaimType.MECHANISM:
        if level < _RANK[EvidenceLevel.E4]:
            raise ValueError("mechanism claim requires evidence level E4")
        if not claim.evidence.get("functional"):
            raise ValueError("mechanism claim requires functional evidence")


def _validate_wording(claim: Claim) -> None:
    text = claim.wording.casefold()
    if claim.claim_type in {ClaimType.OBSERVATION, ClaimType.ASSOCIATION}:
        if any(w in text for w in _CAUSAL_WORDS):
            raise ValueError("association wording uses causal language")
        if any(w in text for w in _MECHANISM_WORDS):
            raise ValueError("association wording uses mechanism language")
    if claim.claim_type is ClaimType.OBSERVATION and any(w in text for w in _TRANSMISSION_WORDS):
        raise ValueError("observation wording uses transmission language")
