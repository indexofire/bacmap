"""样本量/把握度与外部验证（P4 第一片：确定性、纯标准库）。

把握度是**设计输入**（a priori power）：给定预期比例（或基线比例 + OR）→ 每组
所需样本量；或给定 n → 达到的把握度。两比例差异的正态近似（Chow/Wang 无合并
方差式，stdlib ``statistics.NormalDist``）。

外部验证：Woolf 齐性检验（Q 统计量，χ²、df=1）比较推导队列与验证队列的
两个 2×2 关联 —— 一致（可合并）还是存在异质性。

边界（如实记录，不越界）：

- session 模式把**已观察比例当作设计假设**并标注 ``design_input_from_session``，
  不是"事后功效"断言（post-hoc power 无统计意义）；
- 不含连续性校正（文献变体多，主式最通用）；小样本或极端比例（比例 <0.05 或
  >0.95，或每组 n<30）时结果带 ``caution`` 提示，应改用精确法（后续，需另立项）；
- 混合效应/IPTW/匹配/生存分析不在此处（PLAN P4 另一项，需新依赖/ADR）。
"""

from __future__ import annotations

import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

from bacmap.research.models import ResearchError, StatResult
from bacmap.research.store import ResearchStore

POWER_SCHEMA = "bacmap.power_two_proportions/1"
VALIDATION_SCHEMA = "bacmap.external_validation/1"

_Z = NormalDist()


def _check_proportion(name: str, value: float) -> float:
    if not 0.0 < value < 1.0:
        raise ValueError(f"{name} must be in (0, 1), got {value}")
    return value


def proportions_from_odds(baseline: float, odds_ratio: float) -> float:
    """基线比例 + OR → 暴露组比例：p1 = OR·p0 / (1 + p0·(OR−1))。"""
    _check_proportion("baseline", baseline)
    if odds_ratio <= 0:
        raise ValueError(f"odds_ratio must be positive, got {odds_ratio}")
    return odds_ratio * baseline / (1 + baseline * (odds_ratio - 1))


def _caution(p1: float, p2: float, n1: int, n2: int) -> list[str]:
    notes: list[str] = []
    if min(p1, p2) < 0.05 or max(p1, p2) > 0.95:
        notes.append("extreme proportion (<0.05 or >0.95): normal approximation degrades")
    if min(n1, n2) < 30:
        notes.append("group size < 30: consider an exact method")
    return notes


def sample_size_two_proportions(
    *,
    p1: float,
    p2: float,
    alpha: float = 0.05,
    power: float = 0.80,
    ratio: float = 1.0,
) -> dict:
    """每干预组所需样本量（正态近似，无连续性校正）。

    ``ratio`` = n2/n1（对照组/暴露组样本比，1 为均衡设计）。
    """
    _check_proportion("p1", p1)
    _check_proportion("p2", p2)
    if not 0 < alpha < 0.5:
        raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
    if not 0.5 <= power < 1:
        raise ValueError(f"power must be in [0.5, 1), got {power}")
    if ratio <= 0:
        raise ValueError(f"ratio must be positive, got {ratio}")
    delta = p1 - p2
    if delta == 0:
        raise ValueError("p1 and p2 are equal; there is nothing to detect")

    z_alpha = _Z.inv_cdf(1 - alpha / 2)
    z_beta = _Z.inv_cdf(power)
    p_bar = (p1 + ratio * p2) / (1 + ratio)
    se0 = math.sqrt((1 + 1 / ratio) * p_bar * (1 - p_bar))
    se1 = math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / ratio)
    n1_raw = ((z_alpha * se0 + z_beta * se1) / delta) ** 2
    n1 = math.ceil(n1_raw)
    n2 = math.ceil(ratio * n1_raw)
    return {
        "schema": POWER_SCHEMA,
        "method": "two-proportion normal approximation (unpooled, no continuity correction)",
        "p1": p1,
        "p2": p2,
        "alpha": alpha,
        "power": power,
        "ratio": ratio,
        "n1": n1,
        "n2": n2,
        "n_total": n1 + n2,
        "caution": _caution(p1, p2, n1, n2),
        "note": (
            "design input: choose p1/p2 from prior knowledge, not from the data you "
            "will test; the formula detects a two-sided difference in proportions"
        ),
    }


def achieved_power_two_proportions(
    *,
    n1: int,
    n2: int,
    p1: float,
    p2: float,
    alpha: float = 0.05,
) -> dict:
    """给定每组样本量与预期比例 → 达到的把握度（双侧检验）。"""
    _check_proportion("p1", p1)
    _check_proportion("p2", p2)
    if n1 < 1 or n2 < 1:
        raise ValueError("n1 and n2 must be >= 1")
    if not 0 < alpha < 0.5:
        raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
    delta = abs(p1 - p2)
    if delta == 0:
        raise ValueError("p1 and p2 are equal; power is undefined at the null")

    z_alpha = _Z.inv_cdf(1 - alpha / 2)
    p_bar = (n1 * p1 + n2 * p2) / (n1 + n2)
    se0 = math.sqrt(p_bar * (1 - p_bar) * (1 / n1 + 1 / n2))
    se1 = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    upper = _Z.cdf((delta - z_alpha * se0) / se1)
    lower = _Z.cdf((-delta - z_alpha * se0) / se1)
    return {
        "schema": POWER_SCHEMA,
        "method": "two-proportion normal approximation (achieved power)",
        "p1": p1,
        "p2": p2,
        "alpha": alpha,
        "n1": n1,
        "n2": n2,
        "power": min(1.0, upper + lower),
        "caution": _caution(p1, p2, n1, n2),
        "note": "design input for a planned comparison; not a post-hoc claim",
    }


def compute(
    *,
    p1: float | None = None,
    p2: float | None = None,
    baseline: float | None = None,
    odds_ratio: float | None = None,
    n1: int | None = None,
    n2: int | None = None,
    alpha: float = 0.05,
    power: float = 0.80,
    ratio: float = 1.0,
    session_id: str = "",
    home: str | Path = "",
) -> dict:
    """CLI/MCP 共用的参数编排：比例模式 / baseline+OR 模式 / session 模式。

    抛 ``ValueError``/``ResearchError``，由接口层转成错误信封。
    """
    if session_id:
        if p1 is not None or p2 is not None:
            raise ValueError("session_id and p1/p2 are mutually exclusive")
        if not home:
            raise ValueError("session mode requires the bacmap home")
        return power_for_session(home, session_id, target_power=power, alpha=alpha)
    if p1 is None:
        if baseline is None or odds_ratio is None:
            raise ValueError("give p1 (and p2), or baseline+odds_ratio, or session_id")
        p1 = proportions_from_odds(baseline, odds_ratio)
        if p2 is None:
            p2 = baseline
    if p2 is None:
        raise ValueError("p2 is required")
    if n1 is not None and n2 is not None:
        return achieved_power_two_proportions(
            n1=n1, n2=n2, p1=p1, p2=p2, alpha=alpha
        )
    return sample_size_two_proportions(
        p1=p1, p2=p2, alpha=alpha, power=power, ratio=ratio
    )


def power_for_session(
    home: str | Path, session_id: str, *, target_power: float = 0.80, alpha: float = 0.05
) -> dict:
    """以某 session 的观察比例为设计假设，报告目标把握度所需样本量。

    P(结局|基因+) 与 P(结局|基因−) 来自 session 的 2×2 表；结果标注
    ``design_input_from_session``，明示这不是该 session 的事后功效。
    """
    with ResearchStore(Path(home)) as store:
        try:
            store.get_session(session_id)
            stat = store.get_stat(session_id)
        except KeyError as exc:
            raise ResearchError("not_found", f"no such research session: {session_id}") from exc
    if stat is None:
        raise ResearchError("not_found", f"session {session_id} has no statistics")
    return power_from_stat(
        stat, target_power=target_power, alpha=alpha, session_id=session_id
    )


def power_from_stat(
    stat: StatResult,
    *,
    target_power: float = 0.80,
    alpha: float = 0.05,
    session_id: str = "",
) -> dict:
    a = stat.table.get("gene_pos_resistant", 0)
    b = stat.table.get("gene_pos_susceptible", 0)
    c = stat.table.get("gene_neg_resistant", 0)
    d = stat.table.get("gene_neg_susceptible", 0)
    if a + b < 1 or c + d < 1:
        raise ResearchError(
            "validation_error",
            "session table has an empty gene stratum; proportions are undefined",
        )
    p1 = a / (a + b)
    p2 = c / (c + d)
    if p1 == p2:
        raise ResearchError(
            "validation_error",
            "observed proportions are equal; nothing to design for (delta = 0)",
        )
    plan = sample_size_two_proportions(
        p1=p1, p2=p2, alpha=alpha, power=target_power
    )
    current = achieved_power_two_proportions(
        n1=a + b, n2=c + d, p1=p1, p2=p2, alpha=alpha
    )
    plan["design_input_from_session"] = session_id
    plan["observed"] = {
        "p1_resistant_given_gene_pos": p1,
        "p2_resistant_given_gene_neg": p2,
        "n1_gene_pos": a + b,
        "n2_gene_neg": c + d,
        "achieved_power_at_current_n": current["power"],
    }
    plan["note"] = (
        "a priori design using this session's observed proportions as planning "
        "assumptions; the achieved_power_at_current_n field is descriptive, not "
        "evidence for the observed association"
    )
    return plan


def _ln_or_variance(a: int, b: int, c: int, d: int) -> float:
    aa, bb, cc, dd = (a + 0.5, b + 0.5, c + 0.5, d + 0.5)
    return 1 / aa + 1 / bb + 1 / cc + 1 / dd


def external_validation(
    derivation: StatResult, validation: StatResult, *, alpha: float = 0.05
) -> dict:
    """Woolf 齐性检验：推导与验证队列的 OR 是否一致（χ², df=1）。

    结论只回答"两队列估计是否可合并/一致"，不把验证队列的显著性当作
    复现成功——验证队列自身可能把握度不足（配 ``power`` 字段辅助解读）。
    """
    strata: list[dict[str, Any]] = []
    for label, stat in (("derivation", derivation), ("validation", validation)):
        a = stat.table.get("gene_pos_resistant", 0)
        b = stat.table.get("gene_pos_susceptible", 0)
        c = stat.table.get("gene_neg_resistant", 0)
        d = stat.table.get("gene_neg_susceptible", 0)
        if min(a, b, c, d) < 0 or a + b + c + d == 0:
            raise ValueError(f"{label} table is invalid")
        aa, bb, cc, dd = (a + 0.5, b + 0.5, c + 0.5, d + 0.5)  # Haldane-Anscombe
        ln_or = math.log((aa * dd) / (bb * cc))
        var = _ln_or_variance(a, b, c, d)
        se = math.sqrt(var)
        strata.append(
            {
                "cohort": label,
                "n": stat.n,
                "odds_ratio": math.exp(ln_or),
                "ci_low": math.exp(ln_or - 1.959963984540054 * se),
                "ci_high": math.exp(ln_or + 1.959963984540054 * se),
                "weight": 1 / var,
                "ln_or": ln_or,
            }
        )
    weights = [s["weight"] for s in strata]
    ln_pooled = sum(w * s["ln_or"] for s, w in zip(strata, weights, strict=True)) / sum(
        weights
    )
    q_stat = sum(
        w * (s["ln_or"] - ln_pooled) ** 2
        for s, w in zip(strata, weights, strict=True)
    )
    p_value = math.erfc(math.sqrt(q_stat / 2))  # χ² df=1 上尾
    consistent = p_value >= alpha
    return {
        "schema": VALIDATION_SCHEMA,
        "method": "Woolf test of homogeneity (Q, chi-square df=1, 0.5 correction)",
        "alpha": alpha,
        "cohorts": strata,
        "pooled_odds_ratio": math.exp(ln_pooled),
        "q_statistic": q_stat,
        "p_value": p_value,
        "consistent": consistent,
        "interpretation": (
            "estimates are homogeneous (may be pooled; the validation cohort does not "
            "contradict the derivation association)"
            if consistent
            else "heterogeneity detected: the validation cohort contradicts the "
            "derivation estimate — do not pool without explaining the difference"
        ),
        "note": (
            "consistency is not replication success: the validation cohort may be "
            "underpowered; pair with `stats power` for design"
        ),
    }


def validate_sessions(
    home: str | Path,
    derivation_session: str,
    validation_session: str,
    *,
    alpha: float = 0.05,
) -> dict:
    with ResearchStore(Path(home)) as store:
        derivation_stat: StatResult | None = None
        validation_stat: StatResult | None = None
        for label, session_id in (
            ("derivation", derivation_session),
            ("validation", validation_session),
        ):
            try:
                store.get_session(session_id)
                stat = store.get_stat(session_id)
            except KeyError as exc:
                raise ResearchError(
                    "not_found", f"no such research session: {session_id}"
                ) from exc
            if stat is None:
                raise ResearchError(
                    "not_found", f"session {session_id} has no statistics"
                )
            if label == "derivation":
                derivation_stat = stat
            else:
                validation_stat = stat
    if derivation_stat is None or validation_stat is None:
        # 上面循环里 None 已各自抛 not_found；此处仅满足类型收窄
        raise ResearchError("not_found", "missing derivation or validation statistics")
    result = external_validation(derivation_stat, validation_stat, alpha=alpha)
    result["derivation_session"] = derivation_session
    result["validation_session"] = validation_session
    return result
