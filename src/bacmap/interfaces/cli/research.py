"""``bacmap research``：P1 Research Workbench 命令行入口。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.research import phylo, recipes, regression, reporting
from bacmap.research.models import (
    ArtifactKind,
    CreateSessionRequest,
    ResearchError,
    ResearchProfile,
)
from bacmap.research.service import (
    ResearchRequestService,
    ResearchService,
    default_profile,
)


def _service(args: argparse.Namespace) -> ResearchService:
    return ResearchService(Path(args.home))


def _emit(data: Any, as_json: bool) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def run_ls(args: argparse.Namespace) -> None:
    sessions = _service(args).list_sessions(args.limit)
    if args.json:
        _emit([s.model_dump(mode="json") for s in sessions], True)
        return
    for s in sessions:
        print(f"{s.session_id}  {s.status.value:<16} {s.gene} × {s.test_name}  run={s.run_id}")


def run_show(args: argparse.Namespace) -> None:
    try:
        view = _service(args).get_session(args.session_id)
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        _emit(view.model_dump(mode="json"), True)
        return
    s = view.session
    print(f"{s.session_id}  {s.status.value}  {s.label}")
    print(f"  run={s.run_id}  gene={s.gene}  test={s.test_name}  profile={s.profile.value}")
    if view.stat:
        print(f"  n={view.stat.n}  OR={view.stat.odds_ratio}  p={view.stat.p_value}")
        for k, v in view.stat.table.items():
            print(f"    {k}={v}")
    for a in view.artifacts:
        print(f"  {a.kind.value}: {a.path}")


def run_create(args: argparse.Namespace) -> None:
    try:
        p = ResearchProfile(args.profile) if args.profile else default_profile()
        view = _service(args).create_session(
            CreateSessionRequest(
                run_id=args.run_id,
                gene=args.gene,
                test_name=args.test_name,
                profile=p,
                study_id=args.study_id,
                cohort_id=args.cohort_id,
                plan_id=args.plan_id,
                note=args.note,
            ),
            actor=args.by,
            profile=p,
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        _emit(view.model_dump(mode="json"), True)
        return
    message = T(
        f"Created {view.session.session_id} ({view.session.status.value} / {view.session.label})",
        f"已创建 {view.session.session_id}（{view.session.status.value} / {view.session.label}）",
    )
    print(message)
    for a in view.artifacts:
        print(f"  {a.kind.value}: {a.path}")


def run_artifact(args: argparse.Namespace) -> None:
    try:
        path = _service(args).read_artifact(args.session_id, args.kind)
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    print(path.read_text(encoding="utf-8"))


def _runtime_status(recipe: recipes.FigureRecipe) -> dict[str, object]:
    runtime = recipe.runtime
    backend = ""
    available = False
    if runtime.kind == "builtin":
        available = True
        backend = "bacmap"
    elif runtime.kind == "container":
        backend = shutil.which("apptainer") or shutil.which("podman") or ""
        available = bool(backend)
    elif runtime.kind == "pixi":
        backend = shutil.which("pixi") or ""
        available = bool(backend)
    elif runtime.kind == "host":
        if recipe.language == "r":
            backend = shutil.which("Rscript") or ""
        else:
            backend = shutil.which("python") or ""
        available = bool(backend)
    return {
        "recipe_id": recipe.recipe_id,
        "language": recipe.language,
        "runtime": runtime.model_dump(mode="json"),
        "backend": backend,
        "available": available,
    }


def run_figure_runtimes(args: argparse.Namespace) -> None:
    items = [_runtime_status(recipe) for recipe in recipes.list_recipes()]
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    for item in items:
        runtime = item["runtime"]
        if not isinstance(runtime, dict):
            continue
        state = "ok" if item["available"] else "missing"
        print(
            f"{item['recipe_id']:<18} {runtime.get('kind', ''):<10} "
            f"{runtime.get('image') or runtime.get('environment') or '-':<24} "
            f"{state:<8} {item['backend']}"
        )


def run_figure_recipes(args: argparse.Namespace) -> None:
    items = recipes.list_recipes(executable_only=args.executable_only)
    if args.json:
        print(
            json.dumps(
                [recipe.model_dump(mode="json") for recipe in items],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    for recipe in items:
        print(
            f"{recipe.recipe_id:<18} {recipe.version:<8} {recipe.language:<7} "
            f"{recipe.status:<11} {recipe.title}"
        )


def run_figure_spec(args: argparse.Namespace) -> None:
    try:
        spec = _service(args).figure_spec(args.session_id)
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    print(json.dumps(spec.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2))


def run_figure_draft(args: argparse.Namespace) -> None:
    try:
        draft = _service(args).attach_draft(
            args.session_id, args.path, note=args.note, actor=args.by
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        print(json.dumps(draft, ensure_ascii=False, indent=2))
        return
    print(f"draft: {draft['path']}")
    print(f"  sha256: {draft['sha256']}")


def run_figure_drafts(args: argparse.Namespace) -> None:
    items = _service(args).list_drafts(args.session_id)
    if args.json:
        print(
            json.dumps(
                [item.model_dump(mode="json") for item in items],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    for item in items:
        print(
            f"{item.draft_id}  {item.status.value:<8} {item.sha256[:12]}…  "
            f"{item.note or ''}"
        )


def run_figure_feedback(args: argparse.Namespace) -> None:
    try:
        draft = _service(args).add_draft_feedback(
            args.draft_id, args.text, actor=args.by
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        print(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    print(f"{draft.draft_id}  feedback saved")


def run_figure_finalize(args: argparse.Namespace) -> None:
    try:
        artifact = _service(args).finalize_draft(
            args.draft_id,
            recipe_id=args.recipe or "custom",
            code_path=args.code or None,
            actor=args.by,
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        print(
            json.dumps(
                artifact.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(f"finalized {artifact.output}  recipe={artifact.recipe_id}")


def run_figure_reject(args: argparse.Namespace) -> None:
    try:
        draft = _service(args).reject_draft(
            args.draft_id, note=args.note, actor=args.by
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        print(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    print(f"{draft.draft_id}  {draft.status.value}")


def run_figure_attach(args: argparse.Namespace) -> None:
    try:
        artifact = _service(args).attach_figure(
            args.session_id,
            args.path,
            code=args.code or None,
            spec_path=args.spec or None,
            renderer=args.renderer,
            recipe_id=args.recipe,
            actor=args.by,
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        print(
            json.dumps(
                artifact.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(
        T(
            f"attached {artifact.output} ({artifact.renderer})",
            f"已登记图片 {artifact.output}（{artifact.renderer}）",
        )
    )
    print(f"  output_sha256: {artifact.output_sha256}")
    print(f"  spec_sha256:   {artifact.spec_sha256}")
    if artifact.code_sha256:
        print(f"  code_sha256:   {artifact.code_sha256}")


def _load_profile(path: str) -> phylo.AlignmentProfile:
    raw = Path(path).expanduser().read_text(encoding="utf-8")
    return phylo.AlignmentProfile.model_validate(json.loads(raw))


def _load_plan(path: str) -> phylo.PhyloPlan:
    raw = Path(path).expanduser().read_text(encoding="utf-8")
    return phylo.PhyloPlan.model_validate(json.loads(raw))


def run_phylo_profile(args: argparse.Namespace) -> None:
    try:
        profile = phylo.profile_alignment(
            args.alignment,
            dates=args.dates or None,
            partitions=[p.strip() for p in args.partitions.split(",") if p.strip()],
        )
    except phylo.PhyloError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(
            json.dumps(
                profile.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(
        f"{profile.n_taxa} taxa × {profile.n_sites} sites; "
        f"variable={profile.variable_sites} informative={profile.informative_sites}; "
        f"missing={profile.missing_pct:.2f}%"
    )
    for warning in profile.warnings:
        print(f"  warning: {warning}")


def run_phylo_plan(args: argparse.Namespace) -> None:
    try:
        profile = _load_profile(args.profile)
        plan = phylo.recommend_plan(profile, args.goal)
    except (OSError, ValueError, phylo.PhyloError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(
            json.dumps(
                plan.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(f"{plan.plan_id}  {plan.analysis}  {plan.tool}")
    print(
        f"  model={plan.substitution_model} "
        f"clock={plan.clock_model or '-'} prior={plan.tree_prior or '-'}"
    )
    print(f"  chain={plan.chain_length} burn_in={plan.burn_in} sampling={plan.sampling_every}")
    print(f"  rationale: {plan.rationale}")


def run_phylo_validate(args: argparse.Namespace) -> None:
    try:
        profile = _load_profile(args.profile)
        plan = _load_plan(args.plan)
        issues = phylo.validate_plan(plan, profile)
    except (OSError, ValueError, phylo.PhyloError) as exc:
        raise SystemExit(str(exc)) from exc
    payload = {"ok": not issues, "issues": issues}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("ok" if not issues else "INVALID")
    for issue in issues:
        print(f"  - {issue}")
    if issues:
        raise SystemExit(1)


def run_phylo_xml(args: argparse.Namespace) -> None:
    try:
        profile = _load_profile(args.profile)
        plan = _load_plan(args.plan)
        result = phylo.render_beast2_xml(
            plan, profile, args.out, validate=args.validate
        )
    except (OSError, ValueError, phylo.PhyloError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"wrote {result['xml']}  sha256={result['xml_sha256']}")
    validation = result.get("validation", {})
    if isinstance(validation, dict) and validation.get("requested"):
        print(f"  beast -validate: {'ok' if validation.get('ok') else 'FAILED'}")
        if not validation.get("ok"):
            raise SystemExit(1)


def run_phylo_iqtree(args: argparse.Namespace) -> None:
    try:
        plan = _load_plan(args.plan)
        cmd = phylo.render_iqtree_command(plan, args.alignment, args.prefix)
    except (OSError, ValueError, phylo.PhyloError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(json.dumps({"command": cmd}, ensure_ascii=False, indent=2))
        return
    print(" ".join(cmd))


def run_stats_logistic(args: argparse.Namespace) -> None:
    try:
        predictors = [name.strip() for name in args.predictors.split(",") if name.strip()]
        if not predictors:
            raise SystemExit("--predictors is empty")
        rows, outcomes, dropped = regression.load_table(
            args.data, args.outcome, predictors
        )
        result = regression.fit_logistic(rows, outcomes, predictors)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    payload = {
        "schema": "bacmap.logistic_regression/1",
        "n": result.n,
        "events": result.events,
        "dropped": dropped,
        "result": result.model_dump(mode="json"),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"n={result.n} events={result.events} dropped={dropped}")
    for name, beta, odds, low, high, p in zip(
        result.feature_names,
        result.coefficients,
        result.odds_ratios,
        result.ci_low,
        result.ci_high,
        result.p_values,
        strict=True,
    ):
        print(f"  {name:<20} beta={beta:+.4f} OR={odds:.3f} ({low:.3f}-{high:.3f}) p={p:.4g}")
    for warning in result.warnings:
        print(f"  warning: {warning}")


def run_package(args: argparse.Namespace) -> None:
    try:
        package = reporting.build_submission_package(
            args.home, args.study_id, args.out
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(
            json.dumps(
                package.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(f"package: {package.output_dir}")
    print(f"  checklist: {package.checklist.met} met, {package.checklist.partial} partial, "
          f"{package.checklist.missing} missing")
    print(f"  files: {len(package.files)}")
    for blocker in package.blockers:
        print(f"  blocker: {blocker}")


def _request_service(args: argparse.Namespace) -> ResearchRequestService:
    return ResearchRequestService(Path(args.home))


def run_request_create(args: argparse.Namespace) -> None:
    try:
        request = _request_service(args).propose_request(
            args.question,
            pathogen_scope=args.pathogen,
            data_class=args.data_class,
            run_ids=args.run_id,
            gene=args.gene,
            test_name=args.test_name,
            analysis=args.analysis,
            members=_load_json_arg(args.members, "members") if args.members else None,
            plan_spec=_load_json_arg(args.spec, "spec") if args.spec else None,
            note=args.note,
            actor=args.by,
        )
    except (ValueError, ResearchError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    print(f"{request.request_id}  {request.status.value}  {request.question}")


def run_request_list(args: argparse.Namespace) -> None:
    items = _request_service(args).list_requests(status=args.status or None, limit=args.limit)
    if args.json:
        print(
            json.dumps(
                [item.model_dump(mode="json") for item in items],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    for item in items:
        print(f"{item.request_id}  {item.status.value:<10} {item.analysis:<12} {item.question}")


def run_request_show(args: argparse.Namespace) -> None:
    try:
        request = _request_service(args).get_request(args.request_id)
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    print(json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2))


def run_request_approve(args: argparse.Namespace) -> None:
    try:
        request = _request_service(args).approve_request(
            args.request_id,
            members=_load_json_arg(args.members, "members") if args.members else None,
            plan_spec=_load_json_arg(args.spec, "spec") if args.spec else None,
            actor=args.by,
            note=args.note,
        )
    except (ValueError, ResearchError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    print(
        f"{request.request_id}  {request.status.value}  study={request.study_id} "
        f"cohort={request.cohort_id} plan={request.plan_id} session={request.session_id}"
    )


def run_request_reject(args: argparse.Namespace) -> None:
    try:
        request = _request_service(args).reject_request(
            args.request_id, actor=args.by, note=args.note
        )
    except ResearchError as exc:
        raise SystemExit(f"[{exc.code}] {exc.message}") from exc
    if args.json:
        print(json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    print(f"{request.request_id}  {request.status.value}")


def _object_service(args: argparse.Namespace):
    from bacmap.research.service import ResearchObjectService

    return ResearchObjectService(Path(args.home))


def _load_json_arg(raw: str, what: str):
    """Accept inline JSON or a path to a JSON file."""
    text = raw.strip()
    if not text:
        raise SystemExit(f"{what} is empty")
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{what} is not valid JSON: {exc}") from exc
    path = Path(text).expanduser()
    if not path.is_file():
        raise SystemExit(f"{what} is neither JSON nor an existing file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{what} file is not valid JSON: {path}: {exc}") from exc


def _load_members(raw: str) -> list[dict]:
    data = _load_json_arg(raw, "members")
    if isinstance(data, dict) and isinstance(data.get("members"), list):
        data = data["members"]
    if not isinstance(data, list):
        raise SystemExit("members must be a JSON array or an object with a members array")
    return data


def _object_error(exc: Exception) -> SystemExit:
    if isinstance(exc, ResearchError):
        return SystemExit(f"[{exc.code}] {exc.message}")
    return SystemExit(str(exc))


def run_study_create(args: argparse.Namespace) -> None:
    try:
        study = _object_service(args).create_study(
            args.question, args.pathogen, args.data_class, args.by
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(study.model_dump(mode="json"), True)
    else:
        print(f"{study.study_id}  {study.status.value}  {study.question}")


def run_study_ls(args: argparse.Namespace) -> None:
    studies = _object_service(args).list_studies(args.limit)
    if args.json:
        _emit([s.model_dump(mode="json") for s in studies], True)
        return
    for s in studies:
        print(f"{s.study_id}  {s.status.value:<8} D{s.data_class}  {s.question}")


def run_study_show(args: argparse.Namespace) -> None:
    try:
        study = _object_service(args).get_study(args.study_id)
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(study.model_dump(mode="json"), True)
    else:
        print(f"{study.study_id}  {study.status.value}  D{study.data_class}")
        print(f"  question: {study.question}")
        print(f"  scope: {study.pathogen_scope or '-'}")


def run_cohort_create(args: argparse.Namespace) -> None:
    try:
        cohort = _object_service(args).create_cohort(
            args.study_id,
            _load_members(args.members),
            _load_json_arg(args.rules, "rules") if args.rules else {},
            args.name,
            args.by,
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(cohort.model_dump(mode="json"), True)
    else:
        print(f"{cohort.cohort_id}  {cohort.status.value}  members={len(cohort.members)}")


def run_cohort_preview(args: argparse.Namespace) -> None:
    try:
        preview = _object_service(args).preview_cohort(
            args.study_id,
            _load_members(args.members),
            _load_json_arg(args.rules, "rules") if args.rules else {},
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    _emit(preview, True)


def run_cohort_freeze(args: argparse.Namespace) -> None:
    try:
        cohort = _object_service(args).freeze_cohort(args.cohort_id, args.by)
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(cohort.model_dump(mode="json"), True)
    else:
        print(f"{cohort.cohort_id}  frozen  {cohort.snapshot_hash}")


def run_cohort_ls(args: argparse.Namespace) -> None:
    from bacmap.research.store import ResearchObjectStore

    with ResearchObjectStore(Path(args.home)) as store:
        items = store.list_cohorts(args.study_id, args.limit)
    if args.json:
        _emit([c.model_dump(mode="json") for c in items], True)
        return
    for c in items:
        print(f"{c.cohort_id}  {c.status.value:<6} members={len(c.members)}  {c.name}")


def run_plan_create(args: argparse.Namespace) -> None:
    try:
        plan = _object_service(args).create_plan(
            args.study_id,
            args.cohort_id,
            _load_json_arg(args.spec, "spec"),
            args.by,
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(plan.model_dump(mode="json"), True)
    else:
        print(f"{plan.plan_id}  {plan.status.value}  {plan.plan_hash}")


def run_plan_freeze(args: argparse.Namespace) -> None:
    try:
        plan = _object_service(args).freeze_plan(args.plan_id, args.by)
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(plan.model_dump(mode="json"), True)
    else:
        print(f"{plan.plan_id}  frozen  {plan.plan_hash}")


def run_plan_run(args: argparse.Namespace) -> None:
    try:
        view = _object_service(args).run_plan(args.plan_id, args.by)
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(view.model_dump(mode="json"), True)
    else:
        print(f"{view.session.session_id}  {view.session.status.value}")
        if view.stat:
            print(f"  n={view.stat.n}  OR={view.stat.odds_ratio}  p={view.stat.p_value}")


def run_claim_create(args: argparse.Namespace) -> None:
    try:
        claim = _object_service(args).create_claim(
            args.study_id,
            args.claim_type,
            args.wording,
            args.level,
            _load_json_arg(args.evidence, "evidence") if args.evidence else {},
            args.by,
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(claim.model_dump(mode="json"), True)
    else:
        print(f"{claim.claim_id}  {claim.claim_type.value}  {claim.evidence_level.value}"
              f"  {claim.status.value}")


def run_claim_review(args: argparse.Namespace) -> None:
    try:
        claim = _object_service(args).review_claim(
            args.claim_id, args.decision, args.message or "", args.by
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(claim.model_dump(mode="json"), True)
    else:
        print(f"{claim.claim_id}  {claim.status.value}")


def run_claim_ls(args: argparse.Namespace) -> None:
    from bacmap.research.store import ResearchObjectStore

    with ResearchObjectStore(Path(args.home)) as store:
        items = store.list_claims(args.study_id, args.limit)
    if args.json:
        _emit([c.model_dump(mode="json") for c in items], True)
        return
    for c in items:
        print(f"{c.claim_id}  {c.claim_type.value:<12} {c.evidence_level.value}"
              f"  {c.status.value:<20} {c.wording}")


def run_experiment_record(args: argparse.Namespace) -> None:
    try:
        exp = _object_service(args).record_experiment(
            args.plan_id,
            args.status,
            args.run_id or [],
            _load_json_arg(args.outcome, "outcome") if args.outcome else {},
            args.deviation or "",
            args.by,
        )
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(exp.model_dump(mode="json"), True)
    else:
        print(f"{exp.experiment_id}  {exp.status.value}  plan={exp.plan_id}")


def run_experiment_ls(args: argparse.Namespace) -> None:
    items = _object_service(args).list_experiments(args.study_id, args.plan_id, args.limit)
    if args.json:
        _emit([e.model_dump(mode="json") for e in items], True)
        return
    for e in items:
        print(f"{e.experiment_id}  {e.status.value:<9} plan={e.plan_id}"
              f"  runs={','.join(e.run_ids) or '-'}")


def run_publication(args: argparse.Namespace) -> None:
    try:
        out = _object_service(args).publication_readiness(args.study_id)
    except Exception as exc:
        raise _object_error(exc) from exc
    if args.json:
        _emit(out, True)
        return
    print(f"{out['study_id']}  ready={str(out['ready']).lower()}")
    for gate in out["gates"]:
        print(f"  {gate['id']}  {'PASS' if gate['ok'] else 'FAIL'}  {gate['title']}")
        for blocker in gate["blockers"]:
            print(f"      - {blocker}")


def run_outbreak(args: argparse.Namespace) -> None:
    from bacmap.research.outbreak import OutbreakEvent, summarize_outbreak

    data = _load_json_arg(args.events, "events")
    if isinstance(data, dict):
        data = data.get("events", [])
    if not isinstance(data, list):
        raise SystemExit("events must be a JSON array")
    try:
        events = [OutbreakEvent(**row) for row in data]
    except Exception as exc:
        raise SystemExit(f"invalid event: {exc}") from exc
    _emit(summarize_outbreak(events, args.min_count), True)


def run_sensitivity(args: argparse.Namespace) -> None:
    from bacmap.research.stats import sensitivity_summary

    try:
        table = tuple(int(x.strip()) for x in args.table.split(","))
    except ValueError as exc:
        raise SystemExit("--table must be four integers: a,b,c,d") from exc
    if len(table) != 4:
        raise SystemExit("--table must be four integers: a,b,c,d")
    strata: list[tuple[str, int, int, int, int]] | None = None
    if args.strata:
        raw = _load_json_arg(args.strata, "strata")
        if not isinstance(raw, list):
            raise SystemExit("strata must be a JSON array of [label,a,b,c,d]")
        try:
            strata = []
            for row in raw:
                strata.append((str(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4])))
        except (TypeError, ValueError, IndexError) as exc:
            raise SystemExit("each stratum must be [label,a,b,c,d]") from exc
    _emit(sensitivity_summary(table, strata), True)


def run_explore(args: argparse.Namespace) -> None:
    from bacmap.research.discovery import ExploreBudget, explore_candidates

    data = _load_json_arg(args.cases, "cases")
    if isinstance(data, dict):
        data = data.get("cases", [])
    if not isinstance(data, list):
        raise SystemExit("cases must be a JSON array")
    budget = ExploreBudget(
        max_tests=args.max_tests,
        max_candidates=args.max_candidates,
        min_n=args.min_n,
        max_q=args.max_q,
    )
    try:
        out = explore_candidates(args.study_id, data, budget, role="screening")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _emit(out, True)


def run_benchmark(args: argparse.Namespace) -> None:
    from bacmap.research.benchmarks import (
        run_amr_benchmark,
        run_bvbrc_amr_benchmark,
        summarize_osf_cohort,
        verify_benchmark_dir,
    )

    dataset_dirs = {
        "bvbrc": ("bvbrc_kpn_meropenem", run_bvbrc_amr_benchmark),
        "osf": ("osf_n78q3", summarize_osf_cohort),
        "verify-bvbrc": ("bvbrc_kpn_meropenem", verify_benchmark_dir),
        "verify-osf": ("osf_n78q3", verify_benchmark_dir),
    }
    if args.name == "amr":
        out = run_amr_benchmark()
    else:
        dataset, fn = dataset_dirs[args.name]
        root = Path(args.data) if args.data else Path(args.home) / "benchmarks" / dataset
        out = fn(root)
    _emit(out, args.json)


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser(
        "research", help=T("Research Workbench (P1 thin path)", "Research Workbench（P1 薄链路）")
    )
    s = p.add_subparsers(dest="research_command", required=True)

    ls = s.add_parser("list", aliases=["ls"], help=T("List research sessions", "列出研究会话"))
    ls.add_argument("--limit", type=int, default=50)
    add_home(ls)
    add_json(ls)
    ls.set_defaults(func=run_ls)

    show = s.add_parser("show", help=T("Show research session", "查看研究会话"))
    show.add_argument("session_id")
    add_home(show)
    add_json(show)
    show.set_defaults(func=run_show)

    create = s.add_parser(
        "create",
        help=T(
            "Create an AMR association draft from an existing run",
            "从既有 run 生成 AMR 关联草案",
        ),
    )
    create.add_argument("--run-id", required=True)
    create.add_argument("--gene", required=True)
    create.add_argument("--test-name", required=True)
    create.add_argument("--profile", choices=[x.value for x in ResearchProfile], default=None)
    create.add_argument(
        "--study", dest="study_id", default="", help=T("link a Study", "关联 Study")
    )
    create.add_argument(
        "--cohort", dest="cohort_id", default="", help=T("link a Cohort", "关联 Cohort")
    )
    create.add_argument(
        "--plan",
        dest="plan_id",
        default="",
        help=T("link an AnalysisPlan", "关联 AnalysisPlan"),
    )
    create.add_argument("--note", default="", help=T("research note", "研究说明"))
    create.add_argument("--by", default="cli")
    add_home(create)
    add_json(create)
    create.set_defaults(func=run_create)

    art = s.add_parser(
        "artifact", help=T("Output figure/report/manuscript", "输出 figure/report/manuscript")
    )
    art.add_argument("session_id")
    art.add_argument("kind", choices=[k.value for k in ArtifactKind])
    add_home(art)
    art.set_defaults(func=run_artifact)

    fig = s.add_parser(
        "figure",
        help=T(
            "Publication figure contract (spec/attach)", "发表级图片契约（spec/attach）"
        ),
    )
    fig_sub = fig.add_subparsers(dest="figure_command", required=True)
    fig_runtimes = fig_sub.add_parser(
        "runtimes", help=T("check recipe runtimes (R/Python/container)", "检查 recipe 运行时")
    )
    add_json(fig_runtimes)
    fig_runtimes.set_defaults(func=run_figure_runtimes)
    fig_recipes = fig_sub.add_parser(
        "recipes", help=T("list figure recipes", "列出图片 recipe")
    )
    fig_recipes.add_argument(
        "--executable-only",
        action="store_true",
        help=T("only recipes with a working entrypoint", "只显示可执行 recipe"),
    )
    add_json(fig_recipes)
    fig_recipes.set_defaults(func=run_figure_recipes)
    fig_spec = fig_sub.add_parser(
        "spec", help=T("print the machine-readable figure contract", "输出图片契约 JSON")
    )
    fig_spec.add_argument("session_id")
    add_home(fig_spec)
    add_json(fig_spec)
    fig_spec.set_defaults(func=run_figure_spec)
    fig_draft = fig_sub.add_parser(
        "draft", help=T("record an intermediate figure draft", "记录图片草稿")
    )
    fig_draft.add_argument("session_id")
    fig_draft.add_argument("--path", required=True, help=T("draft figure file", "草稿图片"))
    fig_draft.add_argument("--note", default="", help=T("iteration note", "迭代说明"))
    fig_draft.add_argument("--by", default="cli")
    add_home(fig_draft)
    add_json(fig_draft)
    fig_draft.set_defaults(func=run_figure_draft)
    fig_drafts = fig_sub.add_parser(
        "drafts", help=T("list figure drafts", "列出图片草稿")
    )
    fig_drafts.add_argument("session_id")
    add_home(fig_drafts)
    add_json(fig_drafts)
    fig_drafts.set_defaults(func=run_figure_drafts)
    fig_feedback = fig_sub.add_parser(
        "feedback", help=T("save feedback for a draft", "保存草稿反馈")
    )
    fig_feedback.add_argument("draft_id")
    fig_feedback.add_argument("--text", required=True)
    fig_feedback.add_argument("--by", default="cli")
    add_home(fig_feedback)
    add_json(fig_feedback)
    fig_feedback.set_defaults(func=run_figure_feedback)
    fig_final = fig_sub.add_parser(
        "finalize", help=T("attach a draft as the final custom figure", "草稿转最终图")
    )
    fig_final.add_argument("draft_id")
    fig_final.add_argument("--recipe", default="custom")
    fig_final.add_argument("--code", default="")
    fig_final.add_argument("--by", default="cli")
    add_home(fig_final)
    add_json(fig_final)
    fig_final.set_defaults(func=run_figure_finalize)
    fig_reject = fig_sub.add_parser(
        "reject", help=T("reject a draft", "拒绝草稿")
    )
    fig_reject.add_argument("draft_id")
    fig_reject.add_argument("--note", default="")
    fig_reject.add_argument("--by", default="cli")
    add_home(fig_reject)
    add_json(fig_reject)
    fig_reject.set_defaults(func=run_figure_reject)
    fig_att = fig_sub.add_parser(
        "attach",
        help=T(
            "register a rendered figure with provenance", "登记已渲染图片及其来源"
        ),
    )
    fig_att.add_argument("session_id")
    fig_att.add_argument(
        "--path", required=True, help=T("rendered figure file", "图片文件")
    )
    fig_att.add_argument(
        "--code", default="", help=T("plotting script (optional)", "绘图脚本（可选）")
    )
    fig_att.add_argument(
        "--spec", default="", help=T("custom spec JSON (optional)", "自定义契约 JSON（可选）")
    )
    fig_att.add_argument(
        "--renderer",
        choices=["agent-script", "bacmap-deterministic"],
        default="agent-script",
    )
    fig_att.add_argument(
        "--recipe",
        default="",
        help=T(
            "recipe id (default: custom for agent scripts)",
            "recipe id（agent 脚本默认 custom）",
        ),
    )
    fig_att.add_argument("--by", default="cli")
    add_home(fig_att)
    add_json(fig_att)
    fig_att.set_defaults(func=run_figure_attach)

    phylo_p = s.add_parser(
        "phylo",
        help=T(
            "Phylogenetic planning (profile/plan/XML)",
            "系统发育规划（profile/plan/XML）",
        ),
    )
    phylo_sub = phylo_p.add_subparsers(dest="phylo_command", required=True)
    phylo_prof = phylo_sub.add_parser(
        "profile", help=T("summarise an alignment", "统计比对特征")
    )
    phylo_prof.add_argument("--alignment", required=True)
    phylo_prof.add_argument("--dates", default="", help=T("taxon/date TSV", "taxon/date TSV"))
    phylo_prof.add_argument(
        "--partitions",
        default="",
        help=T("comma-separated partition candidates", "逗号分隔分区候选"),
    )
    add_json(phylo_prof)
    phylo_prof.set_defaults(func=run_phylo_profile)
    phylo_plan = phylo_sub.add_parser(
        "plan", help=T("recommend a typed PhyloPlan", "生成类型化 PhyloPlan")
    )
    phylo_plan.add_argument("--profile", required=True)
    phylo_plan.add_argument("--goal", choices=["ml", "bayesian"], default="bayesian")
    add_json(phylo_plan)
    phylo_plan.set_defaults(func=run_phylo_plan)
    phylo_val = phylo_sub.add_parser(
        "validate", help=T("validate a PhyloPlan against its profile", "校验 PhyloPlan")
    )
    phylo_val.add_argument("--profile", required=True)
    phylo_val.add_argument("--plan", required=True)
    add_json(phylo_val)
    phylo_val.set_defaults(func=run_phylo_validate)
    phylo_xml = phylo_sub.add_parser(
        "xml", help=T("render a BEAST2 XML template", "渲染 BEAST2 XML 模板")
    )
    phylo_xml.add_argument("--profile", required=True)
    phylo_xml.add_argument("--plan", required=True)
    phylo_xml.add_argument("--alignment", required=True)
    phylo_xml.add_argument("-o", "--out", required=True)
    phylo_xml.add_argument(
        "--validate", action="store_true", help=T("run beast -validate", "运行 beast -validate")
    )
    add_json(phylo_xml)
    phylo_xml.set_defaults(func=run_phylo_xml)
    phylo_iq = phylo_sub.add_parser(
        "iqtree", help=T("print the IQ-TREE command", "输出 IQ-TREE 命令")
    )
    phylo_iq.add_argument("--plan", required=True)
    phylo_iq.add_argument("--alignment", required=True)
    phylo_iq.add_argument("--prefix", default="iqtree")
    add_json(phylo_iq)
    phylo_iq.set_defaults(func=run_phylo_iqtree)

    stats = s.add_parser(
        "stats", help=T("Deterministic statistics", "确定性统计")
    )
    stats_sub = stats.add_subparsers(dest="stats_command", required=True)
    logistic = stats_sub.add_parser(
        "logistic", help=T("multivariable logistic regression", "多变量 logistic 回归")
    )
    logistic.add_argument("--data", required=True, help=T("CSV/TSV table", "CSV/TSV 表"))
    logistic.add_argument("--outcome", required=True, help=T("0/1 outcome column", "0/1 结局列"))
    logistic.add_argument(
        "--predictors", required=True, help=T("comma-separated predictor columns", "逗号分隔预测列")
    )
    add_json(logistic)
    logistic.set_defaults(
        func=run_stats_logistic,
    )

    package = s.add_parser(
        "package",
        help=T("build a submission package and STROBE draft", "生成投稿包与 STROBE 草案"),
    )
    package.add_argument("study_id")
    package.add_argument("--out", required=True, help=T("output directory", "输出目录"))
    add_home(package)
    add_json(package)
    package.set_defaults(func=run_package)

    request_p = s.add_parser(
        "request", help=T("Research request inbox", "研究请求收件箱")
    )
    request_sub = request_p.add_subparsers(dest="request_command", required=True)
    req_create = request_sub.add_parser(
        "create", help=T("propose a research request", "提交研究请求草案")
    )
    req_create.add_argument("--question", required=True)
    req_create.add_argument("--pathogen", default="")
    req_create.add_argument("--data-class", type=int, choices=[0, 1, 2, 3, 4], default=2)
    req_create.add_argument("--run-id", action="append", default=[])
    req_create.add_argument("--gene", default="")
    req_create.add_argument("--test-name", default="")
    req_create.add_argument(
        "--analysis", choices=["association", "logistic", "phylo", "figure"], default="association"
    )
    req_create.add_argument("--members", default="")
    req_create.add_argument("--spec", default="")
    req_create.add_argument("--note", default="")
    req_create.add_argument("--by", default="cli")
    add_home(req_create)
    add_json(req_create)
    req_create.set_defaults(func=run_request_create)
    req_list = request_sub.add_parser("list", aliases=["ls"], help=T("list requests", "列出请求"))
    req_list.add_argument("--status", default="proposed")
    req_list.add_argument("--limit", type=int, default=50)
    add_home(req_list)
    add_json(req_list)
    req_list.set_defaults(func=run_request_list)
    req_show = request_sub.add_parser("show", help=T("show a request", "查看请求"))
    req_show.add_argument("request_id")
    add_home(req_show)
    add_json(req_show)
    req_show.set_defaults(func=run_request_show)
    req_approve = request_sub.add_parser(
        "approve", help=T("approve and create research objects", "确认并创建研究对象")
    )
    req_approve.add_argument("request_id")
    req_approve.add_argument("--members", default="")
    req_approve.add_argument("--spec", default="")
    req_approve.add_argument("--note", default="")
    req_approve.add_argument("--by", default="cli")
    add_home(req_approve)
    add_json(req_approve)
    req_approve.set_defaults(func=run_request_approve)
    req_reject = request_sub.add_parser("reject", help=T("reject a request", "拒绝请求"))
    req_reject.add_argument("request_id")
    req_reject.add_argument("--note", default="")
    req_reject.add_argument("--by", default="cli")
    add_home(req_reject)
    add_json(req_reject)
    req_reject.set_defaults(func=run_request_reject)

    study = s.add_parser("study", help=T("Study object", "Study 对象"))
    study_sub = study.add_subparsers(dest="study_command", required=True)
    st_c = study_sub.add_parser("create", help=T("Create a Study", "创建 Study"))
    st_c.add_argument("--question", required=True)
    st_c.add_argument("--pathogen", default="")
    st_c.add_argument("--data-class", type=int, choices=[0, 1, 2, 3, 4], default=2)
    st_c.add_argument("--by", default="cli")
    add_home(st_c)
    add_json(st_c)
    st_c.set_defaults(func=run_study_create)
    st_ls = study_sub.add_parser("ls", aliases=["list"], help=T("List Study", "列出 Study"))
    st_ls.add_argument("--limit", type=int, default=50)
    add_home(st_ls)
    add_json(st_ls)
    st_ls.set_defaults(func=run_study_ls)
    st_s = study_sub.add_parser("show", help=T("Show Study", "查看 Study"))
    st_s.add_argument("study_id")
    add_home(st_s)
    add_json(st_s)
    st_s.set_defaults(func=run_study_show)

    cohort = s.add_parser("cohort", help=T("Cohort object", "Cohort 对象"))
    cohort_sub = cohort.add_subparsers(dest="cohort_command", required=True)
    co_c = cohort_sub.add_parser("create", help=T("Create a Cohort", "创建 Cohort"))
    co_c.add_argument("--study", dest="study_id", required=True)
    co_c.add_argument("--name", default="")
    co_c.add_argument(
        "--members", required=True,
        help=T(
            "JSON array, or a JSON file containing members",
            "JSON 数组或包含 members 的 JSON 文件",
        ),
    )
    co_c.add_argument("--rules", default="", help=T("JSON object or file", "JSON 对象或文件"))
    co_c.add_argument("--by", default="cli")
    add_home(co_c)
    add_json(co_c)
    co_c.set_defaults(func=run_cohort_create)
    co_p = cohort_sub.add_parser(
        "preview", help=T("Cohort dry run (without writing)", "Cohort 预检（不写库）")
    )
    co_p.add_argument("--study", dest="study_id", required=True)
    co_p.add_argument("--members", required=True)
    co_p.add_argument("--rules", default="")
    add_home(co_p)
    add_json(co_p)
    co_p.set_defaults(func=run_cohort_preview)
    co_f = cohort_sub.add_parser("freeze", help=T("Freeze Cohort", "冻结 Cohort"))
    co_f.add_argument("cohort_id")
    co_f.add_argument("--by", default="cli")
    add_home(co_f)
    add_json(co_f)
    co_f.set_defaults(func=run_cohort_freeze)
    co_ls = cohort_sub.add_parser("ls", aliases=["list"], help=T("List Cohort", "列出 Cohort"))
    co_ls.add_argument("--study", dest="study_id", default=None)
    co_ls.add_argument("--limit", type=int, default=100)
    add_home(co_ls)
    add_json(co_ls)
    co_ls.set_defaults(func=run_cohort_ls)

    plan = s.add_parser("plan", help=T("AnalysisPlan object", "AnalysisPlan 对象"))
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    pl_c = plan_sub.add_parser(
        "create", help=T("Create a plan (requires a frozen Cohort)", "创建计划（需已冻结 Cohort）")
    )
    pl_c.add_argument("--study", dest="study_id", required=True)
    pl_c.add_argument("--cohort", dest="cohort_id", required=True)
    pl_c.add_argument("--spec", required=True, help=T("JSON object or file", "JSON 对象或文件"))
    pl_c.add_argument("--by", default="cli")
    add_home(pl_c)
    add_json(pl_c)
    pl_c.set_defaults(func=run_plan_create)
    pl_f = plan_sub.add_parser("freeze", help=T("Freeze plan", "冻结计划"))
    pl_f.add_argument("plan_id")
    pl_f.add_argument("--by", default="cli")
    add_home(pl_f)
    add_json(pl_f)
    pl_f.set_defaults(func=run_plan_freeze)
    pl_r = plan_sub.add_parser(
        "run", help=T("Run a frozen plan (P1 AMR recipe)", "执行冻结计划（P1 AMR recipe）")
    )
    pl_r.add_argument("plan_id")
    pl_r.add_argument("--by", default="cli")
    add_home(pl_r)
    add_json(pl_r)
    pl_r.set_defaults(func=run_plan_run)

    claim = s.add_parser("claim", help=T("Claim object", "Claim 对象"))
    claim_sub = claim.add_subparsers(dest="claim_command", required=True)
    cl_c = claim_sub.add_parser("create", help=T("Create a Claim draft", "创建 Claim 草案"))
    cl_c.add_argument("--study", dest="study_id", required=True)
    cl_c.add_argument("--type", dest="claim_type", required=True,
                      choices=["observation", "association", "transmission", "causal", "mechanism"])
    cl_c.add_argument("--wording", required=True)
    cl_c.add_argument("--level", default="E0", choices=["E0", "E1", "E2", "E3", "E4"])
    cl_c.add_argument("--evidence", default="", help=T("JSON object or file", "JSON 对象或文件"))
    cl_c.add_argument("--by", default="cli")
    add_home(cl_c)
    add_json(cl_c)
    cl_c.set_defaults(func=run_claim_create)
    cl_r = claim_sub.add_parser("review", help=T("Review Claim", "审核 Claim"))
    cl_r.add_argument("claim_id")
    cl_r.add_argument("--decision", required=True,
                      choices=["support", "challenge", "reject", "approve"])
    cl_r.add_argument("--message", default="")
    cl_r.add_argument("--by", default="cli")
    add_home(cl_r)
    add_json(cl_r)
    cl_r.set_defaults(func=run_claim_review)
    cl_ls = claim_sub.add_parser("ls", aliases=["list"], help=T("List Claim", "列出 Claim"))
    cl_ls.add_argument("--study", dest="study_id", default=None)
    cl_ls.add_argument("--limit", type=int, default=100)
    add_home(cl_ls)
    add_json(cl_ls)
    cl_ls.set_defaults(func=run_claim_ls)

    experiment = s.add_parser("experiment", help=T("Experiment ledger", "Experiment 账本"))
    exp_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    ex_r = exp_sub.add_parser("record", help=T("Record an actual run", "记录一次实际执行"))
    ex_r.add_argument("--plan", dest="plan_id", required=True)
    ex_r.add_argument("--status", required=True,
                      choices=["success", "failed", "negative", "deviated"])
    ex_r.add_argument("--run-id", action="append", default=[], dest="run_id")
    ex_r.add_argument("--outcome", default="", help=T("JSON object or file", "JSON 对象或文件"))
    ex_r.add_argument("--deviation", default="")
    ex_r.add_argument("--by", default="cli")
    add_home(ex_r)
    add_json(ex_r)
    ex_r.set_defaults(func=run_experiment_record)
    ex_ls = exp_sub.add_parser("ls", aliases=["list"], help=T("List Experiment", "列出 Experiment"))
    ex_ls.add_argument("--study", dest="study_id", default=None)
    ex_ls.add_argument("--plan", dest="plan_id", default=None)
    ex_ls.add_argument("--limit", type=int, default=100)
    add_home(ex_ls)
    add_json(ex_ls)
    ex_ls.set_defaults(func=run_experiment_ls)

    pub = s.add_parser("publication", help=T("Check publication gates G0-G3", "检查发表门 G0–G3"))
    pub.add_argument("study_id")
    add_home(pub)
    add_json(pub)
    pub.set_defaults(func=run_publication)

    outbreak = s.add_parser(
        "outbreak",
        help=T(
            "Outbreak/sporadic event mining (context only, no transmission direction)",
            "暴发/散在事件挖掘（上下文，不做传播方向）",
        ),
    )
    outbreak.add_argument(
        "--events", required=True,
        help=T("JSON array of events, or a file", "事件 JSON 数组或文件"),
    )
    outbreak.add_argument("--min-count", type=int, default=5, dest="min_count")
    add_home(outbreak)
    add_json(outbreak)
    outbreak.set_defaults(func=run_outbreak)

    sens = s.add_parser(
        "sensitivity",
        help=T(
            "2x2 sensitivity analysis (MH/leave-one-out/E-value)",
            "2×2 敏感性分析（MH/留一/E-value）",
        ),
    )
    sens.add_argument("--table", required=True, help="a,b,c,d")
    sens.add_argument("--strata", default="",
                      help=T("[[label,a,b,c,d], ...] or a file", "[[label,a,b,c,d], ...] 或文件"))
    add_home(sens)
    add_json(sens)
    sens.set_defaults(func=run_sensitivity)

    explore = s.add_parser(
        "explore",
        help=T(
            "P3 candidate exploration (screening data only)",
            "P3 候选探索（仅 screening 数据）",
        ),
    )
    explore.add_argument("--study", dest="study_id", required=True)
    explore.add_argument(
        "--cases", required=True,
        help=T("JSON array of candidate cases, or a file", "候选案例 JSON 数组或文件"),
    )
    explore.add_argument("--max-tests", type=int, default=200, dest="max_tests")
    explore.add_argument("--max-candidates", type=int, default=20, dest="max_candidates")
    explore.add_argument("--min-n", type=int, default=20, dest="min_n")
    explore.add_argument("--max-q", type=float, default=0.05, dest="max_q")
    add_home(explore)
    add_json(explore)
    explore.set_defaults(func=run_explore)

    bench = s.add_parser(
        "benchmark", help=T("Run L0/L1/L2 scientific benchmarks", "运行 L0/L1/L2 科学基准")
    )
    bench.add_argument(
        "name",
        choices=["amr", "bvbrc", "osf", "verify-bvbrc", "verify-osf"],
        help=T(
            "amr=L0 synthetic; bvbrc=L1 real AMR;"
            " osf=L2 cohort summary; verify-* verifies snapshots",
            "amr=L0 合成；bvbrc=L1 真实 AMR；osf=L2 队列摘要；verify-* 校验快照",
        ),
    )
    bench.add_argument(
        "--data", default="",
        help=T(
            "Local data directory (default $BACMAP_HOME/benchmarks)",
            "本地数据目录（默认 $BACMAP_HOME/benchmarks）",
        ),
    )
    add_home(bench)
    add_json(bench)
    bench.set_defaults(func=run_benchmark)
