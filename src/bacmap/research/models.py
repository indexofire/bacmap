"""研究对象的 Pydantic 模型（P1 薄链路）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResearchProfile(StrEnum):
    """治理 Profile；与 MCP 的 cloud/local-trusted 数据 Profile 正交。"""

    OPEN_TEST = "open-test"
    RESEARCH = "research"
    PUBLICATION = "publication"


class SessionStatus(StrEnum):
    COMPLETE_TEST = "complete_test"  # open-test: TEST/UNVERIFIED
    REVIEW_REQUIRED = "review_required"  # research/publication: 待人工复核
    REVIEWED = "reviewed"


class ArtifactKind(StrEnum):
    FIGURE = "figure"
    REPORT = "report"
    MANUSCRIPT = "manuscript"
    FIGURE_SPEC = "figure_spec"
    FIGURE_CUSTOM = "figure_custom"
    FIGURE_MANIFEST = "figure_manifest"


class AnalysisSession(BaseModel):
    session_id: str
    run_id: str
    gene: str
    test_name: str
    profile: ResearchProfile
    status: SessionStatus
    data_class: int
    created_by: str
    created_at: str
    updated_at: str
    label: str = ""
    study_id: str = ""
    cohort_id: str = ""
    plan_id: str = ""
    note: str = Field(default="", max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)


class StatResult(BaseModel):
    session_id: str
    table: dict[str, int]
    odds_ratio: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    n: int = 0
    diagnostics: list[str] = Field(default_factory=list)
    created_at: str = ""


class Artifact(BaseModel):
    session_id: str
    kind: ArtifactKind
    path: str
    sha256: str
    created_at: str


class ResearchCapabilities(BaseModel):
    profile: ResearchProfile
    statuses: list[str]
    artifacts: list[str]
    description: str


class CreateSessionRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    gene: str = Field(min_length=1, max_length=128)
    test_name: str = Field(min_length=1, max_length=128)
    profile: ResearchProfile | None = None
    study_id: str = ""
    cohort_id: str = ""
    plan_id: str = ""
    note: str = Field(default="", max_length=2000)


class SessionView(BaseModel):
    session: AnalysisSession
    stat: StatResult | None = None
    artifacts: list[Artifact] = Field(default_factory=list)


class ResearchError(Exception):
    """Research 层错误（接口层映射为统一错误信封）。"""

    def __init__(self, code: Literal["validation_error", "not_found", "conflict"], message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class StudyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class CohortStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"


class ClaimType(StrEnum):
    OBSERVATION = "observation"
    ASSOCIATION = "association"
    TRANSMISSION = "transmission"
    CAUSAL = "causal"
    MECHANISM = "mechanism"


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CHALLENGED = "challenged"
    REJECTED = "rejected"
    APPROVED_FOR_EXPORT = "approved_for_export"


class ExperimentStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    NEGATIVE = "negative"
    DEVIATED = "deviated"


class EvidenceLevel(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"


class Study(BaseModel):
    study_id: str
    question: str
    pathogen_scope: str = ""
    data_class: int = 2
    status: StudyStatus = StudyStatus.DRAFT
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class CohortMember(BaseModel):
    isolate_id: str
    dataset_id: str = ""
    run_id: str = ""


class Cohort(BaseModel):
    cohort_id: str
    study_id: str
    name: str = ""
    rules: dict[str, Any] = Field(default_factory=dict)
    members: list[CohortMember] = Field(default_factory=list)
    snapshot_hash: str = ""
    status: CohortStatus = CohortStatus.DRAFT
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class AnalysisPlan(BaseModel):
    plan_id: str
    study_id: str
    cohort_id: str
    spec: dict[str, Any] = Field(default_factory=dict)
    plan_hash: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class Claim(BaseModel):
    claim_id: str
    study_id: str
    claim_type: ClaimType
    wording: str
    evidence_level: EvidenceLevel = EvidenceLevel.E0
    status: ClaimStatus = ClaimStatus.PROPOSED
    evidence: dict[str, Any] = Field(default_factory=dict)
    reviewed_by: str = ""
    reviewed_at: str = ""
    message: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class Experiment(BaseModel):
    experiment_id: str
    study_id: str
    plan_id: str
    plan_hash: str
    status: ExperimentStatus
    run_ids: list[str] = Field(default_factory=list)
    outcome: dict[str, Any] = Field(default_factory=dict)
    deviation: str = ""
    created_by: str = ""
    created_at: str = ""


class ExperimentCreate(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    status: ExperimentStatus
    run_ids: list[str] = Field(default_factory=list)
    outcome: dict[str, Any] = Field(default_factory=dict)
    deviation: str = Field(default="", max_length=2000)


class EvidenceEdge(BaseModel):
    edge_id: str
    src_type: str
    src_id: str
    edge_type: str
    dst_type: str
    dst_id: str
    reason: str = ""
    created_by: str = ""
    created_at: str = ""


class StudyCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    pathogen_scope: str = Field(default="", max_length=256)
    data_class: int = Field(default=2, ge=0, le=4)


class CohortCreate(BaseModel):
    study_id: str
    name: str = Field(default="", max_length=256)
    rules: dict[str, Any] = Field(default_factory=dict)
    members: list[CohortMember] = Field(default_factory=list)


class PlanCreate(BaseModel):
    study_id: str
    cohort_id: str
    spec: dict[str, Any] = Field(default_factory=dict)


class ClaimCreate(BaseModel):
    study_id: str
    claim_type: ClaimType
    wording: str = Field(min_length=1, max_length=2000)
    evidence_level: EvidenceLevel = EvidenceLevel.E0
    evidence: dict[str, Any] = Field(default_factory=dict)


class ClaimReview(BaseModel):
    decision: Literal["support", "challenge", "reject", "approve"]
    message: str = Field(default="", max_length=500)
