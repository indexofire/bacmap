"""IPTW and Kaplan-Meier/log-rank deterministic statistics."""

from __future__ import annotations

import pytest

from bacmap.research.advanced_stats import fit_iptw, fit_match, kaplan_meier


def _iptw_data():
    treatment = [1 if i % 2 == 0 else 0 for i in range(40)]
    age = [20 + (i % 20) for i in range(40)]
    lineage = [i % 3 for i in range(40)]
    outcome = [
        1 if (t == 1 and i % 4 != 0) or (t == 0 and age[i] > 32) else 0
        for i, t in enumerate(treatment)
    ]
    return treatment, outcome, [[age[i], lineage[i]] for i in range(40)], ["age", "lineage"]


def test_iptw_effect_and_balance():
    treatment, outcome, covariates, names = _iptw_data()
    result = fit_iptw(treatment, outcome, covariates, names, weight_type="ate")
    assert result.n == 40
    assert result.treated == 20
    assert result.control == 20
    assert result.effect > 0
    assert result.ci_low < result.effect < result.ci_high
    age = next(row for row in result.balance if row.covariate == "age")
    assert age.smd_after < age.smd_before
    assert 0 < result.ps_min < result.ps_max < 1


def test_iptw_validation():
    with pytest.raises(ValueError, match="same length"):
        fit_iptw([1], [0, 1], [[1.0]], ["x"])
    with pytest.raises(ValueError, match="0/1"):
        fit_iptw([0, 2], [0, 1], [[1.0], [2.0]], ["x"])
    with pytest.raises(ValueError, match="two treated"):
        fit_iptw([1, 1], [0, 1], [[1.0], [2.0]], ["x"])


def test_kaplan_meier_and_logrank():
    times = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 2
    events = [1, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 0, 1, 0, 0]
    groups = ["A"] * 10 + ["B"] * 10
    result = kaplan_meier(times, events, groups)
    assert len(result.groups) == 2
    assert result.groups[0].n == 10
    assert result.groups[0].median is not None
    assert result.logrank_chi2 >= 0
    assert 0 <= result.p_value <= 1


def test_kaplan_meier_requires_two_groups():
    with pytest.raises(ValueError, match="exactly two groups"):
        kaplan_meier([1, 2], [1, 0], ["A", "A"])
    with pytest.raises(ValueError, match="0/1"):
        kaplan_meier([1, 2], [1, 2], ["A", "B"])


def test_match_effect_and_balance():
    treatment = []
    outcome = []
    age = []
    lineage = []
    for i in range(60):
        a = 20 + (i % 40)
        t = 1 if (a > 40 and i % 5 != 0) or (a <= 40 and i % 7 == 0) else 0
        y = 1 if (t == 1 and i % 3 != 0) or (a > 50 and i % 2 == 0) else 0
        treatment.append(t)
        outcome.append(y)
        age.append(float(a))
        lineage.append(float(i % 3))
    result = fit_match(
        treatment,
        outcome,
        [[age[i], lineage[i]] for i in range(60)],
        ["age", "lineage"],
        caliper=0.2,
    )
    assert result.matched_pairs >= 2
    age_row = next(row for row in result.balance if row.covariate == "age")
    assert age_row.smd_after < age_row.smd_before
    assert result.ci_low < result.effect < result.ci_high


def test_match_caliper_too_small():
    treatment = [1, 1, 0, 0]
    outcome = [1, 0, 0, 1]
    covariates = [[10.0], [20.0], [30.0], [40.0]]
    with pytest.raises(ValueError, match="fewer than 2 matched pairs"):
        fit_match(treatment, outcome, covariates, ["x"], caliper=0.0001)
