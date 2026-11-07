"""Submission package history: build, list, load and zip versioned packages."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bacmap.research import reporting
from bacmap.research.checklist import ChecklistService
from bacmap.research.models import SubmissionPackageRecord
from bacmap.research.store import ResearchObjectStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResearchPackageService:
    """Versioned submission packages under ``research/packages/<study>/<package>``."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def build(
        self, study_id: str, *, actor: str = "web", label: str = ""
    ) -> SubmissionPackageRecord:
        with ResearchObjectStore(self.home) as store:
            try:
                store.get_study(study_id)
            except KeyError as exc:
                raise ValueError(f"no such study: {study_id}") from exc
        package_id = f"pkg-{uuid4().hex[:12]}"
        target = self.home / "research" / "packages" / study_id / package_id
        checklist_service = ChecklistService(self.home)
        checklist = checklist_service.merged(study_id)
        review = checklist_service.get_review(study_id)
        package = reporting.build_submission_package(
            self.home,
            study_id,
            target,
            checklist=checklist,
            checklist_review=(
                review.model_dump(mode="json") if review is not None else None
            ),
        )
        manifest = target / "submission_manifest.json"
        record = SubmissionPackageRecord(
            package_id=package_id,
            study_id=study_id,
            path=str(target),
            created_at=package.generated_at or datetime.now(UTC).isoformat(),
            created_by=actor,
            label=label,
            manifest_sha256=_sha256(manifest),
            n_files=len(package.files),
            blockers=list(package.blockers),
        )
        with ResearchObjectStore(self.home) as store:
            return store.create_package(record)

    def list_packages(
        self, study_id: str, limit: int = 50
    ) -> list[SubmissionPackageRecord]:
        with ResearchObjectStore(self.home) as store:
            return store.list_packages(study_id, limit=limit)

    def get_package(self, package_id: str) -> SubmissionPackageRecord:
        with ResearchObjectStore(self.home) as store:
            try:
                return store.get_package(package_id)
            except KeyError as exc:
                raise ValueError(f"no such submission package: {package_id}") from exc

    def load_manifest(self, record: SubmissionPackageRecord) -> dict[str, Any]:
        path = Path(record.path) / "submission_manifest.json"
        if not path.is_file():
            raise ValueError(f"package manifest missing: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"invalid package manifest: {path}")
        return raw

    def zip_path(self, record: SubmissionPackageRecord) -> Path:
        target = Path(record.path)
        archive = target.with_suffix(".zip")
        if not archive.is_file():
            if not target.is_dir():
                raise ValueError(f"package directory missing: {target}")
            shutil.make_archive(str(target), "zip", root_dir=target)
        return archive
