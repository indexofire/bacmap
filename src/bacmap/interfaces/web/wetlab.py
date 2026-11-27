"""湿实验数据编辑入口（v1.10.55，P3）。

所有写入仍只提交 ``record`` 任务（ADR-07），本模块只做权限、目标存在性与
载荷形状校验，不直接调用 store。Web 详情页用它完成 specimen / isolate /
library 元数据与化验结果的新增、替换和删除。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bacmap.interfaces.web.auth import principal_of, verify_csrf
from bacmap.interfaces.web.rbac import Permission, require_permission
from bacmap.store.import_jobs import ImportJobService
from bacmap.store.strain_metadata import METADATA_FIELDS
from bacmap.store.users import Role
from bacmap.store.wetlab_targets import target_exists, target_owner, target_version
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.records import (
    IsolateCreate,
    LabResultDelete,
    LabResultRecord,
    LabResultUpdate,
    LibraryMetadataDelete,
    LibraryMetadataRecord,
    MetadataDelete,
    MetadataRecord,
    SpecimenAssign,
    SpecimenCreate,
    SpecimenMetadataDelete,
    SpecimenMetadataRecord,
    parse_record,
)
from bacmap.tasks.spec import TaskType

Scalar = str | int | float | bool | None
_MAX_KEYS = 200
_MAX_VALUE_CHARS = 4000


def _clean_map(value: dict[str, Scalar]) -> dict[str, Scalar]:
    if len(value) > _MAX_KEYS:
        raise ValueError(f"too many fields (max {_MAX_KEYS})")
    out: dict[str, Scalar] = {}
    for key, item in value.items():
        text = str(key).strip()
        if not text or len(text) > 100:
            raise ValueError("field names must be 1-100 characters")
        if isinstance(item, str) and len(item) > _MAX_VALUE_CHARS:
            raise ValueError(f"value for {text!r} is too long")
        out[text] = item
    return out


class DataBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Scalar] = Field(default_factory=dict)
    replace: bool = True

    @field_validator("data")
    @classmethod
    def _validate_data(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        return _clean_map(value)


class IsolateDataBody(DataBody):
    sample_id: str = Field(default="", max_length=128)


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isolates: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.isolates and not self.datasets:
            raise ValueError("give at least one isolate or dataset to assign")


def _audit_proposal(
    engine: DbosTaskEngine, *, actor_name: str, payload: dict[str, Any]
) -> None:
    try:
        from bacmap.tasks.events import EventLog, EventType
        from bacmap.tools.spec import DataClass

        EventLog(engine.db).append(
            EventType.WETLAB_PROPOSED,
            actor=actor_name,
            payload=payload,
            data_class=DataClass.D2,
        )
    except Exception:  # 审计旁路不阻断提案
        import logging

        logging.getLogger(__name__).warning("wetlab proposal audit failed", exc_info=True)


class ProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any]
    base_version: str = ""


# 允许普通用户提案的 record 种类（新增由审核人执行）。
_PROPOSAL_KINDS = {
    "specimen_metadata",
    "specimen_metadata_delete",
    "metadata",
    "metadata_delete",
    "library_metadata",
    "library_metadata_delete",
    "lab_result",
    "lab_result_update",
    "lab_result_delete",
    "specimen_assign",
    "specimen_create",
    "isolate_create",
}


def _row_target(row: Any) -> tuple[str, str] | None:
    """record 行 → (owner 目标类型, 目标 ID)。"""
    if isinstance(row, MetadataRecord):
        return ("isolate", row.strain_id)
    if isinstance(row, MetadataDelete):
        return ("isolate", row.strain_id)
    if isinstance(row, SpecimenMetadataRecord | SpecimenMetadataDelete):
        return ("specimen", row.specimen_id)
    if isinstance(row, LibraryMetadataRecord | LibraryMetadataDelete):
        return ("library", row.library_id)
    if isinstance(row, LabResultRecord):
        subject = row.subject_id or row.strain_id
        return (
            ("specimen" if row.subject_type == "specimen" else "isolate"),
            subject,
        )
    if isinstance(row, LabResultUpdate | LabResultDelete):
        return ("lab", row.result_id)
    if isinstance(row, SpecimenAssign):
        return ("specimen", row.specimen_id)
    if isinstance(row, SpecimenCreate):
        return ("specimen", row.specimen_id)
    if isinstance(row, IsolateCreate):
        if row.specimen_id:
            return ("specimen", row.specimen_id)
        return ("isolate", row.isolate_id)
    return None


def assert_rows_owned(home: Any, rows: list[Any], username: str) -> list[str]:
    """返回 rows 中不属于 username 的目标 ID（无主数据视为可用）。"""
    denied: list[str] = []

    def _check(target_type: str, target_id: str) -> None:
        owner = target_owner(home, target_type, target_id)
        if owner and owner != username:
            denied.append(target_id)
            return
        if target_type == "specimen":
            from bacmap.store.specimens import SpecimenService

            with SpecimenService(Path(home) / "data" / "bacmap.sqlite") as store:
                children = store.isolates(target_id)
            if any(
                str(child.get("owner_user_id") or "")
                and str(child.get("owner_user_id")) != username
                for child in children
            ):
                denied.append(target_id)

    for row in rows:
        if isinstance(row, SpecimenAssign):
            _check("specimen", row.specimen_id)
            for isolate_id in row.isolates:
                _check("isolate", isolate_id)
            for dataset_id in row.datasets:
                _check("library", dataset_id)
            continue
        target = _row_target(row)
        if target is not None:
            _check(target[0], target[1])
    return denied


def _proposal_target(record: Any) -> tuple[str, str, str, str, str, str]:
    """返回 (target_type, target_id, base_type, base_id, owner_type, owner_id)。"""
    if isinstance(record, SpecimenMetadataRecord | SpecimenMetadataDelete):
        return (
            "specimen",
            record.specimen_id,
            "specimen",
            record.specimen_id,
            "specimen",
            record.specimen_id,
        )
    if isinstance(record, MetadataRecord | MetadataDelete):
        return (
            "isolate",
            record.strain_id,
            "isolate",
            record.strain_id,
            "isolate",
            record.strain_id,
        )
    if isinstance(record, LibraryMetadataRecord | LibraryMetadataDelete):
        return (
            "library",
            record.library_id,
            "library",
            record.library_id,
            "library",
            record.library_id,
        )
    if isinstance(record, LabResultUpdate | LabResultDelete):
        return (
            "lab",
            record.result_id,
            "lab",
            record.result_id,
            "lab",
            record.result_id,
        )
    if isinstance(record, LabResultRecord):
        subject_type = "specimen" if record.subject_type == "specimen" else "isolate"
        subject_id = record.subject_id or record.strain_id
        return ("lab", "", "", "", subject_type, subject_id)
    if isinstance(record, SpecimenAssign):
        return (
            "specimen",
            record.specimen_id,
            "specimen",
            record.specimen_id,
            "specimen",
            record.specimen_id,
        )
    if isinstance(record, SpecimenCreate):
        return (
            "specimen",
            record.specimen_id,
            "",
            "",
            "specimen",
            record.specimen_id,
        )
    if isinstance(record, IsolateCreate):
        return (
            "isolate",
            record.isolate_id,
            "",
            "",
            "specimen" if record.specimen_id else "isolate",
            record.specimen_id or record.isolate_id,
        )
    return ("", "", "", "", "", "")


def _job_service(engine: DbosTaskEngine) -> ImportJobService:
    return ImportJobService(Path(engine.home) / "data" / "bacmap.sqlite")


def _assert_proposal_access(home: Any, request: Request, record: Any) -> None:
    principal = principal_of(request)
    if principal is None or principal.role is not Role.USER:
        return
    if assert_rows_owned(home, [record], principal.username):
        raise HTTPException(404, "no such target")


class SpecimenCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specimen_id: str = Field(min_length=1, max_length=128)
    origin: str = Field(default="manual", max_length=64)
    note: str = Field(default="", max_length=2000)


class IsolateCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isolate_id: str = Field(min_length=1, max_length=128)
    specimen_id: str = Field(default="", max_length=128)
    lineage_id: str | None = Field(default=None, max_length=128)
    passage: int | None = Field(default=None, ge=0)


class LabAddBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strain_id: str = Field(default="", max_length=128)
    subject_type: Literal["isolate", "specimen"] = "isolate"
    subject_id: str = Field(default="", max_length=128)
    category: str = Field(min_length=1, max_length=64)
    test_name: str = Field(min_length=1, max_length=128)
    result: str = Field(min_length=1, max_length=256)
    unit: str = ""
    method: str = ""
    interpretation: str = ""
    standard: str = ""
    tested_date: str = ""
    tested_by: str = ""
    lab: str = ""
    notes: str = ""
    extra: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _validate_extra(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        return _clean_map(value)


class LabUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=64)
    test_name: str | None = Field(default=None, max_length=128)
    result: str | None = Field(default=None, max_length=256)
    unit: str | None = None
    method: str | None = None
    interpretation: str | None = None
    standard: str | None = None
    tested_date: str | None = None
    tested_by: str | None = None
    lab: str | None = None
    notes: str | None = None
    subject_type: Literal["isolate", "specimen"] | None = None
    subject_id: str | None = None
    extra: dict[str, Scalar] | None = None

    @field_validator("extra")
    @classmethod
    def _validate_extra(cls, value: dict[str, Scalar] | None) -> dict[str, Scalar] | None:
        return _clean_map(value) if value is not None else None


def _require_csrf(request: Request) -> None:
    if not verify_csrf(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(403, "CSRF check failed")


def _db(engine: DbosTaskEngine) -> Any:
    return engine.home / "data" / "bacmap.sqlite"


def _ensure_specimen(engine: DbosTaskEngine, specimen_id: str) -> None:
    from bacmap.store.specimens import SpecimenService

    with SpecimenService(_db(engine)) as store:
        if store.get(specimen_id) is None:
            raise HTTPException(404, f"no such specimen: {specimen_id}")


def _ensure_isolate(engine: DbosTaskEngine, isolate_id: str) -> None:
    from bacmap.store.isolates import IsolateService

    with IsolateService(_db(engine)) as store:
        if store.get(isolate_id) is None:
            raise HTTPException(404, f"no such isolate: {isolate_id}")


def _ensure_library(engine: DbosTaskEngine, library_id: str) -> None:
    from bacmap.store.catalog import library_exists

    if not library_exists(engine.home, library_id):
        raise HTTPException(404, f"no such library: {library_id}")


def _ensure_lab_result(engine: DbosTaskEngine, result_id: str) -> None:
    from bacmap.store.lab_results import LabResultService

    with LabResultService(_db(engine)) as store:
        if store.get_by_id(result_id) is None:
            raise HTTPException(404, f"no such lab result: {result_id}")


def _submit(
    engine: DbosTaskEngine, request: Request, params: dict[str, Any]
) -> dict[str, Any]:
    principal = principal_of(request)
    actor_name = f"web:{principal.username}" if principal is not None else "web"
    try:
        tid = engine.submit(TaskType.RECORD, params, actor_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "task_id": str(tid),
        "kind": params["kind"],
        "task": engine.get_task(tid),
    }


def build_wetlab_routes(app: APIRouter, engine: DbosTaskEngine) -> None:  # noqa: C901 — 路由族内聚
    @app.post("/wetlab/proposals")
    def create_wetlab_proposal(
        request: Request, body: ProposalBody
    ) -> dict[str, Any]:
        """普通用户提交修改/删除提案；审核通过后由审核人提交 record 任务。"""
        _require_csrf(request)
        principal = require_permission(request, Permission.IMPORT_SUBMIT)
        try:
            record = parse_record(body.params)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if record.kind not in _PROPOSAL_KINDS:
            raise HTTPException(400, f"record kind {record.kind!r} is not proposable")
        _assert_proposal_access(Path(engine.home), request, record)
        target_type, target_id, base_type, base_id, owner_type, owner_id = (
            _proposal_target(record)
        )
        if base_id and not target_exists(Path(engine.home), base_type, base_id):
            raise HTTPException(404, f"no such {base_type}: {base_id}")
        if isinstance(record, LabResultRecord) and not target_exists(
            Path(engine.home), owner_type, owner_id
        ):
            raise HTTPException(404, f"no such {owner_type}: {owner_id}")
        current = (
            target_version(Path(engine.home), base_type, base_id)
            if base_id
            else ""
        )
        if body.base_version and body.base_version != current:
            raise HTTPException(
                409, "target changed since the editor was opened; reload and retry"
            )
        params = dict(body.params)
        operation = str(params.get("kind") or "")
        with _job_service(engine) as service:
            pending = [
                item
                for item in service.pending_for_target(
                    target_type or owner_type, target_id or owner_id
                )
                if str((item.get("summary") or {}).get("operation") or "")
                == operation
            ]
        if pending and operation != "lab_result":
            raise HTTPException(
                409,
                "a pending proposal already exists for this target: "
                + pending[0]["job_id"],
            )
        params.pop("owner_user_id", None)
        created_by = principal.username if principal is not None else "web"
        job_id = "wet_" + uuid.uuid4().hex[:16]
        summary = {
            "operation": str(params.get("kind") or ""),
            "target_type": target_type or owner_type,
            "target_id": target_id or owner_id,
            "owner_target_type": owner_type,
            "owner_target_id": owner_id,
            "fields": sorted(
                key
                for key in params
                if key
                not in {"kind", "strain_id", "specimen_id", "library_id", "result_id"}
            ),
            "base_version": current,
        }
        with _job_service(engine) as service:
            job = service.create(
                job_id=job_id,
                filename=f"{target_type or owner_type}:{target_id or owner_id}",
                file_sha256="",
                file_path=None,
                created_by=created_by,
                sheet_args={},
                summary=summary,
                errors=[],
                kind="edit",
                payload=[params],
                target_type=target_type or owner_type,
                target_id=target_id or owner_id,
                base_version=current,
            )
        _audit_proposal(
            engine,
            actor_name=created_by,
            payload={"job_id": job_id, "summary": summary},
        )
        return job

    @app.post("/wetlab/specimens")
    def create_specimen(
        request: Request, body: SpecimenCreateBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        return _submit(
            engine,
            request,
            {
                "kind": "specimen_create",
                "specimen_id": body.specimen_id,
                "origin": body.origin,
                "note": body.note,
            },
        )

    @app.post("/wetlab/isolates")
    def create_isolate(
        request: Request, body: IsolateCreateBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        if body.specimen_id:
            _ensure_specimen(engine, body.specimen_id)
        return _submit(
            engine,
            request,
            {
                "kind": "isolate_create",
                "isolate_id": body.isolate_id,
                "specimen_id": body.specimen_id,
                "lineage_id": body.lineage_id,
                "passage": body.passage,
            },
        )

    @app.post("/wetlab/specimens/{specimen_id}/metadata")
    def save_specimen_metadata(
        request: Request, specimen_id: str, body: DataBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_specimen(engine, specimen_id)
        return _submit(
            engine,
            request,
            {
                "kind": "specimen_metadata",
                "specimen_id": specimen_id,
                "data": body.data,
                "replace": body.replace,
            },
        )

    @app.post("/wetlab/specimens/{specimen_id}/metadata/delete")
    def delete_specimen_metadata(request: Request, specimen_id: str) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_specimen(engine, specimen_id)
        return _submit(
            engine,
            request,
            {"kind": "specimen_metadata_delete", "specimen_id": specimen_id},
        )

    @app.post("/wetlab/isolates/{isolate_id}/metadata")
    def save_isolate_metadata(
        request: Request, isolate_id: str, body: IsolateDataBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_isolate(engine, isolate_id)
        data = dict(body.data)
        sample_id = body.sample_id.strip() or str(data.pop("sample_id", "") or "")
        fields = {key: value for key, value in data.items() if key in METADATA_FIELDS}
        extra = {
            key: value
            for key, value in data.items()
            if key not in METADATA_FIELDS
            and key not in {"strain_id", "sample_id", "extra", "created_at", "updated_at"}
        }
        return _submit(
            engine,
            request,
            {
                "kind": "metadata",
                "strain_id": isolate_id,
                "sample_id": sample_id,
                "fields": fields,
                "extra": extra,
                "replace": body.replace,
            },
        )

    @app.post("/wetlab/isolates/{isolate_id}/metadata/delete")
    def delete_isolate_metadata(request: Request, isolate_id: str) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_isolate(engine, isolate_id)
        return _submit(
            engine, request, {"kind": "metadata_delete", "strain_id": isolate_id}
        )

    @app.post("/wetlab/libraries/{library_id}/metadata")
    def save_library_metadata(
        request: Request, library_id: str, body: DataBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_library(engine, library_id)
        return _submit(
            engine,
            request,
            {
                "kind": "library_metadata",
                "library_id": library_id,
                "data": body.data,
                "replace": body.replace,
            },
        )

    @app.post("/wetlab/libraries/{library_id}/metadata/delete")
    def delete_library_metadata(request: Request, library_id: str) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_library(engine, library_id)
        return _submit(
            engine,
            request,
            {"kind": "library_metadata_delete", "library_id": library_id},
        )

    @app.post("/wetlab/specimens/{specimen_id}/assign")
    def assign_specimen(
        request: Request, specimen_id: str, body: AssignBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.SPECIMEN_WRITE)
        _ensure_specimen(engine, specimen_id)
        return _submit(
            engine,
            request,
            {
                "kind": "specimen_assign",
                "specimen_id": specimen_id,
                "isolates": body.isolates,
                "datasets": body.datasets,
            },
        )

    @app.post("/wetlab/lab")
    def add_lab_result(request: Request, body: LabAddBody) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        subject_id = body.subject_id.strip() or body.strain_id.strip()
        if body.subject_type == "specimen":
            _ensure_specimen(engine, subject_id)
        else:
            _ensure_isolate(engine, subject_id)
        return _submit(
            engine,
            request,
            {
                "kind": "lab_result",
                "strain_id": body.strain_id.strip() or subject_id,
                "subject_type": body.subject_type,
                "subject_id": subject_id,
                "category": body.category,
                "test_name": body.test_name,
                "result": body.result,
                "unit": body.unit,
                "method": body.method,
                "interpretation": body.interpretation,
                "standard": body.standard,
                "tested_date": body.tested_date,
                "tested_by": body.tested_by,
                "lab": body.lab,
                "notes": body.notes,
                "extra": body.extra,
            },
        )

    @app.post("/wetlab/lab/{result_id}")
    def update_lab_result(
        request: Request, result_id: str, body: LabUpdateBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_lab_result(engine, result_id)
        fields = {
            key: value
            for key, value in body.model_dump(exclude_unset=True).items()
            if value is not None
        }
        if not fields:
            raise HTTPException(400, "no fields to update")
        return _submit(
            engine,
            request,
            {"kind": "lab_result_update", "result_id": result_id, **fields},
        )

    @app.post("/wetlab/lab/{result_id}/delete")
    def delete_lab_result(request: Request, result_id: str) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.RECORD_WRITE)
        _ensure_lab_result(engine, result_id)
        return _submit(
            engine,
            request,
            {"kind": "lab_result_delete", "result_id": result_id},
        )
