"""Checklist edits and sign-off."""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.research.checklist import ChecklistService
from bacmap.research.models import ChecklistOverride, ChecklistReviewStatus
from bacmap.research.packages import ResearchPackageService
from bacmap.research.service import ResearchObjectService


@pytest.fixture
def study(tmp_path: Path):
    svc = ResearchObjectService(tmp_path)
    return svc.create_study("Checklist question", "KPN", 2, "t"), tmp_path


def _overrides(service: ChecklistService, study_id: str, status: str):
    return [
        ChecklistOverride(item_id=item.item_id, status=status)
        for item in service.base(study_id).items
    ]


def test_save_and_merge(study):
    item, home = study
    svc = ChecklistService(home)
    overrides = _overrides(svc, item.study_id, "met")
    review = svc.save(item.study_id, overrides, actor="web", note="draft")
    assert review.status is ChecklistReviewStatus.DRAFT
    merged = svc.merged(item.study_id)
    assert merged.missing == 0
    assert merged.met == len(merged.items)


def test_sign_requires_no_missing(study):
    item, home = study
    svc = ChecklistService(home)
    with pytest.raises(ValueError, match="missing checklist items"):
        svc.sign(item.study_id, [], actor="web")
    review = svc.sign(
        item.study_id,
        _overrides(svc, item.study_id, "partial"),
        actor="reviewer",
        note="signed",
    )
    assert review.status is ChecklistReviewStatus.SIGNED
    assert review.reviewed_by == "reviewer"


def test_reset(study):
    item, home = study
    svc = ChecklistService(home)
    svc.save(item.study_id, _overrides(svc, item.study_id, "met"), actor="web")
    assert svc.get_review(item.study_id) is not None
    svc.reset(item.study_id, actor="web")
    assert svc.get_review(item.study_id) is None


def test_package_carries_signed_checklist(study):
    item, home = study
    svc = ChecklistService(home)
    svc.sign(
        item.study_id,
        _overrides(svc, item.study_id, "partial"),
        actor="reviewer",
        note="signed",
    )
    record = ResearchPackageService(home).build(item.study_id, actor="web")
    manifest = ResearchPackageService(home).load_manifest(record)
    assert manifest["checklist_review"]["status"] == "signed"
    assert manifest["checklist"]["missing"] == 0
