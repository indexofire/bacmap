"""Deterministic regression and reporting helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bacmap.research import reporting
from bacmap.research.regression import fit_logistic, standardized_mean_difference
from bacmap.research.service import ResearchObjectService


def test_logistic_regression_positive_effect():
    rows = [[value] for value in range(-5, 15)]
    outcomes = [0, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    result = fit_logistic(rows, outcomes, ["dose"])
    assert result.n == 20
    assert result.events == 14
    assert result.converged
    assert result.coefficients[1] > 0
    assert result.odds_ratios[1] > 1
    assert result.ci_low[1] < result.odds_ratios[1] < result.ci_high[1]
    assert 0 <= result.p_values[1] <= 1


def test_logistic_regression_validation():
    with pytest.raises(ValueError, match="same length"):
        fit_logistic([[1.0]], [0, 1], ["x"])
    with pytest.raises(ValueError, match="0/1"):
        fit_logistic([[1.0], [2.0]], [0, 2], ["x"])
    with pytest.raises(ValueError, match="feature_names"):
        fit_logistic([[1.0], [2.0]], [0, 1], ["x", "y"])


def test_standardized_mean_difference():
    assert standardized_mean_difference([1, 2, 3], [1, 2, 3]) == 0.0
    assert standardized_mean_difference([10, 11, 12], [1, 2, 3]) > 1.0
    with pytest.raises(ValueError):
        standardized_mean_difference([], [1])
    # n<2 时 ddof=1 方差除零——必须显式报错而非漏出 NaN
    with pytest.raises(ValueError, match="two"):
        standardized_mean_difference([1], [1, 2])


def _study_with_objects(home: Path):
    svc = ResearchObjectService(home)
    study = svc.create_study("Does gene X associate with resistance?", "KPN", 2, "t")
    cohort = svc.create_cohort(
        study.study_id, [{"isolate_id": "I1", "run_id": "run-1"}], name="discovery", actor="t"
    )
    svc.freeze_cohort(cohort.cohort_id, "t")
    plan = svc.create_plan(study.study_id, cohort.cohort_id, {"gene": "x"}, "t")
    svc.freeze_plan(plan.plan_id, "t")
    claim = svc.create_claim(
        study.study_id,
        "association",
        "gene X is associated with resistance",
        "E2",
        {"run_id": "run-1"},
        "t",
    )
    svc.review_claim(claim.claim_id, "approve", "", "t")
    svc.record_experiment(plan.plan_id, "success", ["run-1"], {"n": 1}, actor="t")
    return study


def test_checklist_has_met_and_missing_items(tmp_path: Path):
    study = _study_with_objects(tmp_path)
    checklist = reporting.checklist_for_study(tmp_path, study.study_id)
    assert checklist.study_id == study.study_id
    assert checklist.met >= 1
    assert checklist.missing >= 1
    statuses = {item.status for item in checklist.items}
    assert {"met", "missing"} <= statuses


def test_submission_package_writes_manifest(tmp_path: Path):
    study = _study_with_objects(tmp_path)
    out = tmp_path / "package"
    package = reporting.build_submission_package(tmp_path, study.study_id, out)
    assert (out / "submission_manifest.json").is_file()
    assert (out / "strobe_checklist.json").is_file()
    assert (out / "strobe_checklist.md").is_file()
    payload = json.loads((out / "submission_manifest.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "bacmap.submission_package/1"
    assert package.study_id == study.study_id
    assert package.checklist.missing >= 1


def test_checklist_unknown_study(tmp_path: Path):
    with pytest.raises(ValueError, match="no such study"):
        reporting.checklist_for_study(tmp_path, "nope")
