"""research.sqlite 的迁移与持久化。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bacmap.research.models import (
    AnalysisPlan,
    AnalysisSession,
    Artifact,
    ArtifactKind,
    Claim,
    ClaimStatus,
    ClaimType,
    Cohort,
    CohortMember,
    CohortStatus,
    EvidenceEdge,
    EvidenceLevel,
    Experiment,
    ExperimentStatus,
    FigureDraft,
    FigureDraftStatus,
    PlanStatus,
    ResearchProfile,
    ResearchRequest,
    ResearchRequestStatus,
    SessionStatus,
    StatResult,
    Study,
    StudyStatus,
    SubmissionPackageRecord,
)
from bacmap.store.migrations import Migration, migrate

SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS analysis_sessions (
    session_id   TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    gene         TEXT NOT NULL,
    test_name    TEXT NOT NULL,
    profile      TEXT NOT NULL,
    status       TEXT NOT NULL,
    data_class   INTEGER NOT NULL,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
)
"""

STATS_DDL = """
CREATE TABLE IF NOT EXISTS stat_results (
    session_id     TEXT PRIMARY KEY,
    table_json     TEXT NOT NULL,
    odds_ratio     REAL,
    ci_low         REAL,
    ci_high        REAL,
    p_value        REAL,
    n              INTEGER NOT NULL,
    diagnostics_json TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL
)
"""

ARTIFACTS_DDL = """
CREATE TABLE IF NOT EXISTS research_artifacts (
    session_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    path       TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, kind)
)
"""

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS research_ledger (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,
    event        TEXT NOT NULL,
    actor        TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    at           TEXT NOT NULL
)
"""

STUDIES_DDL = """
CREATE TABLE IF NOT EXISTS studies (
    study_id       TEXT PRIMARY KEY,
    question       TEXT NOT NULL,
    pathogen_scope TEXT NOT NULL DEFAULT '',
    data_class     INTEGER NOT NULL DEFAULT 2,
    status         TEXT NOT NULL,
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

COHORTS_DDL = """
CREATE TABLE IF NOT EXISTS cohorts (
    cohort_id     TEXT PRIMARY KEY,
    study_id      TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    rules_json    TEXT NOT NULL DEFAULT '{}',
    members_json  TEXT NOT NULL DEFAULT '[]',
    snapshot_hash TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,
    created_by    TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""

PLANS2_DDL = """
CREATE TABLE IF NOT EXISTS analysis_plans (
    plan_id     TEXT PRIMARY KEY,
    study_id    TEXT NOT NULL,
    cohort_id   TEXT NOT NULL,
    spec_json   TEXT NOT NULL DEFAULT '{}',
    plan_hash   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    created_by  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id       TEXT PRIMARY KEY,
    study_id       TEXT NOT NULL,
    claim_type     TEXT NOT NULL,
    wording        TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    status         TEXT NOT NULL,
    evidence_json  TEXT NOT NULL DEFAULT '{}',
    reviewed_by    TEXT NOT NULL DEFAULT '',
    reviewed_at    TEXT NOT NULL DEFAULT '',
    message        TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

EDGES_DDL = """
CREATE TABLE IF NOT EXISTS evidence_edges (
    edge_id    TEXT PRIMARY KEY,
    src_type   TEXT NOT NULL,
    src_id     TEXT NOT NULL,
    edge_type  TEXT NOT NULL,
    dst_type   TEXT NOT NULL,
    dst_id     TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

PACKAGES_DDL = """
CREATE TABLE IF NOT EXISTS submission_packages (
    package_id      TEXT PRIMARY KEY,
    study_id        TEXT NOT NULL,
    path            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL DEFAULT '',
    label           TEXT NOT NULL DEFAULT '',
    manifest_sha256 TEXT NOT NULL DEFAULT '',
    n_files         INTEGER NOT NULL DEFAULT 0,
    blockers_json   TEXT NOT NULL DEFAULT '[]'
)
"""

DRAFTS_DDL = """
CREATE TABLE IF NOT EXISTS figure_drafts (
    draft_id   TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    path       TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    feedback   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT ''
)
"""

REQUESTS_DDL = """
CREATE TABLE IF NOT EXISTS research_requests (
    request_id     TEXT PRIMARY KEY,
    question       TEXT NOT NULL,
    pathogen_scope TEXT NOT NULL DEFAULT '',
    data_class     INTEGER NOT NULL DEFAULT 2,
    run_ids_json   TEXT NOT NULL DEFAULT '[]',
    gene           TEXT NOT NULL DEFAULT '',
    test_name      TEXT NOT NULL DEFAULT '',
    analysis       TEXT NOT NULL DEFAULT 'association',
    members_json   TEXT NOT NULL DEFAULT '[]',
    plan_spec_json TEXT NOT NULL DEFAULT '{}',
    note           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL,
    proposed_by    TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    reviewed_by    TEXT NOT NULL DEFAULT '',
    reviewed_at    TEXT NOT NULL DEFAULT '',
    review_note    TEXT NOT NULL DEFAULT '',
    study_id       TEXT NOT NULL DEFAULT '',
    cohort_id      TEXT NOT NULL DEFAULT '',
    plan_id        TEXT NOT NULL DEFAULT '',
    session_id     TEXT NOT NULL DEFAULT ''
)
"""

EXPERIMENTS_DDL = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    study_id      TEXT NOT NULL,
    plan_id       TEXT NOT NULL,
    plan_hash     TEXT NOT NULL,
    status        TEXT NOT NULL,
    run_ids_json  TEXT NOT NULL DEFAULT '[]',
    outcome_json  TEXT NOT NULL DEFAULT '{}',
    deviation     TEXT NOT NULL DEFAULT '',
    created_by    TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
)
"""

RESEARCH_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "research: sessions, stats, artifacts, ledger",
        (SESSIONS_DDL, STATS_DDL, ARTIFACTS_DDL, LEDGER_DDL),
    ),
    Migration(
        2,
        "research: studies, cohorts, plans, claims, evidence edges",
        (
            STUDIES_DDL,
            COHORTS_DDL,
            PLANS2_DDL,
            CLAIMS_DDL,
            EDGES_DDL,
            "ALTER TABLE analysis_sessions ADD COLUMN study_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE analysis_sessions ADD COLUMN cohort_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE research_ledger ADD COLUMN object_type TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE research_ledger ADD COLUMN object_id TEXT NOT NULL DEFAULT ''",
        ),
    ),
    Migration(
        3,
        "research: session links to plan",
        ("ALTER TABLE analysis_sessions ADD COLUMN plan_id TEXT NOT NULL DEFAULT ''",),
    ),
    Migration(
        4,
        "research: experiment ledger (success/failure/negative/deviation)",
        (EXPERIMENTS_DDL,),
    ),
    Migration(
        5,
        "research: agent-proposed research requests",
        (REQUESTS_DDL,),
    ),
    Migration(
        6,
        "research: figure drafts and feedback",
        (DRAFTS_DDL,),
    ),
    Migration(
        7,
        "research: submission package history",
        (PACKAGES_DDL,),
    ),
)


def research_db_path(home: Path | str) -> Path:
    return Path(home) / "research.sqlite"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ResearchStore:
    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.db = research_db_path(home)
        migrate(self.db, RESEARCH_MIGRATIONS)
        self._conn = sqlite3.connect(str(self.db), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ResearchStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def create_session(
        self,
        *,
        session_id: str,
        run_id: str,
        gene: str,
        test_name: str,
        profile: ResearchProfile,
        status: SessionStatus,
        data_class: int,
        created_by: str,
        label: str = "",
        study_id: str = "",
        cohort_id: str = "",
        plan_id: str = "",
        payload: dict | None = None,
    ) -> AnalysisSession:
        now = _now()
        self._conn.execute(
            "INSERT INTO analysis_sessions"
            " (session_id, run_id, gene, test_name, profile, status, data_class,"
            "  created_by, created_at, updated_at, label, payload_json,"
            "  study_id, cohort_id, plan_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                run_id,
                gene,
                test_name,
                profile.value,
                status.value,
                data_class,
                created_by,
                now,
                now,
                label,
                json.dumps(payload or {}, ensure_ascii=False),
                study_id,
                cohort_id,
                plan_id,
            ),
        )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> AnalysisSession:
        row = self._conn.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such research session: {session_id}")
        return _row_to_session(row)

    def list_sessions(self, limit: int = 50) -> list[AnalysisSession]:
        rows = self._conn.execute(
            "SELECT * FROM analysis_sessions ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [_row_to_session(r) for r in rows]

    def set_status(self, session_id: str, status: SessionStatus) -> None:
        self._conn.execute(
            "UPDATE analysis_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (status.value, _now(), session_id),
        )

    def put_stat(self, stat: StatResult) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO stat_results"
            " (session_id, table_json, odds_ratio, ci_low, ci_high, p_value, n,"
            "  diagnostics_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                stat.session_id,
                json.dumps(stat.table, ensure_ascii=False),
                stat.odds_ratio,
                stat.ci_low,
                stat.ci_high,
                stat.p_value,
                stat.n,
                json.dumps(stat.diagnostics, ensure_ascii=False),
                stat.created_at or _now(),
            ),
        )

    def get_stat(self, session_id: str) -> StatResult | None:
        row = self._conn.execute(
            "SELECT * FROM stat_results WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return StatResult(
            session_id=row["session_id"],
            table=json.loads(row["table_json"]),
            odds_ratio=row["odds_ratio"],
            ci_low=row["ci_low"],
            ci_high=row["ci_high"],
            p_value=row["p_value"],
            n=int(row["n"]),
            diagnostics=list(json.loads(row["diagnostics_json"])),
            created_at=row["created_at"],
        )

    def put_artifact(self, artifact: Artifact) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO research_artifacts"
            " (session_id, kind, path, sha256, created_at) VALUES (?,?,?,?,?)",
            (
                artifact.session_id,
                artifact.kind.value,
                artifact.path,
                artifact.sha256,
                artifact.created_at or _now(),
            ),
        )

    def list_artifacts(self, session_id: str) -> list[Artifact]:
        rows = self._conn.execute(
            "SELECT * FROM research_artifacts WHERE session_id = ? ORDER BY kind",
            (session_id,),
        ).fetchall()
        return [
            Artifact(
                session_id=r["session_id"],
                kind=ArtifactKind(r["kind"]),
                path=r["path"],
                sha256=r["sha256"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def ledger(
        self,
        session_id: str | None,
        event: str,
        actor: str,
        payload: dict | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO research_ledger (session_id, event, actor, payload_json, at)"
            " VALUES (?,?,?,?,?)",
            (session_id, event, actor, json.dumps(payload or {}, ensure_ascii=False), _now()),
        )

    def list_ledger(self, session_id: str, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM research_ledger WHERE session_id = ? ORDER BY seq LIMIT ?",
            (session_id, max(1, min(limit, 500))),
        ).fetchall()
        return [dict(r) for r in rows]


    def create_draft(self, draft: FigureDraft) -> FigureDraft:
        self._conn.execute(
            "INSERT INTO figure_drafts"
            " (draft_id, session_id, path, sha256, note, feedback, status,"
            "  created_by, created_at, reviewed_by, reviewed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                draft.draft_id,
                draft.session_id,
                draft.path,
                draft.sha256,
                draft.note,
                draft.feedback,
                draft.status.value,
                draft.created_by,
                draft.created_at or _now(),
                draft.reviewed_by,
                draft.reviewed_at,
            ),
        )
        self.ledger(
            draft.session_id,
            "figure.draft.created",
            draft.created_by,
            {"draft_id": draft.draft_id, "sha256": draft.sha256},
        )
        return self.get_draft(draft.draft_id)

    def get_draft(self, draft_id: str) -> FigureDraft:
        row = self._conn.execute(
            "SELECT * FROM figure_drafts WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such figure draft: {draft_id}")
        return _row_to_draft(row)

    def list_drafts(self, session_id: str, limit: int = 100) -> list[FigureDraft]:
        rows = self._conn.execute(
            "SELECT * FROM figure_drafts WHERE session_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (session_id, max(1, min(limit, 500))),
        ).fetchall()
        return [_row_to_draft(row) for row in rows]

    def update_draft(
        self,
        draft_id: str,
        *,
        feedback: str | None = None,
        status: FigureDraftStatus | None = None,
        actor: str = "",
    ) -> FigureDraft:
        draft = self.get_draft(draft_id)
        new_feedback = draft.feedback if feedback is None else feedback
        new_status = draft.status if status is None else status
        reviewed_at = _now() if status is not None else draft.reviewed_at
        self._conn.execute(
            "UPDATE figure_drafts SET feedback=?, status=?, reviewed_by=?,"
            " reviewed_at=? WHERE draft_id=?",
            (new_feedback, new_status.value, actor or draft.reviewed_by, reviewed_at, draft_id),
        )
        self.ledger(
            draft.session_id,
            "figure.draft.feedback"
            if feedback is not None
            else f"figure.draft.{new_status.value}",
            actor,
            {"draft_id": draft_id, "status": new_status.value},
        )
        return self.get_draft(draft_id)

def _row_to_session(row: sqlite3.Row) -> AnalysisSession:
    return AnalysisSession(
        session_id=row["session_id"],
        run_id=row["run_id"],
        gene=row["gene"],
        test_name=row["test_name"],
        profile=ResearchProfile(row["profile"]),
        status=SessionStatus(row["status"]),
        data_class=int(row["data_class"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        label=row["label"],
        study_id=row["study_id"],
        cohort_id=row["cohort_id"],
        plan_id=row["plan_id"],
        payload=json.loads(row["payload_json"]),
    )


def _hash(payload: object) -> str:
    import hashlib

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


class ResearchObjectStore:
    """P2 研究语义对象的持久化（P1 的 ResearchStore 保持兼容）。"""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.db = research_db_path(home)
        migrate(self.db, RESEARCH_MIGRATIONS)
        self._conn = sqlite3.connect(str(self.db), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ResearchObjectStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def create_study(
        self, question: str, pathogen_scope: str, data_class: int, actor: str
    ) -> Study:
        import uuid

        sid = f"study-{uuid.uuid4().hex[:12]}"
        now = _now()
        self._conn.execute(
            "INSERT INTO studies (study_id, question, pathogen_scope, data_class, status,"
            " created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                sid,
                question,
                pathogen_scope,
                int(data_class),
                StudyStatus.DRAFT.value,
                actor,
                now,
                now,
            ),
        )
        return self.get_study(sid)

    def list_studies(self, limit: int = 50) -> list[Study]:
        rows = self._conn.execute(
            "SELECT * FROM studies ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [_row_to_study(r) for r in rows]

    def get_study(self, study_id: str) -> Study:
        row = self._conn.execute("SELECT * FROM studies WHERE study_id = ?", (study_id,)).fetchone()
        if row is None:
            raise KeyError(f"no such study: {study_id}")
        return _row_to_study(row)

    def create_cohort(
        self,
        study_id: str,
        name: str,
        rules: dict,
        members: list[dict],
        actor: str,
    ) -> Cohort:
        import uuid

        self.get_study(study_id)
        cid = f"cohort-{uuid.uuid4().hex[:12]}"
        parsed = [CohortMember(**m) for m in members]
        now = _now()
        self._conn.execute(
            "INSERT INTO cohorts (cohort_id, study_id, name, rules_json, members_json,"
            " snapshot_hash, status, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                study_id,
                name,
                json.dumps(rules, ensure_ascii=False),
                json.dumps([m.model_dump(mode="json") for m in parsed], ensure_ascii=False),
                "",
                CohortStatus.DRAFT.value,
                actor,
                now,
                now,
            ),
        )
        return self.get_cohort(cid)

    def get_cohort(self, cohort_id: str) -> Cohort:
        row = self._conn.execute(
            "SELECT * FROM cohorts WHERE cohort_id = ?", (cohort_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such cohort: {cohort_id}")
        return _row_to_cohort(row)

    def list_cohorts(self, study_id: str | None = None, limit: int = 100) -> list[Cohort]:
        if study_id:
            rows = self._conn.execute(
                "SELECT * FROM cohorts WHERE study_id = ? ORDER BY created_at DESC LIMIT ?",
                (study_id, max(1, min(limit, 200))),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM cohorts ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_row_to_cohort(r) for r in rows]

    def freeze_cohort(self, cohort_id: str, actor: str) -> Cohort:
        c = self.get_cohort(cohort_id)
        if c.status is CohortStatus.FROZEN:
            raise ValueError(f"cohort {cohort_id} is already frozen")
        members = sorted(
            (m.model_dump(mode="json") for m in c.members),
            key=lambda m: (m["isolate_id"], m["dataset_id"], m["run_id"]),
        )
        snapshot = _hash({"study_id": c.study_id, "rules": c.rules, "members": members})
        now = _now()
        self._conn.execute(
            "UPDATE cohorts SET status = ?, snapshot_hash = ?, updated_at = ? WHERE cohort_id = ?",
            (CohortStatus.FROZEN.value, snapshot, now, cohort_id),
        )
        self._ledger("cohort", cohort_id, "cohort.frozen", actor, {"snapshot_hash": snapshot})
        return self.get_cohort(cohort_id)

    def create_plan(self, study_id: str, cohort_id: str, spec: dict, actor: str) -> AnalysisPlan:
        import uuid

        self.get_study(study_id)
        cohort = self.get_cohort(cohort_id)
        if cohort.status is not CohortStatus.FROZEN:
            raise ValueError("cohort must be frozen before creating an analysis plan")
        pid = f"plan-{uuid.uuid4().hex[:12]}"
        ph = _hash(
            {
                "study_id": study_id,
                "cohort_id": cohort_id,
                "cohort": cohort.snapshot_hash,
                "spec": spec,
            }
        )
        now = _now()
        self._conn.execute(
            "INSERT INTO analysis_plans (plan_id, study_id, cohort_id, spec_json, plan_hash,"
            " status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, study_id, cohort_id, json.dumps(spec, ensure_ascii=False), ph,
             PlanStatus.DRAFT.value, actor, now, now),
        )
        return self.get_plan(pid)

    def get_plan(self, plan_id: str) -> AnalysisPlan:
        row = self._conn.execute(
            "SELECT * FROM analysis_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such analysis plan: {plan_id}")
        return _row_to_plan(row)

    def list_plans(self, study_id: str | None = None, limit: int = 100) -> list[AnalysisPlan]:
        if study_id:
            rows = self._conn.execute(
                "SELECT * FROM analysis_plans WHERE study_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (study_id, max(1, min(limit, 200))),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM analysis_plans ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_row_to_plan(r) for r in rows]

    def freeze_plan(self, plan_id: str, actor: str) -> AnalysisPlan:
        p = self.get_plan(plan_id)
        if p.status is PlanStatus.FROZEN:
            raise ValueError(f"plan {plan_id} is already frozen")
        now = _now()
        self._conn.execute(
            "UPDATE analysis_plans SET status = ?, updated_at = ? WHERE plan_id = ?",
            (PlanStatus.FROZEN.value, now, plan_id),
        )
        self._ledger("plan", plan_id, "plan.frozen", actor, {"plan_hash": p.plan_hash})
        return self.get_plan(plan_id)

    def create_claim(
        self,
        study_id: str,
        claim_type: ClaimType,
        wording: str,
        evidence_level: EvidenceLevel,
        evidence: dict,
        actor: str,
    ) -> Claim:
        import uuid

        self.get_study(study_id)
        cid = f"claim-{uuid.uuid4().hex[:12]}"
        now = _now()
        self._conn.execute(
            "INSERT INTO claims (claim_id, study_id, claim_type, wording, evidence_level,"
            " status, evidence_json, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                cid, study_id, claim_type.value, wording, evidence_level.value,
                ClaimStatus.PROPOSED.value, json.dumps(evidence, ensure_ascii=False),
                actor, now, now,
            ),
        )
        return self.get_claim(cid)

    def get_claim(self, claim_id: str) -> Claim:
        row = self._conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        if row is None:
            raise KeyError(f"no such claim: {claim_id}")
        return _row_to_claim(row)

    def list_claims(self, study_id: str | None = None, limit: int = 100) -> list[Claim]:
        if study_id:
            rows = self._conn.execute(
                "SELECT * FROM claims WHERE study_id = ? ORDER BY created_at DESC LIMIT ?",
                (study_id, max(1, min(limit, 200))),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM claims ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_row_to_claim(r) for r in rows]

    def review_claim(self, claim_id: str, decision: str, message: str, actor: str) -> Claim:
        mapping = {
            "support": ClaimStatus.SUPPORTED,
            "challenge": ClaimStatus.CHALLENGED,
            "reject": ClaimStatus.REJECTED,
            "approve": ClaimStatus.APPROVED_FOR_EXPORT,
        }
        if decision not in mapping:
            raise ValueError(f"unknown claim decision: {decision}")
        self.get_claim(claim_id)
        now = _now()
        self._conn.execute(
            "UPDATE claims SET status = ?, reviewed_by = ?, reviewed_at = ?, message = ?,"
            " updated_at = ? WHERE claim_id = ?",
            (mapping[decision].value, actor, now, message, now, claim_id),
        )
        self._ledger("claim", claim_id, f"claim.{decision}", actor, {"message": message})
        return self.get_claim(claim_id)

    def create_experiment(
        self,
        study_id: str,
        plan_id: str,
        plan_hash: str,
        status: ExperimentStatus,
        run_ids: list[str],
        outcome: dict,
        deviation: str,
        actor: str,
    ) -> Experiment:
        import uuid

        eid = f"exp-{uuid.uuid4().hex[:12]}"
        now = _now()
        self._conn.execute(
            "INSERT INTO experiments (experiment_id, study_id, plan_id, plan_hash, status,"
            " run_ids_json, outcome_json, deviation, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                eid, study_id, plan_id, plan_hash, status.value,
                json.dumps(run_ids, ensure_ascii=False),
                json.dumps(outcome, ensure_ascii=False), deviation, actor, now,
            ),
        )
        return self.get_experiment(eid)

    def get_experiment(self, experiment_id: str) -> Experiment:
        row = self._conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such experiment: {experiment_id}")
        return _row_to_experiment(row)

    def list_experiments(
        self, study_id: str | None = None, plan_id: str | None = None, limit: int = 100
    ) -> list[Experiment]:
        clauses: list[str] = []
        args: list[object] = []
        if study_id:
            clauses.append("study_id = ?")
            args.append(study_id)
        if plan_id:
            clauses.append("plan_id = ?")
            args.append(plan_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(max(1, min(limit, 200)))
        rows = self._conn.execute(
            f"SELECT * FROM experiments{where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
            args,
        ).fetchall()
        return [_row_to_experiment(r) for r in rows]

    def list_sessions_by_study(self, study_id: str, limit: int = 200) -> list[AnalysisSession]:
        rows = self._conn.execute(
            "SELECT * FROM analysis_sessions WHERE study_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (study_id, max(1, min(limit, 500))),
        ).fetchall()
        return [_row_to_session(r) for r in rows]

    def add_edge(
        self, src_type: str, src_id: str, edge_type: str, dst_type: str, dst_id: str,
        reason: str, actor: str,
    ) -> EvidenceEdge:
        import uuid

        eid = f"edge-{uuid.uuid4().hex[:12]}"
        now = _now()
        self._conn.execute(
            "INSERT INTO evidence_edges (edge_id, src_type, src_id, edge_type, dst_type, dst_id,"
            " reason, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, src_type, src_id, edge_type, dst_type, dst_id, reason, actor, now),
        )
        return EvidenceEdge(
            edge_id=eid, src_type=src_type, src_id=src_id, edge_type=edge_type,
            dst_type=dst_type, dst_id=dst_id, reason=reason, created_by=actor, created_at=now,
        )

    def list_ledger(
        self, object_type: str | None = None, object_id: str | None = None, limit: int = 200
    ) -> list[dict]:
        clauses: list[str] = []
        args: list[object] = []
        if object_type:
            clauses.append("object_type = ?")
            args.append(object_type)
        if object_id:
            clauses.append("object_id = ?")
            args.append(object_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(max(1, min(limit, 500)))
        rows = self._conn.execute(
            f"SELECT * FROM research_ledger{where} ORDER BY seq DESC LIMIT ?",  # noqa: S608
            args,
        ).fetchall()
        return [dict(r) for r in rows]

    def list_edges(self, src_type: str, src_id: str) -> list[EvidenceEdge]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_edges WHERE src_type = ? AND src_id = ? ORDER BY created_at",
            (src_type, src_id),
        ).fetchall()
        return [
            EvidenceEdge(
                edge_id=r["edge_id"], src_type=r["src_type"], src_id=r["src_id"],
                edge_type=r["edge_type"], dst_type=r["dst_type"], dst_id=r["dst_id"],
                reason=r["reason"], created_by=r["created_by"], created_at=r["created_at"],
            )
            for r in rows
        ]

    def create_request(self, request: ResearchRequest) -> ResearchRequest:
        self._conn.execute(
            "INSERT INTO research_requests"
            " (request_id, question, pathogen_scope, data_class, run_ids_json, gene,"
            "  test_name, analysis, members_json, plan_spec_json, note, status,"
            "  proposed_by, created_at, reviewed_by, reviewed_at, review_note,"
            "  study_id, cohort_id, plan_id, session_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                request.request_id,
                request.question,
                request.pathogen_scope,
                request.data_class,
                json.dumps(request.run_ids, ensure_ascii=False),
                request.gene,
                request.test_name,
                request.analysis,
                json.dumps(request.members, ensure_ascii=False),
                json.dumps(request.plan_spec, ensure_ascii=False),
                request.note,
                request.status.value,
                request.proposed_by,
                request.created_at or _now(),
                request.reviewed_by,
                request.reviewed_at,
                request.review_note,
                request.study_id,
                request.cohort_id,
                request.plan_id,
                request.session_id,
            ),
        )
        self._ledger(
            "request",
            request.request_id,
            "request.proposed",
            request.proposed_by,
            {"question": request.question, "analysis": request.analysis},
        )
        return self.get_request(request.request_id)

    def get_request(self, request_id: str) -> ResearchRequest:
        row = self._conn.execute(
            "SELECT * FROM research_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such research request: {request_id}")
        return _row_to_request(row)

    def list_requests(
        self, status: str | None = None, limit: int = 100
    ) -> list[ResearchRequest]:
        sql = "SELECT * FROM research_requests"
        params: list[object] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_request(row) for row in rows]

    def review_request(
        self,
        request_id: str,
        *,
        status: ResearchRequestStatus,
        actor: str,
        note: str = "",
        study_id: str = "",
        cohort_id: str = "",
        plan_id: str = "",
        session_id: str = "",
    ) -> ResearchRequest:
        self._conn.execute(
            "UPDATE research_requests SET status=?, reviewed_by=?, reviewed_at=?,"
            " review_note=?, study_id=?, cohort_id=?, plan_id=?, session_id=?"
            " WHERE request_id=?",
            (
                status.value,
                actor,
                _now(),
                note,
                study_id,
                cohort_id,
                plan_id,
                session_id,
                request_id,
            ),
        )
        self._ledger(
            "request",
            request_id,
            f"request.{status.value}",
            actor,
            {
                "note": note,
                "study_id": study_id,
                "cohort_id": cohort_id,
                "plan_id": plan_id,
                "session_id": session_id,
            },
        )
        return self.get_request(request_id)

    def create_package(self, record: SubmissionPackageRecord) -> SubmissionPackageRecord:
        self._conn.execute(
            "INSERT INTO submission_packages"
            " (package_id, study_id, path, created_at, created_by, label,"
            "  manifest_sha256, n_files, blockers_json)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record.package_id,
                record.study_id,
                record.path,
                record.created_at,
                record.created_by,
                record.label,
                record.manifest_sha256,
                record.n_files,
                json.dumps(record.blockers, ensure_ascii=False),
            ),
        )
        self._ledger(
            "package",
            record.package_id,
            "package.created",
            record.created_by,
            {"study_id": record.study_id, "n_files": record.n_files},
        )
        return self.get_package(record.package_id)

    def get_package(self, package_id: str) -> SubmissionPackageRecord:
        row = self._conn.execute(
            "SELECT * FROM submission_packages WHERE package_id = ?", (package_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such submission package: {package_id}")
        return _row_to_package(row)

    def list_packages(
        self, study_id: str, limit: int = 50
    ) -> list[SubmissionPackageRecord]:
        rows = self._conn.execute(
            "SELECT * FROM submission_packages WHERE study_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (study_id, max(1, min(limit, 200))),
        ).fetchall()
        return [_row_to_package(row) for row in rows]

    def _ledger(
        self,
        object_type: str,
        object_id: str,
        event: str,
        actor: str,
        payload: dict,
    ) -> None:
        self._conn.execute(
            "INSERT INTO research_ledger (session_id, event, actor, payload_json, at,"
            " object_type, object_id) VALUES (?,?,?,?,?,?,?)",
            (
                None,
                event,
                actor,
                json.dumps(payload, ensure_ascii=False),
                _now(),
                object_type,
                object_id,
            ),
        )


def _row_to_study(row: sqlite3.Row) -> Study:
    return Study(
        study_id=row["study_id"], question=row["question"],
        pathogen_scope=row["pathogen_scope"], data_class=int(row["data_class"]),
        status=StudyStatus(row["status"]), created_by=row["created_by"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_cohort(row: sqlite3.Row) -> Cohort:
    return Cohort(
        cohort_id=row["cohort_id"], study_id=row["study_id"], name=row["name"],
        rules=json.loads(row["rules_json"]),
        members=[CohortMember(**m) for m in json.loads(row["members_json"])],
        snapshot_hash=row["snapshot_hash"], status=CohortStatus(row["status"]),
        created_by=row["created_by"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_plan(row: sqlite3.Row) -> AnalysisPlan:
    return AnalysisPlan(
        plan_id=row["plan_id"], study_id=row["study_id"], cohort_id=row["cohort_id"],
        spec=json.loads(row["spec_json"]), plan_hash=row["plan_hash"],
        status=PlanStatus(row["status"]), created_by=row["created_by"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        claim_id=row["claim_id"], study_id=row["study_id"],
        claim_type=ClaimType(row["claim_type"]), wording=row["wording"],
        evidence_level=EvidenceLevel(row["evidence_level"]), status=ClaimStatus(row["status"]),
        evidence=json.loads(row["evidence_json"]), reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"], message=row["message"],
        created_by=row["created_by"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_experiment(row: sqlite3.Row) -> Experiment:
    return Experiment(
        experiment_id=row["experiment_id"], study_id=row["study_id"],
        plan_id=row["plan_id"], plan_hash=row["plan_hash"],
        status=ExperimentStatus(row["status"]),
        run_ids=list(json.loads(row["run_ids_json"])),
        outcome=json.loads(row["outcome_json"]), deviation=row["deviation"],
        created_by=row["created_by"], created_at=row["created_at"],
    )


def _row_to_request(row: sqlite3.Row) -> ResearchRequest:
    return ResearchRequest(
        request_id=row["request_id"],
        question=row["question"],
        pathogen_scope=row["pathogen_scope"],
        data_class=int(row["data_class"]),
        run_ids=list(json.loads(row["run_ids_json"])),
        gene=row["gene"],
        test_name=row["test_name"],
        analysis=row["analysis"],
        members=list(json.loads(row["members_json"])),
        plan_spec=dict(json.loads(row["plan_spec_json"])),
        note=row["note"],
        status=ResearchRequestStatus(row["status"]),
        proposed_by=row["proposed_by"],
        created_at=row["created_at"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        review_note=row["review_note"],
        study_id=row["study_id"],
        cohort_id=row["cohort_id"],
        plan_id=row["plan_id"],
        session_id=row["session_id"],
    )


def _row_to_draft(row: sqlite3.Row) -> FigureDraft:
    return FigureDraft(
        draft_id=row["draft_id"],
        session_id=row["session_id"],
        path=row["path"],
        sha256=row["sha256"],
        note=row["note"],
        feedback=row["feedback"],
        status=FigureDraftStatus(row["status"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
    )


def _row_to_package(row: sqlite3.Row) -> SubmissionPackageRecord:
    return SubmissionPackageRecord(
        package_id=row["package_id"],
        study_id=row["study_id"],
        path=row["path"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        label=row["label"],
        manifest_sha256=row["manifest_sha256"],
        n_files=int(row["n_files"]),
        blockers=list(json.loads(row["blockers_json"])),
    )
