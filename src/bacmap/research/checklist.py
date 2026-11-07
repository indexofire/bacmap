"""Human edits and sign-off for the deterministic STROBE checklist."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bacmap.research import reporting
from bacmap.research.models import (
    ChecklistOverride,
    ChecklistReview,
    ChecklistReviewStatus,
)
from bacmap.research.store import ResearchObjectStore


def _apply(
    reporting_checklist: reporting.Checklist, overrides: list[ChecklistOverride]
) -> reporting.Checklist:
    by_id = {item.item_id: item for item in overrides}
    items: list[reporting.ChecklistItem] = []
    for item in reporting_checklist.items:
        override = by_id.get(item.item_id)
        if override is None:
            items.append(item)
            continue
        items.append(
            item.model_copy(
                update={
                    "status": override.status or item.status,
                    "evidence": item.evidence if override.evidence is None else override.evidence,
                    "note": item.note if override.note is None else override.note,
                }
            )
        )
    met = sum(1 for item in items if item.status == "met")
    partial = sum(1 for item in items if item.status == "partial")
    missing = sum(1 for item in items if item.status == "missing")
    return reporting.Checklist(
        study_id=reporting_checklist.study_id,
        guideline=reporting_checklist.guideline,
        items=items,
        met=met,
        partial=partial,
        missing=missing,
    )


class ChecklistService:
    """Load the base checklist, apply edits, save drafts and sign off."""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)

    def base(self, study_id: str) -> reporting.Checklist:
        return reporting.checklist_for_study(self.home, study_id)

    def get_review(self, study_id: str) -> ChecklistReview | None:
        with ResearchObjectStore(self.home) as store:
            return store.get_checklist_review(study_id)

    def merged(self, study_id: str) -> reporting.Checklist:
        base = self.base(study_id)
        review = self.get_review(study_id)
        return base if review is None else _apply(base, review.overrides)

    def save(
        self,
        study_id: str,
        overrides: list[ChecklistOverride],
        *,
        actor: str,
        note: str = "",
    ) -> ChecklistReview:
        base = self.base(study_id)
        known = {item.item_id for item in base.items}
        cleaned = [item for item in overrides if item.item_id in known]
        review = ChecklistReview(
            study_id=study_id,
            overrides=cleaned,
            status=ChecklistReviewStatus.DRAFT,
            note=note,
            updated_at=datetime.now(UTC).isoformat(),
        )
        with ResearchObjectStore(self.home) as store:
            saved = store.save_checklist_review(review)
            store.ensure_edge(
                "checklist", study_id, "CHECKLIST_OF", "study", study_id,
                f"checklist status={saved.status.value}", actor,
            )
            return saved

    def sign(
        self,
        study_id: str,
        overrides: list[ChecklistOverride],
        *,
        actor: str,
        note: str = "",
    ) -> ChecklistReview:
        base = self.base(study_id)
        known = {item.item_id for item in base.items}
        cleaned = [item for item in overrides if item.item_id in known]
        merged = _apply(base, cleaned)
        missing = [item.item_id for item in merged.items if item.status == "missing"]
        if missing:
            raise ValueError(
                "cannot sign with missing checklist items: " + ", ".join(missing)
            )
        now = datetime.now(UTC).isoformat()
        review = ChecklistReview(
            study_id=study_id,
            overrides=cleaned,
            status=ChecklistReviewStatus.SIGNED,
            reviewed_by=actor,
            reviewed_at=now,
            note=note,
            updated_at=now,
        )
        with ResearchObjectStore(self.home) as store:
            saved = store.save_checklist_review(review)
            store.ensure_edge(
                "checklist", study_id, "CHECKLIST_OF", "study", study_id,
                f"checklist status={saved.status.value}", actor,
            )
            return saved

    def reset(self, study_id: str, *, actor: str = "web") -> None:
        with ResearchObjectStore(self.home) as store:
            store.delete_checklist_review(study_id, actor=actor)
