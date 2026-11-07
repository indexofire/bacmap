"""Persisted deterministic analysis results linked to a Study."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bacmap.research.models import AnalysisRecord
from bacmap.research.store import ResearchObjectStore


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class ResearchAnalysisService:
    """Save/list/get analysis results and link them into the evidence graph."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def save(
        self,
        study_id: str,
        analysis_type: str,
        result: dict[str, Any],
        *,
        title: str = "",
        params: dict[str, Any] | None = None,
        input_paths: list[str] | None = None,
        note: str = "",
        actor: str = "web",
    ) -> AnalysisRecord:
        with ResearchObjectStore(self.home) as store:
            try:
                store.get_study(study_id)
            except KeyError as exc:
                raise ValueError(f"no such study: {study_id}") from exc
        paths = [str(path) for path in (input_paths or [])]
        hashes: dict[str, str] = {}
        for raw in paths:
            path = Path(raw).expanduser()
            if path.is_file():
                hashes[raw] = _sha256_file(path)
        record = AnalysisRecord(
            analysis_id=f"ana-{uuid4().hex[:12]}",
            study_id=study_id,
            analysis_type=analysis_type,
            title=title,
            input_paths=paths,
            input_sha256=hashes,
            params=dict(params or {}),
            result=dict(result),
            result_sha256=_sha256_text(_canonical(result)),
            note=note,
            created_by=actor,
            created_at=datetime.now(UTC).isoformat(),
        )
        with ResearchObjectStore(self.home) as store:
            return store.create_analysis(record)

    def list_analyses(
        self,
        study_id: str,
        analysis_type: str | None = None,
        limit: int = 100,
    ) -> list[AnalysisRecord]:
        with ResearchObjectStore(self.home) as store:
            return store.list_analyses(study_id, analysis_type, limit)

    def get_analysis(self, analysis_id: str) -> AnalysisRecord:
        with ResearchObjectStore(self.home) as store:
            try:
                return store.get_analysis(analysis_id)
            except KeyError as exc:
                raise ValueError(f"no such analysis: {analysis_id}") from exc
