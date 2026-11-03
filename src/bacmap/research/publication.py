"""P2 发表门 G0–G3 的最小确定性检查。

不是自动发表：只判断研究是否具备进入人工发表评审的最低条件。任何 gate 失败都返回
可操作的 blockers，而不是模糊的“未就绪”。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bacmap.research.claims import validate_claim
from bacmap.research.models import (
    AnalysisPlan,
    AnalysisSession,
    Claim,
    ClaimStatus,
    Cohort,
    CohortStatus,
    Experiment,
    PlanStatus,
    Study,
)
from bacmap.research.store import ResearchObjectStore


def _gate(gate_id: str, title: str, blockers: list[str]) -> dict:
    return {"id": gate_id, "title": title, "ok": not blockers, "blockers": blockers}


def _gate_g0(cohorts: list[Cohort], plans: list[AnalysisPlan]) -> dict:
    blockers: list[str] = []
    frozen_cohorts = [c for c in cohorts if c.status is CohortStatus.FROZEN]
    frozen_plans = [p for p in plans if p.status is PlanStatus.FROZEN]
    if not frozen_cohorts:
        blockers.append("no frozen cohort")
    if not frozen_plans:
        blockers.append("no frozen analysis plan")
    for plan in frozen_plans:
        if len(plan.plan_hash) != 64:
            blockers.append(f"plan {plan.plan_id} has no valid hash")
        if not any(c.cohort_id == plan.cohort_id for c in frozen_cohorts):
            blockers.append(f"plan {plan.plan_id} references a non-frozen cohort")
    return _gate("G0", "frozen provenance", blockers)


def _gate_g1(claims: list[Claim]) -> dict:
    blockers: list[str] = []
    usable = [
        c for c in claims
        if c.status in {ClaimStatus.SUPPORTED, ClaimStatus.APPROVED_FOR_EXPORT}
    ]
    if not usable:
        blockers.append("no supported/approved claim")
    unresolved = [c.claim_id for c in claims if c.status is ClaimStatus.CHALLENGED]
    if unresolved:
        blockers.append(f"challenged claims unresolved: {', '.join(unresolved)}")
    for claim in claims:
        if claim.status is ClaimStatus.APPROVED_FOR_EXPORT:
            try:
                validate_claim(claim, "approve")
            except ValueError as exc:
                blockers.append(f"claim {claim.claim_id}: {exc}")
    return _gate("G1", "claim level and wording", blockers)


def _gate_g2(study: Study, sessions: list[AnalysisSession]) -> dict:
    blockers: list[str] = []
    if study.data_class > 2:
        blockers.append(f"study data_class=D{study.data_class} exceeds D2")
    for session in sessions:
        if session.data_class > 2:
            blockers.append(f"session {session.session_id} data_class=D{session.data_class}")
    return _gate("G2", "data boundary D0–D2", blockers)


def _gate_g3(plans: list[AnalysisPlan], experiments: list[Experiment]) -> dict:
    blockers: list[str] = []
    frozen_plans = [p for p in plans if p.status is PlanStatus.FROZEN]
    executed = [e for e in experiments if e.status.value in {"success", "negative"}]
    if not executed:
        blockers.append("no successful/negative experiment recorded")
    hashes = {p.plan_id: p.plan_hash for p in frozen_plans}
    for experiment in experiments:
        expected = hashes.get(experiment.plan_id)
        if expected is None:
            blockers.append(f"experiment {experiment.experiment_id} uses a non-frozen plan")
        elif experiment.plan_hash != expected:
            blockers.append(f"experiment {experiment.experiment_id} plan hash does not match")
        if experiment.status.value in {"success", "negative"} and not experiment.run_ids:
            blockers.append(f"experiment {experiment.experiment_id} has no run_ids")
    return _gate("G3", "reproducible execution", blockers)


def publication_readiness(home: Path | str, study_id: str) -> dict[str, Any]:
    with ResearchObjectStore(home) as store:
        study = store.get_study(study_id)
        cohorts = store.list_cohorts(study_id)
        plans = store.list_plans(study_id)
        claims = store.list_claims(study_id)
        experiments = store.list_experiments(study_id)
        sessions = store.list_sessions_by_study(study_id)
    gates = [
        _gate_g0(cohorts, plans),
        _gate_g1(claims),
        _gate_g2(study, sessions),
        _gate_g3(plans, experiments),
    ]
    return {
        "study_id": study_id,
        "ready": all(g["ok"] for g in gates),
        "gates": gates,
        "note": (
            "Gate pass is necessary, not sufficient: a human publication review "
            "is still required."
        ),
    }
