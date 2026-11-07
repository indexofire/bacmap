"""Advanced deterministic statistics: IPTW and Kaplan–Meier/log-rank (two groups)."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from bacmap.research.regression import fit_logistic

WeightType = Literal["ate", "att"]


class BalanceRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    covariate: str
    smd_before: float
    smd_after: float


class IptwResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int
    treated: int
    control: int
    weight_type: WeightType
    effect: float
    ci_low: float
    ci_high: float
    ps_min: float
    ps_max: float
    max_weight: float
    balance: list[BalanceRow]
    warnings: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int
    treated: int
    control: int
    matched_pairs: int
    unmatched_treated: int
    caliper: float
    effect: float
    ci_low: float
    ci_high: float
    balance: list[BalanceRow]
    warnings: list[str] = Field(default_factory=list)


class SurvivalPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    time: float
    survival: float
    at_risk: int
    events: int


class SurvivalCurve(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    group: str
    n: int
    events: int
    median: float | None
    points: list[SurvivalPoint]


class SurvivalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    groups: list[SurvivalCurve]
    logrank_chi2: float
    p_value: float
    warnings: list[str] = Field(default_factory=list)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -35.0, 35.0)))


def _smd(
    treated: np.ndarray,
    control: np.ndarray,
    weights_t: np.ndarray | None = None,
    weights_c: np.ndarray | None = None,
) -> float:
    if weights_t is None:
        weights_t = np.ones_like(treated)
    if weights_c is None:
        weights_c = np.ones_like(control)

    def mean(values: np.ndarray, weights: np.ndarray) -> float:
        return float(np.sum(values * weights) / np.sum(weights))

    def var(values: np.ndarray, weights: np.ndarray) -> float:
        mu = mean(values, weights)
        return float(np.sum(weights * (values - mu) ** 2) / np.sum(weights))

    pooled = math.sqrt((var(treated, weights_t) + var(control, weights_c)) / 2.0)
    if pooled == 0:
        return 0.0 if mean(treated, weights_t) == mean(control, weights_c) else float("inf")
    return abs(mean(treated, weights_t) - mean(control, weights_c)) / pooled


def fit_propensity(
    treatment: list[int], covariates: list[list[float]], names: list[str]
) -> np.ndarray:
    """Logistic propensity scores for a binary treatment."""
    model = fit_logistic(covariates, treatment, names)
    beta = np.asarray(model.coefficients, dtype=float)
    x = np.asarray(covariates, dtype=float)
    return np.clip(_sigmoid(beta[0] + x @ beta[1:]), 1e-6, 1 - 1e-6)


def fit_iptw(
    treatment: list[int],
    outcome: list[int],
    covariates: list[list[float]],
    names: list[str],
    *,
    weight_type: WeightType = "ate",
) -> IptwResult:
    """Propensity-score weighting for a binary treatment and binary outcome."""
    if len(treatment) != len(outcome) or len(treatment) != len(covariates):
        raise ValueError("treatment, outcome and covariates must have the same length")
    if not treatment:
        raise ValueError("at least one row is required")
    if len(names) != len(covariates[0]):
        raise ValueError("names must match the covariate columns")
    t = np.asarray(treatment, dtype=float)
    y = np.asarray(outcome, dtype=float)
    x = np.asarray(covariates, dtype=float)
    if not np.isin(t, [0.0, 1.0]).all() or not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("treatment and outcome must be 0/1")
    if int(np.sum(t)) < 2 or int(np.sum(1 - t)) < 2:
        raise ValueError("need at least two treated and two control rows")

    ps = fit_propensity(treatment, covariates, names)
    if weight_type == "ate":
        weights = np.where(t == 1, 1.0 / ps, 1.0 / (1.0 - ps))
    else:
        weights = np.where(t == 1, 1.0, ps / (1.0 - ps))

    def weighted_mean(values: np.ndarray, mask: np.ndarray) -> float:
        return float(np.sum(values[mask] * weights[mask]) / np.sum(weights[mask]))

    def weighted_var(values: np.ndarray, mask: np.ndarray) -> float:
        mu = weighted_mean(values, mask)
        return float(np.sum(weights[mask] * (values[mask] - mu) ** 2) / np.sum(weights[mask]))

    treated = t == 1
    control = t == 0
    mu_t = weighted_mean(y, treated)
    mu_c = weighted_mean(y, control)
    effect = mu_t - mu_c
    n_eff_t = float(np.sum(weights[treated]) ** 2 / np.sum(weights[treated] ** 2))
    n_eff_c = float(np.sum(weights[control]) ** 2 / np.sum(weights[control] ** 2))
    se = math.sqrt(
        weighted_var(y, treated) / max(n_eff_t, 1.0)
        + weighted_var(y, control) / max(n_eff_c, 1.0)
    )
    balance = [
        BalanceRow(
            covariate=name,
            smd_before=_smd(x[treated, i], x[control, i]),
            smd_after=_smd(
                x[treated, i],
                x[control, i],
                weights[treated],
                weights[control],
            ),
        )
        for i, name in enumerate(names)
    ]
    warnings: list[str] = []
    if float(np.max(weights)) > 10:
        warnings.append("extreme weights (>10); check positivity/overlap")
    if float(np.min(ps)) < 0.01 or float(np.max(ps)) > 0.99:
        warnings.append("propensity scores near 0/1; limited overlap")
    if int(np.sum(y[treated])) < 5 or int(np.sum(y[control])) < 5:
        warnings.append("fewer than 5 events in a group; weighted estimates are unstable")
    return IptwResult(
        n=len(treatment),
        treated=int(np.sum(t)),
        control=int(np.sum(1 - t)),
        weight_type=weight_type,
        effect=effect,
        ci_low=effect - 1.96 * se,
        ci_high=effect + 1.96 * se,
        ps_min=float(np.min(ps)),
        ps_max=float(np.max(ps)),
        max_weight=float(np.max(weights)),
        balance=balance,
        warnings=warnings,
    )


def fit_match(
    treatment: list[int],
    outcome: list[int],
    covariates: list[list[float]],
    names: list[str],
    *,
    caliper: float = 0.05,
) -> MatchResult:
    """1:1 nearest-neighbour propensity matching without replacement."""
    if len(treatment) != len(outcome) or len(treatment) != len(covariates):
        raise ValueError("treatment, outcome and covariates must have the same length")
    if not treatment:
        raise ValueError("at least one row is required")
    if len(names) != len(covariates[0]):
        raise ValueError("names must match the covariate columns")
    if caliper <= 0:
        raise ValueError("caliper must be > 0")
    t = np.asarray(treatment, dtype=float)
    y = np.asarray(outcome, dtype=float)
    x = np.asarray(covariates, dtype=float)
    if not np.isin(t, [0.0, 1.0]).all() or not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("treatment and outcome must be 0/1")
    if int(np.sum(t)) < 2 or int(np.sum(1 - t)) < 2:
        raise ValueError("need at least two treated and two control rows")

    ps = fit_propensity(treatment, covariates, names)
    treated_idx = [i for i in range(len(t)) if t[i] == 1]
    available = {i for i in range(len(t)) if t[i] == 0}
    pairs: list[tuple[int, int]] = []
    for ti in sorted(treated_idx, key=lambda i: (-ps[i], i)):
        candidates = [
            ci for ci in available if abs(ps[ti] - ps[ci]) <= caliper
        ]
        if not candidates:
            continue
        ci = min(candidates, key=lambda c: (abs(ps[ti] - ps[c]), c))
        pairs.append((ti, ci))
        available.remove(ci)
    if len(pairs) < 2:
        raise ValueError(
            f"fewer than 2 matched pairs within caliper {caliper}; widen the caliper"
        )
    matched_t = [pair[0] for pair in pairs]
    matched_c = [pair[1] for pair in pairs]
    y_t = y[matched_t]
    y_c = y[matched_c]
    effect = float(np.mean(y_t) - np.mean(y_c))
    se = math.sqrt(
        float(np.var(y_t, ddof=1)) / len(y_t)
        + float(np.var(y_c, ddof=1)) / len(y_c)
    )
    balance = [
        BalanceRow(
            covariate=name,
            smd_before=_smd(x[t == 1, i], x[t == 0, i]),
            smd_after=_smd(x[matched_t, i], x[matched_c, i]),
        )
        for i, name in enumerate(names)
    ]
    warnings: list[str] = []
    unmatched = len(treated_idx) - len(pairs)
    if unmatched:
        warnings.append(f"{unmatched} treated rows left unmatched")
    if len(pairs) < 5:
        warnings.append("fewer than 5 matched pairs; estimates are unstable")
    return MatchResult(
        n=len(treatment),
        treated=int(np.sum(t)),
        control=int(np.sum(1 - t)),
        matched_pairs=len(pairs),
        unmatched_treated=unmatched,
        caliper=caliper,
        effect=effect,
        ci_low=effect - 1.96 * se,
        ci_high=effect + 1.96 * se,
        balance=balance,
        warnings=warnings,
    )


def _curve(group: str, times: list[float], events: list[int]) -> SurvivalCurve:
    unique = sorted(set(times))
    survival = 1.0
    points: list[SurvivalPoint] = []
    for time_value in unique:
        at_risk = sum(1 for t in times if t >= time_value)
        observed = sum(1 for t, e in zip(times, events, strict=True) if t == time_value and e == 1)
        if at_risk:
            survival *= 1.0 - observed / at_risk
        points.append(
            SurvivalPoint(
                time=time_value,
                survival=survival,
                at_risk=at_risk,
                events=observed,
            )
        )
    median = next((point.time for point in points if point.survival <= 0.5), None)
    return SurvivalCurve(
        group=group,
        n=len(times),
        events=sum(events),
        median=median,
        points=points,
    )


def _at_risk(
    times: list[float], groups: list[str], label: str, time_value: float
) -> int:
    return sum(
        1
        for t, g in zip(times, groups, strict=True)
        if g == label and t >= time_value
    )


def _events_at(
    times: list[float],
    events: list[int],
    groups: list[str],
    label: str,
    time_value: float,
) -> int:
    return sum(
        1
        for t, e, g in zip(times, events, groups, strict=True)
        if g == label and t == time_value and e == 1
    )


def kaplan_meier(
    times: list[float], events: list[int], groups: list[str]
) -> SurvivalResult:
    """Kaplan–Meier curves and a two-group log-rank test."""
    if len(times) != len(events) or len(times) != len(groups):
        raise ValueError("times, events and groups must have the same length")
    if not times:
        raise ValueError("at least one row is required")
    if not np.isin(events, [0, 1]).all():
        raise ValueError("events must be 0/1")
    if any(t < 0 for t in times):
        raise ValueError("times must be non-negative")
    labels = sorted(set(groups))
    if len(labels) != 2:
        raise ValueError("log-rank currently requires exactly two groups")
    curves = [
        _curve(
            label,
            [t for t, g in zip(times, groups, strict=True) if g == label],
            [e for e, g in zip(events, groups, strict=True) if g == label],
        )
        for label in labels
    ]
    observed_diff = 0.0
    variance = 0.0
    for time_value in sorted(set(times)):
        n1 = _at_risk(times, groups, labels[0], time_value)
        n2 = _at_risk(times, groups, labels[1], time_value)
        d1 = _events_at(times, events, groups, labels[0], time_value)
        d2 = _events_at(times, events, groups, labels[1], time_value)
        total_n = n1 + n2
        total_d = d1 + d2
        if total_n <= 1:
            continue
        expected = total_d * n1 / total_n
        observed_diff += d1 - expected
        variance += n1 * n2 * total_d * (total_n - total_d) / (total_n**2 * (total_n - 1))
    if variance <= 0:
        raise ValueError("log-rank variance is zero; no informative events")
    chi2 = observed_diff**2 / variance
    p_value = math.erfc(math.sqrt(chi2 / 2.0))
    warnings: list[str] = []
    if min(len(curves[0].points), len(curves[1].points)) == 0:
        warnings.append("one group has no observations")
    if any(curve.events == 0 for curve in curves):
        warnings.append("one group has no events")
    return SurvivalResult(
        groups=curves,
        logrank_chi2=chi2,
        p_value=p_value,
        warnings=warnings,
    )
