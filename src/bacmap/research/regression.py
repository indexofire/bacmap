"""Deterministic regression helpers for research evidence.

The first slice is multivariable logistic regression (IRLS, no scipy dependency).
Mixed-effects, IPTW, matching and survival models remain future work; they must not be
faked by an LLM.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class LogisticResult(BaseModel):
    """Multivariable logistic regression with Wald 95% CIs and p-values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int
    events: int
    feature_names: list[str]
    coefficients: list[float]
    std_errors: list[float]
    odds_ratios: list[float]
    ci_low: list[float]
    ci_high: list[float]
    p_values: list[float]
    converged: bool
    iterations: int
    warnings: list[str] = Field(default_factory=list)


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -35.0, 35.0)))


def _normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def fit_logistic(
    rows: list[list[float]],
    outcomes: list[int],
    feature_names: list[str],
    *,
    max_iter: int = 50,
    tolerance: float = 1e-8,
) -> LogisticResult:
    """Fit ``logit(y) = b0 + b1*x1 + ...`` with IRLS.

    ``rows`` must not include the intercept; it is prepended automatically.
    """
    if len(rows) != len(outcomes):
        raise ValueError("rows and outcomes must have the same length")
    if not rows:
        raise ValueError("at least one row is required")
    if len(feature_names) != len(rows[0]):
        raise ValueError("feature_names must match the number of columns")
    y = np.asarray(outcomes, dtype=float)
    if not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("outcomes must be 0/1")
    X = np.column_stack([np.ones(len(rows)), np.asarray(rows, dtype=float)])
    names = ["intercept", *feature_names]
    if X.shape[0] <= X.shape[1]:
        raise ValueError("not enough rows for the number of parameters")
    beta = np.zeros(X.shape[1], dtype=float)
    converged = False
    iterations = 0
    for iteration in range(1, max_iter + 1):
        iterations = iteration
        eta = X @ beta
        mu = np.clip(_sigmoid(eta), 1e-9, 1 - 1e-9)
        weights = np.clip(mu * (1.0 - mu), 1e-10, None)
        z = eta + (y - mu) / weights
        root_w = np.sqrt(weights)
        design = X * root_w[:, None]
        target = z * root_w
        candidate, *_ = np.linalg.lstsq(design, target, rcond=None)
        delta = candidate - beta
        beta = candidate
        if float(np.max(np.abs(delta))) < tolerance:
            converged = True
            break

    eta = X @ beta
    mu = np.clip(_sigmoid(eta), 1e-9, 1 - 1e-9)
    weights = np.clip(mu * (1.0 - mu), 1e-10, None)
    information = X.T @ (X * weights[:, None])
    covariance = np.linalg.pinv(information)
    std_errors = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    z_values = np.divide(beta, std_errors, out=np.zeros_like(beta), where=std_errors > 0)
    odds_ratios = np.exp(np.clip(beta, -50.0, 50.0))
    ci_low = np.exp(np.clip(beta - 1.96 * std_errors, -50.0, 50.0))
    ci_high = np.exp(np.clip(beta + 1.96 * std_errors, -50.0, 50.0))
    p_values = np.asarray([_normal_two_sided_p(float(value)) for value in z_values])
    warnings: list[str] = []
    if not converged:
        warnings.append("IRLS did not converge; estimates are unstable")
    if int(np.sum(y)) < 10:
        warnings.append("fewer than 10 events; logistic estimates may be biased")
    if float(np.max(np.abs(beta))) > 20 or float(np.max(std_errors)) > 10:
        warnings.append("possible separation or sparse data; interpret with caution")
    return LogisticResult(
        n=len(rows),
        events=int(np.sum(y)),
        feature_names=names,
        coefficients=[float(value) for value in beta],
        std_errors=[float(value) for value in std_errors],
        odds_ratios=[float(value) for value in odds_ratios],
        ci_low=[float(value) for value in ci_low],
        ci_high=[float(value) for value in ci_high],
        p_values=[float(value) for value in p_values],
        converged=converged,
        iterations=iterations,
        warnings=warnings,
    )


def load_columns(
    path: str | Path, columns: list[str]
) -> tuple[list[dict[str, float]], int]:
    """Read a CSV/TSV table and return complete numeric rows plus dropped count."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"table not found: {source}")
    delimiter = "\t" if source.suffix.lower() in {".tsv", ".tab"} else ","
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError("table has no header")
        missing = [name for name in columns if name not in reader.fieldnames]
        if missing:
            raise ValueError(f"missing column(s): {', '.join(missing)}")
        rows: list[dict[str, float]] = []
        dropped = 0
        for record in reader:
            try:
                rows.append({name: float(record[name]) for name in columns})
            except (TypeError, ValueError):
                dropped += 1
    if not rows:
        raise ValueError("no complete rows after dropping missing/invalid values")
    return rows, dropped


def load_survival_table(
    path: str | Path, time_col: str, event_col: str, group_col: str
) -> tuple[list[float], list[int], list[str], int]:
    """Read time/event/group rows; group stays a string."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"table not found: {source}")
    delimiter = "\t" if source.suffix.lower() in {".tsv", ".tab"} else ","
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError("table has no header")
        missing = [
            name
            for name in (time_col, event_col, group_col)
            if name not in reader.fieldnames
        ]
        if missing:
            raise ValueError(f"missing column(s): {', '.join(missing)}")
        times: list[float] = []
        events: list[int] = []
        groups: list[str] = []
        dropped = 0
        for record in reader:
            try:
                time_value = float(record[time_col])
                event_value = int(float(record[event_col]))
            except (TypeError, ValueError):
                dropped += 1
                continue
            group = str(record[group_col] or "").strip()
            if time_value < 0 or event_value not in {0, 1} or not group:
                dropped += 1
                continue
            times.append(time_value)
            events.append(event_value)
            groups.append(group)
    if not times:
        raise ValueError("no complete rows after dropping missing/invalid values")
    return times, events, groups, dropped


def load_table(
    path: str | Path, outcome: str, predictors: list[str]
) -> tuple[list[list[float]], list[int], int]:
    """Read a CSV/TSV table, returning rows, 0/1 outcomes and the number of dropped rows."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"table not found: {source}")
    delimiter = "\t" if source.suffix.lower() in {".tsv", ".tab"} else ","
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError("table has no header")
        missing = [name for name in [outcome, *predictors] if name not in reader.fieldnames]
        if missing:
            raise ValueError(f"missing column(s): {', '.join(missing)}")
        rows: list[list[float]] = []
        outcomes: list[int] = []
        dropped = 0
        for record in reader:
            try:
                values = [float(record[name]) for name in predictors]
                target = int(float(record[outcome]))
            except (TypeError, ValueError):
                dropped += 1
                continue
            if target not in {0, 1}:
                dropped += 1
                continue
            rows.append(values)
            outcomes.append(target)
    if not rows:
        raise ValueError("no complete rows after dropping missing/invalid values")
    return rows, outcomes, dropped


def standardized_mean_difference(treated: list[float], control: list[float]) -> float:
    """Absolute standardized mean difference (pooled SD); 0 means balanced."""
    if not treated or not control:
        raise ValueError("both groups need at least one observation")
    a = np.asarray(treated, dtype=float)
    b = np.asarray(control, dtype=float)
    pooled = math.sqrt((float(np.var(a, ddof=1)) + float(np.var(b, ddof=1))) / 2.0)
    if pooled == 0:
        return 0.0 if float(np.mean(a)) == float(np.mean(b)) else float("inf")
    return abs(float(np.mean(a)) - float(np.mean(b))) / pooled


def result_to_dict(result: LogisticResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
