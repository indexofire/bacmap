"""湿实验导入提案 API（v1.10.53，P1）。

流程：上传 → 本地解析/摘要 → ``pending_review`` → analyst/admin 审核 →
提交一个 ``record`` batch 任务。上传本身**不写**任何 specimen/isolate/library
元数据；文件保存在 ``$BACMAP_HOME/imports/<job_id>/``（0600），审核前不进入业务表。
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from bacmap.agent.llm.endpoints import load_llm_config
from bacmap.agent.llm.gateway import DataClassViolationError, LlmGateway, LlmUnavailableError
from bacmap.agent.llm.import_mapping import advise_import_mapping
from bacmap.config import config_path
from bacmap.interfaces.cli.wetlab import parse_import_file
from bacmap.interfaces.web.auth import Principal, verify_csrf
from bacmap.interfaces.web.rbac import Permission, actor, require_permission
from bacmap.interfaces.web.wetlab import assert_rows_owned
from bacmap.store.import_jobs import ImportJobService
from bacmap.store.users import Role, UserService
from bacmap.store.wetlab_targets import target_version
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.events import EventLog, EventType
from bacmap.tasks.records import parse_record
from bacmap.tasks.spec import TaskId, TaskType
from bacmap.tools.spec import DataClass

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".txt"}


def _imports_home(engine: DbosTaskEngine) -> Path:
    return Path(engine.home) / "imports"


def _job_service(engine: DbosTaskEngine) -> ImportJobService:
    return ImportJobService(Path(engine.home) / "data" / "bacmap.sqlite")


def _require_csrf(request: Request) -> None:
    if not verify_csrf(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(403, "CSRF check failed")


def _audit(
    engine: DbosTaskEngine,
    type_: EventType,
    *,
    actor_name: str,
    payload: dict[str, Any],
) -> None:
    try:
        EventLog(engine.db).append(
            type_,
            actor=actor_name,
            payload=payload,
            data_class=DataClass.D2,
        )
    except Exception:  # 审计旁路不阻断导入
        import logging

        logging.getLogger(__name__).warning("import audit failed", exc_info=True)


def _scope_creator(principal: Principal | None, fallback: str) -> str | None:
    """普通用户只看自己的提案；analyst/admin（或旧模式）看全部。"""
    if principal is None:
        return None
    return principal.username if principal.role is Role.USER else None


_OWNER_KINDS = {
    "metadata",
    "specimen_metadata",
    "library_metadata",
    "lab_result",
    "specimen_assign",
    "specimen_create",
    "isolate_create",
}


def _submitter_role(engine: DbosTaskEngine, username: str) -> Role | None:
    with UserService(Path(engine.home) / "data" / "bacmap.sqlite") as users:
        user = users.get_by_username(username)
    return user.role if user is not None else None


def _inject_owner(params: dict[str, Any], owner: str) -> dict[str, Any]:
    """把审核通过的数据归属到提交人（只对写类 kind；已有 owner 不会被覆盖）。"""
    kind = str(params.get("kind") or "")
    if kind == "batch":
        for row in params.get("rows") or []:
            if isinstance(row, dict) and row.get("kind") in _OWNER_KINDS:
                row["owner_user_id"] = owner
    elif kind in _OWNER_KINDS:
        params["owner_user_id"] = owner
    return params


def _job_or_404(svc: ImportJobService, job_id: str) -> dict[str, Any]:
    job = svc.get(job_id)
    if job is None:
        raise HTTPException(404, "no such import job")
    return job


def _ensure_job_access(principal: Principal | None, job: dict[str, Any]) -> None:
    if principal is None:
        return
    if principal.role is Role.USER and job["created_by"] != principal.username:
        raise HTTPException(404, "no such import job")


def _safe_parse(
    path: Path, home: Path, sheet_args: dict[str, Any]
) -> tuple[Any, dict[str, Any], list[str]]:
    return parse_import_file(
        path,
        home=home,
        specimen_sheet=str(sheet_args.get("specimen_sheet") or ""),
        isolate_sheet=str(sheet_args.get("isolate_sheet") or ""),
        metadata_sheet=str(sheet_args.get("metadata_sheet") or ""),
        library_sheet=str(sheet_args.get("library_sheet") or ""),
        lab_sheet=str(sheet_args.get("lab_sheet") or ""),
        lab_subject=str(sheet_args.get("lab_subject") or "auto"),
    )


def build_import_routes(app: APIRouter, engine: DbosTaskEngine) -> None:  # noqa: C901 — 路由族内聚
    @app.post("/imports")
    def upload_import(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008 — FastAPI 依赖注入签名
        specimen_sheet: str = Form(""),
        isolate_sheet: str = Form(""),
        metadata_sheet: str = Form(""),
        library_sheet: str = Form(""),
        lab_sheet: str = Form(""),
        lab_subject: str = Form("auto"),
    ) -> JSONResponse:
        _require_csrf(request)
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in _ALLOWED_SUFFIXES:
            raise HTTPException(400, "unsupported file; use .xlsx/.xlsm/.csv/.tsv")
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file too large (max 20 MB)")
        job_id = "imp_" + uuid.uuid4().hex[:16]
        root = _imports_home(engine) / job_id
        root.mkdir(parents=True, mode=0o700)
        target = root / f"upload{suffix}"
        target.write_bytes(data)
        with contextlib.suppress(OSError):
            target.chmod(0o600)
        sheet_args = {
            "specimen_sheet": specimen_sheet.strip(),
            "isolate_sheet": isolate_sheet.strip(),
            "metadata_sheet": metadata_sheet.strip(),
            "library_sheet": library_sheet.strip(),
            "lab_sheet": lab_sheet.strip(),
            "lab_subject": (
                lab_subject
                if lab_subject in {"auto", "isolate", "specimen"}
                else "auto"
            ),
        }
        try:
            record, summary, errors = _safe_parse(target, Path(engine.home), sheet_args)
        except (OSError, ValueError) as exc:
            shutil.rmtree(root, ignore_errors=True)
            raise HTTPException(400, f"import parse failed: {exc}") from exc
        if errors or record is None:
            shutil.rmtree(root, ignore_errors=True)
            return JSONResponse(
                {
                    "code": "validation_error",
                    "error": "import has invalid rows",
                    "details": errors[:50],
                },
                status_code=400,
            )
        if principal is not None and principal.role is Role.USER:
            denied = assert_rows_owned(Path(engine.home), record.rows, principal.username)
            if denied:
                shutil.rmtree(root, ignore_errors=True)
                raise HTTPException(
                    403,
                    "rows target data you do not own: " + ", ".join(sorted(set(denied))[:10]),
                )
        with _job_service(engine) as svc:
            job = svc.create(
                job_id=job_id,
                filename=filename,
                file_sha256=hashlib.sha256(data).hexdigest(),
                file_path=target,
                created_by=actor(request, "web"),
                sheet_args=sheet_args,
                summary=summary,
                errors=[],
            )
        _audit(
            engine,
            EventType.IMPORT_UPLOADED,
            actor_name=actor(request, "web"),
            payload={"job_id": job_id, "filename": filename, "rows": summary},
        )
        return JSONResponse(job, status_code=201)

    @app.get("/imports")
    def list_imports(
        request: Request,
        limit: int = 50,
        offset: int = 0,
        status: str = "",
        kind: str = "",
    ) -> dict[str, Any]:
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        with _job_service(engine) as svc:
            items = svc.list(
                limit=max(1, min(limit, 200)),
                offset=max(0, offset),
                created_by=_scope_creator(principal, actor(request, "web")),
                status=status.strip(),
                kind=kind.strip(),
            )
            total = svc.count(
                created_by=_scope_creator(principal, actor(request, "web")),
                status=status.strip(),
                kind=kind.strip(),
            )
        return {
            "items": items,
            "total": total,
            "offset": max(0, offset),
            "limit": max(1, min(limit, 200)),
        }

    @app.get("/imports/{job_id}")
    def get_import(request: Request, job_id: str) -> dict[str, Any]:
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        with _job_service(engine) as svc:
            job = _job_or_404(svc, job_id)
        _ensure_job_access(principal, job)
        return job

    @app.post("/imports/{job_id}/advise")
    def advise_map(request: Request, job_id: str) -> Any:
        """AI 映射建议（只读顾问）：不写业务表，也不改上传文件。"""
        _require_csrf(request)
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        with _job_service(engine) as svc:
            job = _job_or_404(svc, job_id)
            _ensure_job_access(principal, job)
            if job["status"] != "pending_review":
                raise HTTPException(
                    409, f"import job is {job['status']}, not pending_review"
                )
            if job["kind"] != "import":
                raise HTTPException(409, "AI mapping advice is only for file imports")
            path = svc.file_path(job_id)
        if path is None or not path.is_file():
            raise HTTPException(409, "import file is missing")
        record, _summary, errors = _safe_parse(
            path, Path(engine.home), job["sheet_args"]
        )
        if errors or record is None:
            return JSONResponse(
                {
                    "code": "conflict",
                    "error": "import no longer valid",
                    "details": errors[:50],
                },
                status_code=409,
            )
        cfg = load_llm_config(config_path(Path(engine.home)))
        try:
            result = advise_import_mapping(record, cfg, LlmGateway(cfg))
        except LlmUnavailableError as exc:
            raise HTTPException(503, f"AI mapping advisor unavailable: {exc}") from exc
        except DataClassViolationError as exc:
            raise HTTPException(409, f"AI data policy rejected the request: {exc}") from exc
        _audit(
            engine,
            EventType.IMPORT_ADVISED,
            actor_name=actor(request, "web"),
            payload={
                "job_id": job_id,
                "endpoint": result.endpoint,
                "location": result.location,
                "data_class": result.data_class.name,
                "included_values": result.included_values,
            },
        )
        return {
            "job_id": job_id,
            "endpoint": result.endpoint,
            "location": result.location,
            "data_class": result.data_class.name,
            "included_values": result.included_values,
            "columns": [item.model_dump(mode="json") for item in result.advice.columns],
            "warnings": result.advice.warnings,
            "notes": result.advice.notes,
        }

    @app.get("/imports/{job_id}/preview")
    def preview_import(request: Request, job_id: str, limit: int = 20) -> dict[str, Any]:
        """返回提案的前 N 行（本地 D4 数据，仅授权用户/审核者可见）。"""
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        with _job_service(engine) as svc:
            job = _job_or_404(svc, job_id)
            _ensure_job_access(principal, job)
            path = svc.file_path(job_id)
        if job["kind"] != "import":
            payload = job.get("payload") or []
            return {
                "summary": job.get("summary") or {},
                "errors": [],
                "total": len(payload),
                "limit": max(1, min(limit, 50)),
                "rows": payload[: max(1, min(limit, 50))],
            }
        if path is None or not path.is_file():
            raise HTTPException(409, "import file is missing")
        record, summary, errors = _safe_parse(path, Path(engine.home), job["sheet_args"])
        if record is None:
            return {"summary": summary, "errors": errors, "rows": []}
        cap = max(1, min(limit, 50))
        return {
            "summary": summary,
            "errors": errors,
            "total": len(record.rows),
            "limit": cap,
            "rows": [row.model_dump(mode="json") for row in record.rows[:cap]],
        }

    @app.post("/imports/{job_id}/approve")
    def approve_import(  # noqa: C901 — 文件导入与编辑提案共用审核状态机
        request: Request,
        job_id: str,
        force_self_approval: bool = False,
    ) -> Any:
        _require_csrf(request)
        principal = require_permission(request, Permission.IMPORT_REVIEW)
        with _job_service(engine) as svc:
            job = _job_or_404(svc, job_id)
            if job["status"] != "pending_review":
                raise HTTPException(409, f"import job is {job['status']}, not pending_review")
            reviewer = principal.username if principal is not None else actor(request, "web")
            if (
                principal is not None
                and reviewer == job["created_by"]
                and not (principal.role is Role.ADMIN and force_self_approval)
            ):
                raise HTTPException(
                    409,
                    "submitter cannot approve their own proposal; "
                    "an admin may force self-approval",
                )
            role = _submitter_role(engine, job["created_by"])
            if job["kind"] == "import":
                path = svc.file_path(job_id)
                if path is None or not path.is_file():
                    raise HTTPException(409, "import file is missing")
                if hashlib.sha256(path.read_bytes()).hexdigest() != job["file_sha256"]:
                    raise HTTPException(409, "import file changed after upload")
                record, summary, errors = _safe_parse(
                    path, Path(engine.home), job["sheet_args"]
                )
                if errors or record is None:
                    return JSONResponse(
                        {
                            "code": "conflict",
                            "error": "import no longer valid",
                            "details": errors[:50],
                        },
                        status_code=409,
                    )
                if role is Role.USER:
                    denied = assert_rows_owned(
                        Path(engine.home), record.rows, job["created_by"]
                    )
                    if denied:
                        raise HTTPException(
                            409,
                            "target data is no longer owned by the submitter: "
                            + ", ".join(sorted(set(denied))[:10]),
                        )
                params: dict[str, Any] = {
                    "kind": "batch",
                    "rows": [row.model_dump(mode="json") for row in record.rows],
                }
            else:
                payload = job.get("payload") or []
                if not payload:
                    raise HTTPException(409, "proposal payload is empty")
                params = dict(payload[0])
                try:
                    record = parse_record(params)
                except ValueError as exc:
                    raise HTTPException(409, f"proposal no longer valid: {exc}") from exc
                if job.get("base_version"):
                    current = target_version(
                        Path(engine.home), job["target_type"], job["target_id"]
                    )
                    if current != job["base_version"]:
                        raise HTTPException(
                            409,
                            "target changed after the proposal was submitted; "
                            "ask the submitter to redo it",
                        )
                if role is Role.USER:
                    denied = assert_rows_owned(
                        Path(engine.home), [record], job["created_by"]
                    )
                    if denied:
                        raise HTTPException(
                            409,
                            "target data is no longer owned by the submitter: "
                            + ", ".join(sorted(set(denied))[:10]),
                        )
                summary = job.get("summary") or {}
            if role is not None:
                params = _inject_owner(params, job["created_by"])
            # 由 job_id 派生确定性 task_id：重复点击/并发审核落到同一个任务，
            # 避免同一提案写出两份数据。
            task_id = TaskId(
                hashlib.sha256(f"import:{job_id}".encode()).hexdigest()[:32]
            )
            try:
                tid = engine.submit(
                    TaskType.RECORD,
                    params,
                    f"web:{reviewer}",
                    task_id=task_id,
                )
            except (ValueError, NotImplementedError) as exc:
                raise HTTPException(400, f"cannot submit record task: {exc}") from exc
            updated = svc.mark_reviewed(
                job_id,
                status="submitted",
                reviewed_by=reviewer,
                task_id=str(tid),
            )
            if updated is None:
                raise HTTPException(409, "proposal was already reviewed")
        _audit(
            engine,
            EventType.IMPORT_APPROVED,
            actor_name=reviewer,
            payload={"job_id": job_id, "task_id": str(tid), "rows": summary},
        )
        return updated

    @app.post("/imports/{job_id}/reject")
    def reject_import(request: Request, job_id: str, note: str = "") -> dict[str, Any]:
        _require_csrf(request)
        principal = require_permission(request, Permission.IMPORT_REVIEW)
        reviewer = principal.username if principal is not None else actor(request, "web")
        with _job_service(engine) as svc:
            job = _job_or_404(svc, job_id)
            if job["status"] != "pending_review":
                raise HTTPException(409, f"import job is {job['status']}, not pending_review")
            updated = svc.mark_reviewed(
                job_id, status="rejected", reviewed_by=reviewer, note=note
            )
            if updated is None:
                raise HTTPException(409, "import job was already reviewed")
        _audit(
            engine,
            EventType.IMPORT_REJECTED,
            actor_name=reviewer,
            payload={"job_id": job_id, "note": note[:300]},
        )
        return updated

    @app.post("/imports/{job_id}/withdraw")
    def withdraw_import(request: Request, job_id: str) -> dict[str, Any]:
        _require_csrf(request)
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        with _job_service(engine) as svc:
            job = _job_or_404(svc, job_id)
            _ensure_job_access(principal, job)
            if job["created_by"] != actor(request, "web"):
                raise HTTPException(403, "only the submitter can withdraw")
            if job["status"] != "pending_review":
                raise HTTPException(409, f"import job is {job['status']}, not pending_review")
            updated = svc.mark_reviewed(
                job_id,
                status="withdrawn",
                reviewed_by=actor(request, "web"),
                note="withdrawn by submitter",
            )
            if updated is None:
                raise HTTPException(409, "import job was already reviewed")
        return updated
