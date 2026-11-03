"""P3 自动探索的第一片：候选评分与预算/停止规则。

设计边界：
- 只接受 **screening** 数据；确认性数据不得用于生成候选（防泄漏）。
- 只提出候选，不创建 Claim、不改变证据等级、不自动执行。
- 评分不替代统计显著性；它只是排序与预算控制。
"""

from __future__ import annotations

import hashlib
import math
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from bacmap.research.stats import associate_counts, benjamini_hochberg


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    REJECTED = "rejected"


class ExploreBudget(BaseModel):
    max_tests: int = Field(default=200, ge=1, le=10000)
    max_candidates: int = Field(default=20, ge=1, le=1000)
    min_n: int = Field(default=20, ge=1)
    max_q: float = Field(default=0.05, gt=0, le=1)


class ExploreRequest(BaseModel):
    study_id: str = Field(min_length=1, max_length=128)
    cases: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    budget: ExploreBudget = Field(default_factory=ExploreBudget)
    role: str = "screening"


class Candidate(BaseModel):
    candidate_id: str
    study_id: str
    exposure: str
    outcome: str
    status: CandidateStatus = CandidateStatus.PROPOSED
    odds_ratio: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    q_value: float | None = None
    n: int = 0
    score: float = 0.0
    reason: str = ""


def _table(case: dict[str, Any]) -> tuple[int, int, int, int]:
    raw = case.get("table")
    if isinstance(raw, dict):
        return (
            int(raw.get("gene_pos_resistant", raw.get("a")) or 0),
            int(raw.get("gene_pos_susceptible", raw.get("b")) or 0),
            int(raw.get("gene_neg_resistant", raw.get("c")) or 0),
            int(raw.get("gene_neg_susceptible", raw.get("d")) or 0),
        )
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = tuple(int(x) for x in raw)
        return values[0], values[1], values[2], values[3]
    return (
        int(case.get("a") or 0),
        int(case.get("b") or 0),
        int(case.get("c") or 0),
        int(case.get("d") or 0),
    )


def _effect_weight(odds_ratio: float | None) -> float:
    if odds_ratio is None or odds_ratio <= 0:
        return 0.0
    return abs(math.log(odds_ratio))


def score_candidate(q_value: float | None, odds_ratio: float | None, n: int) -> float:
    """Rank by evidence strength × effect size, with a mild sample-size term."""
    if q_value is None or q_value <= 0 or q_value > 1:
        return 0.0
    return (-math.log10(q_value)) * _effect_weight(odds_ratio) * math.log1p(max(n, 0))


def explore_candidates(
    study_id: str,
    cases: list[dict[str, Any]],
    budget: ExploreBudget | None = None,
    role: str = "screening",
) -> dict:
    """Rank candidate exposure→outcome associations from screening data only."""
    if role != "screening":
        raise ValueError("only screening data may be used to propose candidates")
    budget = budget or ExploreBudget()
    tested: list[dict] = []
    for index, case in enumerate(cases):
        if index >= budget.max_tests:
            break
        exposure = str(case.get("exposure", "")).strip()
        outcome = str(case.get("outcome", "")).strip()
        if not exposure or not outcome:
            continue
        stat = associate_counts(*_table(case))
        tested.append(
            {
                "exposure": exposure,
                "outcome": outcome,
                "stat": stat,
                "source": str(case.get("source", "")),
            }
        )
    q_values = benjamini_hochberg([t["stat"].p_value for t in tested])
    candidates: list[Candidate] = []
    for item, q_value in zip(tested, q_values, strict=True):
        stat = item["stat"]
        if stat.n < budget.min_n:
            continue
        if q_value is None or q_value > budget.max_q:
            continue
        digest = hashlib.sha256(
            f"{study_id}|{item['exposure']}|{item['outcome']}|{stat.table}".encode()
        ).hexdigest()[:12]
        candidates.append(
            Candidate(
                candidate_id=f"cand-{digest}",
                study_id=study_id,
                exposure=item["exposure"],
                outcome=item["outcome"],
                odds_ratio=stat.odds_ratio,
                ci_low=stat.ci_low,
                ci_high=stat.ci_high,
                p_value=stat.p_value,
                q_value=q_value,
                n=stat.n,
                score=score_candidate(q_value, stat.odds_ratio, stat.n),
                reason="screening association; needs independent confirmation",
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.candidate_id))
    stopped = "max_candidates" if len(candidates) > budget.max_candidates else "exhausted"
    candidates = candidates[: budget.max_candidates]
    return {
        "study_id": study_id,
        "role": role,
        "n_cases": len(cases),
        "n_tested": len(tested),
        "n_candidates": len(candidates),
        "stopped_reason": stopped,
        "budget": budget.model_dump(mode="json"),
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "guard": (
            "Candidates are proposals only. They must be confirmed on independent data; "
            "this function does not create Claims or change evidence levels."
        ),
    }
