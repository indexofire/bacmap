"""Research Workbench P1 服务：session → stat → figure/report/manuscript。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bacmap.research.figures import (
    FigureArtifact,
    FigureSpec,
    Renderer,
    build_artifact,
    build_association_spec,
    load_spec,
    write_spec,
)
from bacmap.research.models import (
    AnalysisSession,
    Artifact,
    ArtifactKind,
    CreateSessionRequest,
    ResearchCapabilities,
    ResearchError,
    ResearchProfile,
    SessionStatus,
    SessionView,
)
from bacmap.research.render import (
    render_figure_svg,
    render_manuscript_markdown,
    render_report_markdown,
)
from bacmap.research.stats import analyze_amr_association
from bacmap.research.store import ResearchStore
from bacmap.tools.spec import DataClass


def default_profile() -> ResearchProfile:
    raw = (os.environ.get("BACMAP_RESEARCH_PROFILE") or "research").strip().lower()
    try:
        return ResearchProfile(raw)
    except ValueError:
        return ResearchProfile.RESEARCH


class ResearchService:
    """P1 薄链路服务；对象写入 research.sqlite，产物写入 research/<session_id>/。"""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def capabilities(self, profile: ResearchProfile | None = None) -> ResearchCapabilities:
        p = profile or default_profile()
        return ResearchCapabilities(
            profile=p,
            statuses=[s.value for s in SessionStatus],
            artifacts=[k.value for k in ArtifactKind],
            description=(
                "P1 Research Workbench: deterministic AMR association from an existing run. "
                "open-test marks output TEST/UNVERIFIED; research/publication require review."
            ),
        )

    def create_session(
        self,
        request: CreateSessionRequest,
        *,
        actor: str = "cli",
        profile: ResearchProfile | None = None,
    ) -> SessionView:
        p = profile or request.profile or default_profile()
        run_id = request.run_id.strip()
        gene = request.gene.strip()
        test_name = request.test_name.strip()
        if not run_id or not gene or not test_name:
            raise ResearchError("validation_error", "run_id, gene and test_name are required")

        stat = analyze_amr_association(self.home, run_id, gene, test_name)
        session_id = f"rs-{uuid4().hex[:12]}"
        stat.session_id = session_id
        stat.created_at = datetime.now(UTC).isoformat()

        status = (
            SessionStatus.COMPLETE_TEST
            if p is ResearchProfile.OPEN_TEST
            else SessionStatus.REVIEW_REQUIRED
        )
        label = "TEST/UNVERIFIED" if status is SessionStatus.COMPLETE_TEST else "REVIEW REQUIRED"
        outdir = self.home / "research" / session_id
        outdir.mkdir(parents=True, exist_ok=True)

        fig_path = outdir / "figure.svg"
        fig_path.write_text(render_figure_svg(
            AnalysisSession(
                session_id=session_id,
                run_id=run_id,
                gene=gene,
                test_name=test_name,
                profile=p,
                status=status,
                data_class=int(DataClass.D2),
                created_by=actor,
                created_at=stat.created_at,
                updated_at=stat.created_at,
                label=label,
                study_id=request.study_id,
                cohort_id=request.cohort_id,
                plan_id=request.plan_id,
            ),
            stat,
        ), encoding="utf-8")
        report_path = outdir / "report.md"
        manuscript_path = outdir / "manuscript.md"
        spec_path = outdir / "figure_spec.json"

        with ResearchStore(self.home) as store:
            session = store.create_session(
                session_id=session_id,
                run_id=run_id,
                gene=gene,
                test_name=test_name,
                profile=p,
                status=status,
                data_class=int(DataClass.D2),
                created_by=actor,
                label=label,
                study_id=request.study_id,
                cohort_id=request.cohort_id,
                plan_id=request.plan_id,
                payload={"p1": True},
            )
            report_path.write_text(render_report_markdown(session, stat), encoding="utf-8")
            manuscript_path.write_text(
                render_manuscript_markdown(session, stat), encoding="utf-8"
            )
            write_spec(build_association_spec(session, stat), spec_path)
            store.put_stat(stat)
            for kind, path in (
                (ArtifactKind.FIGURE, fig_path),
                (ArtifactKind.REPORT, report_path),
                (ArtifactKind.MANUSCRIPT, manuscript_path),
                (ArtifactKind.FIGURE_SPEC, spec_path),
            ):
                store.put_artifact(
                    Artifact(
                        session_id=session_id,
                        kind=kind,
                        path=str(path),
                        sha256=_sha256(path),
                        created_at=stat.created_at,
                    )
                )
            store.ledger(
                session_id,
                "session.created",
                actor,
                {
                    "run_id": run_id,
                    "gene": gene,
                    "test_name": test_name,
                    "profile": p.value,
                    "study_id": request.study_id,
                    "cohort_id": request.cohort_id,
                    "plan_id": request.plan_id,
                },
            )
            return SessionView(
                session=session,
                stat=stat,
                artifacts=store.list_artifacts(session_id),
            )

    def get_session(self, session_id: str) -> SessionView:
        with ResearchStore(self.home) as store:
            try:
                session = store.get_session(session_id)
            except KeyError as exc:
                raise ResearchError("not_found", f"no such research session: {session_id}") from exc
            return SessionView(
                session=session,
                stat=store.get_stat(session_id),
                artifacts=store.list_artifacts(session_id),
            )

    def list_sessions(self, limit: int = 50) -> list[AnalysisSession]:
        with ResearchStore(self.home) as store:
            return store.list_sessions(limit)

    def read_artifact(self, session_id: str, kind: str) -> Path:
        try:
            k = ArtifactKind(kind)
        except ValueError as exc:
            raise ResearchError("validation_error", f"unknown artifact kind: {kind}") from exc
        with ResearchStore(self.home) as store:
            try:
                session = store.get_session(session_id)
            except KeyError as exc:
                raise ResearchError("not_found", f"no such research session: {session_id}") from exc
            for art in store.list_artifacts(session_id):
                if art.kind is k:
                    path = Path(art.path)
                    if path.is_file() and path.is_relative_to(self.home / "research"):
                        return path
            raise ResearchError(
                "not_found", f"artifact {kind!r} not found for session {session.session_id}"
            )

    def figure_spec(self, session_id: str) -> FigureSpec:
        """Return the stored figure contract (or rebuild it for legacy sessions)."""
        with ResearchStore(self.home) as store:
            try:
                session = store.get_session(session_id)
            except KeyError as exc:
                raise ResearchError("not_found", f"no such research session: {session_id}") from exc
            stat = store.get_stat(session_id)
            for art in store.list_artifacts(session_id):
                if art.kind is ArtifactKind.FIGURE_SPEC:
                    path = Path(art.path)
                    if path.is_file():
                        return load_spec(path)
        if stat is None:
            raise ResearchError("not_found", f"session {session_id} has no statistics")
        return build_association_spec(session, stat)

    def attach_figure(
        self,
        session_id: str,
        output: str | Path,
        *,
        code: str | Path | None = None,
        spec_path: str | Path | None = None,
        renderer: Renderer = "agent-script",
        actor: str = "cli",
    ) -> FigureArtifact:
        """Register a rendered custom figure with spec/data/code/output hashes."""
        view = self.get_session(session_id)
        if view.stat is None:
            raise ResearchError("not_found", f"session {session_id} has no statistics")
        spec = (
            load_spec(spec_path)
            if spec_path is not None
            else build_association_spec(view.session, view.stat)
        )
        if spec.source.session_id != session_id:
            raise ResearchError(
                "validation_error",
                f"figure spec belongs to session {spec.source.session_id}, not {session_id}",
            )
        if renderer not in {"bacmap-deterministic", "agent-script"}:
            raise ResearchError("validation_error", f"unknown figure renderer: {renderer}")
        try:
            artifact = build_artifact(
                spec,
                output,
                renderer=renderer,
                code=code,
            )
        except ValueError as exc:
            raise ResearchError("validation_error", str(exc)) from exc
        outdir = self.home / "research" / session_id
        outdir.mkdir(parents=True, exist_ok=True)
        src = Path(artifact.output)
        dest = src if src.is_relative_to(outdir) else outdir / f"figure_custom{src.suffix.lower()}"
        if src != dest:
            shutil.copy2(src, dest)
        updates: dict[str, str] = {"output": str(dest)}
        if artifact.code_path:
            code_src = Path(artifact.code_path)
            code_dest = (
                code_src
                if code_src.is_relative_to(outdir)
                else outdir / f"figure_custom{code_src.suffix.lower()}"
            )
            if code_src != code_dest:
                shutil.copy2(code_src, code_dest)
            updates["code_path"] = str(code_dest)
        artifact = artifact.model_copy(update=updates)
        manifest_path = outdir / "figure_custom.manifest.json"
        manifest = json.dumps(
            artifact.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2
        )
        manifest_path.write_text(manifest + "\n", encoding="utf-8")
        with ResearchStore(self.home) as store:
            store.put_artifact(
                Artifact(
                    session_id=session_id,
                    kind=ArtifactKind.FIGURE_CUSTOM,
                    path=str(dest),
                    sha256=_sha256(dest),
                    created_at=artifact.created_at,
                )
            )
            store.put_artifact(
                Artifact(
                    session_id=session_id,
                    kind=ArtifactKind.FIGURE_MANIFEST,
                    path=str(manifest_path),
                    sha256=_sha256(manifest_path),
                    created_at=artifact.created_at,
                )
            )
            store.ledger(
                session_id,
                "figure.attached",
                actor,
                artifact.model_dump(mode="json", by_alias=True),
            )
        return artifact

    def ledger(self, session_id: str) -> list[dict]:
        with ResearchStore(self.home) as store:
            return store.list_ledger(session_id)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class ResearchObjectService:
    """P2 研究语义对象：Study/Cohort/AnalysisPlan/Claim/EvidenceEdge。"""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def create_study(
        self, question: str, pathogen_scope: str = "", data_class: int = 2,
        actor: str = "cli",
    ):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            study = store.create_study(question, pathogen_scope, data_class, actor)
            store._ledger("study", study.study_id, "study.created", actor, {})
            return study

    def list_studies(self, limit: int = 50):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            return store.list_studies(limit)

    def get_study(self, study_id: str):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            return store.get_study(study_id)

    def create_cohort(
        self, study_id: str, members: list[dict], rules: dict | None = None,
        name: str = "", actor: str = "cli",
    ):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            cohort = store.create_cohort(study_id, name, rules or {}, members, actor)
            store._ledger("cohort", cohort.cohort_id, "cohort.created", actor, {})
            return cohort

    def preview_cohort(
        self, study_id: str, members: list[dict], rules: dict | None = None
    ) -> dict:
        """Cohort 预检：重复成员、缺失 run、孤立数据集；不写库。"""
        from bacmap.research.models import CohortMember
        from bacmap.research.store import ResearchObjectStore
        from bacmap.store import runs

        with ResearchObjectStore(self.home) as store:
            store.get_study(study_id)
        parsed = [CohortMember(**m) for m in members]
        seen_iso: set[str] = set()
        seen_ds: set[str] = set()
        dup_iso: list[str] = []
        dup_ds: list[str] = []
        missing_runs: list[str] = []
        for m in parsed:
            if m.isolate_id in seen_iso:
                dup_iso.append(m.isolate_id)
            seen_iso.add(m.isolate_id)
            if m.dataset_id:
                if m.dataset_id in seen_ds:
                    dup_ds.append(m.dataset_id)
                seen_ds.add(m.dataset_id)
            if m.run_id and runs.read_run(m.run_id, self.home / "runs.sqlite") is None:
                missing_runs.append(m.run_id)
        return {
            "n_members": len(parsed),
            "n_isolates": len(seen_iso),
            "n_datasets": len(seen_ds),
            "duplicate_isolates": dup_iso,
            "duplicate_datasets": dup_ds,
            "missing_runs": missing_runs,
            "rules": rules or {},
            "ok": not (dup_iso or dup_ds or missing_runs),
        }

    def freeze_cohort(self, cohort_id: str, actor: str = "cli"):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            return store.freeze_cohort(cohort_id, actor)

    def create_plan(
        self, study_id: str, cohort_id: str, spec: dict, actor: str = "cli"
    ):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            plan = store.create_plan(study_id, cohort_id, spec, actor)
            store._ledger("plan", plan.plan_id, "plan.created", actor, {})
            return plan

    def freeze_plan(self, plan_id: str, actor: str = "cli"):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            return store.freeze_plan(plan_id, actor)

    def create_claim(
        self, study_id: str, claim_type: str, wording: str,
        evidence_level: str = "E0", evidence: dict | None = None, actor: str = "cli",
    ):
        from bacmap.research.models import ClaimType, EvidenceLevel
        from bacmap.research.store import ResearchObjectStore

        try:
            ct = ClaimType(claim_type)
            el = EvidenceLevel(evidence_level)
        except ValueError as exc:
            raise ResearchError("validation_error", str(exc)) from exc
        with ResearchObjectStore(self.home) as store:
            claim = store.create_claim(study_id, ct, wording, el, evidence or {}, actor)
            store._ledger("claim", claim.claim_id, "claim.created", actor, {})
            return claim

    def claim_from_session(
        self,
        session_id: str,
        wording: str,
        evidence_level: str = "E2",
        actor: str = "cli",
    ):
        """把一个 P1 AMR 会话转成 association Claim 草案（不自动 support）。"""
        from bacmap.research.models import EvidenceLevel

        view = ResearchService(self.home).get_session(session_id)
        if not view.session.study_id:
            raise ResearchError(
                "validation_error", "research session is not linked to a study"
            )
        if view.stat is None:
            raise ResearchError("validation_error", "session has no stat result")
        try:
            level = EvidenceLevel(evidence_level)
        except ValueError as exc:
            raise ResearchError("validation_error", str(exc)) from exc
        return self.create_claim(
            view.session.study_id,
            "association",
            wording,
            level.value,
            {
                "session_id": session_id,
                "run_id": view.session.run_id,
                "stat": view.stat.model_dump(mode="json"),
            },
            actor,
        )

    def review_claim(
        self, claim_id: str, decision: str, message: str = "", actor: str = "cli"
    ):
        from bacmap.research.claims import validate_claim
        from bacmap.research.store import ResearchObjectStore

        try:
            with ResearchObjectStore(self.home) as store:
                validate_claim(store.get_claim(claim_id), decision)
                return store.review_claim(claim_id, decision, message, actor)
        except KeyError as exc:
            raise ResearchError("not_found", str(exc)) from exc
        except ValueError as exc:
            raise ResearchError("conflict", str(exc)) from exc


    def record_experiment(
        self,
        plan_id: str,
        status: str,
        run_ids: list[str] | None = None,
        outcome: dict | None = None,
        deviation: str = "",
        actor: str = "cli",
    ):
        """记录一次实际执行：成功/失败/阴性/偏离，并绑定冻结计划哈希。"""
        from bacmap.research.models import ExperimentStatus
        from bacmap.research.store import ResearchObjectStore

        try:
            exp_status = ExperimentStatus(status)
        except ValueError as exc:
            raise ResearchError("validation_error", str(exc)) from exc
        if exp_status is ExperimentStatus.DEVIATED and not deviation.strip():
            raise ResearchError("validation_error", "deviated experiment requires a deviation note")
        with ResearchObjectStore(self.home) as store:
            try:
                plan = store.get_plan(plan_id)
            except KeyError as exc:
                raise ResearchError("not_found", str(exc)) from exc
            if plan.status.value != "frozen":
                raise ResearchError("conflict", f"plan {plan_id} is not frozen")
            experiment = store.create_experiment(
                plan.study_id,
                plan.plan_id,
                plan.plan_hash,
                exp_status,
                list(run_ids or []),
                outcome or {},
                deviation.strip(),
                actor,
            )
            store.add_edge(
                "experiment", experiment.experiment_id, "TESTS", "plan", plan.plan_id,
                f"experiment status={exp_status.value}", actor,
            )
            store._ledger(
                "experiment", experiment.experiment_id, f"experiment.{exp_status.value}",
                actor,
                {
                    "plan_id": plan.plan_id,
                    "plan_hash": plan.plan_hash,
                    "run_ids": experiment.run_ids,
                    "deviation": experiment.deviation,
                },
            )
            return experiment

    def list_experiments(
        self, study_id: str | None = None, plan_id: str | None = None, limit: int = 100
    ):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            return store.list_experiments(study_id, plan_id, limit)

    def publication_readiness(self, study_id: str) -> dict:
        from bacmap.research.publication import publication_readiness

        return publication_readiness(self.home, study_id)

    def run_plan(self, plan_id: str, actor: str = "cli", profile: ResearchProfile | None = None):
        """执行已冻结计划：P1 AMR recipe 绑定到 Study/Cohort/Plan。"""
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(self.home) as store:
            try:
                plan = store.get_plan(plan_id)
            except KeyError as exc:
                raise ResearchError("not_found", str(exc)) from exc
            if plan.status.value != "frozen":
                raise ResearchError("conflict", f"plan {plan_id} is not frozen")
            spec = plan.spec
            missing = [k for k in ("run_id", "gene", "test_name") if not spec.get(k)]
            if missing:
                raise ResearchError(
                    "validation_error",
                    f"P1 AMR recipe needs spec fields {missing}",
                )
            view = ResearchService(self.home).create_session(
                CreateSessionRequest(
                    run_id=str(spec["run_id"]),
                    gene=str(spec["gene"]),
                    test_name=str(spec["test_name"]),
                    study_id=plan.study_id,
                    cohort_id=plan.cohort_id,
                    plan_id=plan.plan_id,
                ),
                actor=actor,
                profile=profile or ResearchProfile.RESEARCH,
            )
            store.add_edge(
                "session", view.session.session_id, "USES_RUN", "run", view.session.run_id,
                "P1 AMR recipe", actor,
            )
            store.add_edge(
                "session", view.session.session_id, "DERIVED_FROM", "plan", plan.plan_id,
                "frozen analysis plan", actor,
            )
            store._ledger(
                "plan", plan.plan_id, "plan.executed", actor,
                {"session_id": view.session.session_id},
            )
            return view
