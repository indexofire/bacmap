"""P1 确定性统计：AMR 基因存在 × 表型耐药的 2×2 关联。

只读取已有证据（gom.sqlite 的 strain_amr_genes、data/bacmap.sqlite 的 lab_results、
runs.sqlite 的 run 记录），不发起新测序、不调用 LLM。
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from bacmap.research.models import ResearchError, StatResult
from bacmap.store import runs

_Z95 = 1.959963984540054


def _open_ro(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _run_strains(home: Path, run_id: str) -> list[str]:
    run = runs.read_run(run_id, home / "runs.sqlite")
    if run is None:
        raise ResearchError("not_found", f"no such run: {run_id}")
    return list(run.strain_ids)


def _gene_present(
    home: Path, strain_ids: list[str], gene: str, diagnostics: list[str]
) -> dict[str, bool]:
    conn = _open_ro(home / "gom.sqlite")
    if conn is None:
        diagnostics.append("gom.sqlite missing; gene presence treated as unknown")
        return {}
    try:
        cols = _table_columns(conn, "strain_amr_genes")
        if not cols:
            diagnostics.append("strain_amr_genes table missing; gene presence treated as unknown")
            return {}
        rows = conn.execute(
            "SELECT DISTINCT strain_id FROM strain_amr_genes WHERE lower(gene_name) = lower(?)",
            (gene,),
        ).fetchall()
        present = {str(r["strain_id"]) for r in rows}
        return {sid: sid in present for sid in strain_ids}
    finally:
        conn.close()


def _phenotypes(
    home: Path, strain_ids: list[str], test_name: str, diagnostics: list[str]
) -> dict[str, bool]:
    conn = _open_ro(home / "data" / "bacmap.sqlite")
    if conn is None:
        diagnostics.append("data/bacmap.sqlite missing; phenotype treated as unknown")
        return {}
    try:
        cols = _table_columns(conn, "lab_results")
        if not cols:
            diagnostics.append("lab_results table missing; phenotype treated as unknown")
            return {}
        rows = conn.execute(
            "SELECT strain_id, interpretation, result FROM lab_results"
            " WHERE lower(test_name) = lower(?) ORDER BY created_at DESC",
            (test_name,),
        ).fetchall()
        wanted = set(strain_ids)
        out: dict[str, bool] = {}
        for r in rows:
            sid = str(r["strain_id"])
            if sid not in wanted or sid in out:
                continue
            interp = str(r["interpretation"] or "").strip().lower()
            if interp.startswith("r") or interp in {"resistant", "耐药"}:
                out[sid] = True
            elif interp.startswith("s") or interp in {"susceptible", "敏感"}:
                out[sid] = False
            elif interp.startswith("i") or interp in {"intermediate", "中介"}:
                diagnostics.append(f"{sid}: intermediate phenotype skipped")
            else:
                diagnostics.append(f"{sid}: no usable interpretation (result={r['result']!r})")
        return out
    finally:
        conn.close()


def _fisher_two_sided(a: int, b: int, c: int, d: int) -> float | None:
    n = a + b + c + d
    if n == 0:
        return None
    row1 = a + b
    col1 = a + c
    if n > 2000:
        # 大样本用两比例 z 近似，避免巨大的组合数；MVP 数据通常很小。
        p1 = a / row1 if row1 else 0.0
        p2 = c / (c + d) if (c + d) else 0.0
        pooled = col1 / n
        se = math.sqrt(pooled * (1 - pooled) * (1 / row1 + 1 / (c + d))) if 0 < pooled < 1 else 0
        if se == 0:
            return None
        z = abs(p1 - p2) / se
        return math.erfc(z / math.sqrt(2))
    denom = math.comb(n, col1)
    if denom == 0:
        return None
    observed = (math.comb(row1, a) * math.comb(n - row1, col1 - a)) / denom
    total = 0.0
    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)
    for x in range(lo, hi + 1):
        prob = (math.comb(row1, x) * math.comb(n - row1, col1 - x)) / denom
        if prob <= observed + 1e-15:
            total += prob
    return min(1.0, total)


def analyze_amr_association(
    home: Path | str, run_id: str, gene: str, test_name: str
) -> StatResult:
    home = Path(home)
    diagnostics: list[str] = []
    strain_ids = _run_strains(home, run_id)
    genes = _gene_present(home, strain_ids, gene, diagnostics)
    phenos = _phenotypes(home, strain_ids, test_name, diagnostics)

    usable = [s for s in strain_ids if s in genes and s in phenos]
    a = sum(1 for s in usable if genes[s] and phenos[s])
    b = sum(1 for s in usable if genes[s] and not phenos[s])
    c = sum(1 for s in usable if not genes[s] and phenos[s])
    d = sum(1 for s in usable if not genes[s] and not phenos[s])
    if not usable:
        diagnostics.append("no strain has both gene presence and usable phenotype")
    return associate_counts(a, b, c, d, diagnostics=diagnostics)


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    """Benjamini–Hochberg FDR adjustment, preserving order and missing values.

    ``None`` entries (e.g. an untestable stratum) are left as ``None`` and do not
    count towards the number of hypotheses.
    """
    indexed = [(i, p) for i, p in enumerate(p_values) if p is not None]
    m = len(indexed)
    if m == 0:
        return [None for _ in p_values]
    indexed.sort(key=lambda item: item[1])
    adjusted: list[float | None] = [None for _ in p_values]
    running = 1.0
    for rank in range(m, 0, -1):
        i, p_value = indexed[rank - 1]
        if p_value is None:  # filtered above; keeps the type checker honest
            continue
        running = min(running, p_value * m / rank)
        adjusted[i] = min(1.0, running)
    return adjusted


def mantel_haenszel(strata: list[tuple[int, int, int, int]]) -> dict:
    """Pooled Mantel–Haenszel odds ratio with Greenland–Robins 95% CI.

    Each stratum is ``(a, b, c, d)`` = gene+/resistant, gene+/susceptible,
    gene-/resistant, gene-/susceptible. Zero cells in a stratum receive the
    Haldane–Anscombe 0.5 correction for that stratum only.
    """
    diagnostics: list[str] = []
    clean: list[tuple[float, float, float, float]] = []
    for a, b, c, d in strata:
        if min(a, b, c, d) < 0:
            raise ValueError("stratum counts must be non-negative")
        if a + b + c + d == 0:
            diagnostics.append("empty stratum skipped")
            continue
        if 0 in (a, b, c, d):
            diagnostics.append("zero cell in stratum: 0.5 correction applied")
            clean.append((a + 0.5, b + 0.5, c + 0.5, d + 0.5))
        else:
            clean.append((float(a), float(b), float(c), float(d)))
    if not clean:
        return {
            "odds_ratio": None,
            "ci_low": None,
            "ci_high": None,
            "p_value": None,
            "n_strata": 0,
            "n": 0,
            "diagnostics": [*diagnostics, "no usable strata"],
        }
    rs: list[float] = []
    ss: list[float] = []
    observed = 0.0
    expected = 0.0
    hypergeometric_var = 0.0
    total_n = 0.0
    for aa, bb, cc, dd in clean:
        n = aa + bb + cc + dd
        total_n += n
        r = aa * dd / n
        s = bb * cc / n
        rs.append(r)
        ss.append(s)
        observed += aa
        expected += (aa + bb) * (aa + cc) / n
        if n > 1:
            hypergeometric_var += (aa + bb) * (cc + dd) * (aa + cc) * (bb + dd) / (n * n * (n - 1))
    sum_r = sum(rs)
    sum_s = sum(ss)
    odds_ratio = sum_r / sum_s if sum_s else None
    ci_low = ci_high = None
    if odds_ratio is not None and odds_ratio > 0:
        # Greenland–Robins variance of ln(OR_MH).
        term_a = term_b = term_c = 0.0
        for aa, bb, cc, dd in clean:
            n = aa + bb + cc + dd
            term_a += (aa + dd) * aa * dd / (n * n)
            term_b += ((aa + dd) * bb * cc + (bb + cc) * aa * dd) / (2 * n * n)
            term_c += (bb + cc) * bb * cc / (n * n)
        var = (
            term_a / (2 * sum_r * sum_r)
            + term_b / (2 * sum_r * sum_s)
            + term_c / (2 * sum_s * sum_s)
        )
        if var > 0:
            se = math.sqrt(var)
            log_or = math.log(odds_ratio)
            ci_low = math.exp(log_or - _Z95 * se)
            ci_high = math.exp(log_or + _Z95 * se)
    p_value = None
    if hypergeometric_var > 0:
        chi2 = (observed - expected) ** 2 / hypergeometric_var
        p_value = math.erfc(math.sqrt(chi2 / 2))
    return {
        "odds_ratio": odds_ratio,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_value": p_value,
        "n_strata": len(clean),
        "n": int(total_n),
        "diagnostics": diagnostics,
    }


def e_value_odds_ratio(odds_ratio: float | None) -> float | None:
    """VanderWeele–Ding E-value for an odds ratio (rare-outcome RR approximation).

    ``RR ≈ sqrt(OR)``; for OR < 1 the E-value uses ``1/OR``. The result is the
    minimum strength of association an unmeasured confounder would need with both
    exposure and outcome to explain away the observed association.
    """
    if odds_ratio is None or odds_ratio <= 0:
        return None
    rr = math.sqrt(odds_ratio) if odds_ratio >= 1 else math.sqrt(1 / odds_ratio)
    if rr < 1:
        return None
    return rr + math.sqrt(rr * (rr - 1))


def sensitivity_summary(
    table: tuple[int, int, int, int],
    strata: list[tuple[str, int, int, int, int]] | None = None,
) -> dict:
    """Crude vs stratified sensitivity for a 2×2 association.

    ``strata`` entries are ``(label, a, b, c, d)``. Returns the crude estimate,
    Mantel–Haenszel pooled estimate (if strata exist), leave-one-stratum-out
    range, and the E-value for the crude OR.
    """
    crude = associate_counts(*table)
    out: dict = {
        "crude": {
            "odds_ratio": crude.odds_ratio,
            "ci_low": crude.ci_low,
            "ci_high": crude.ci_high,
            "p_value": crude.p_value,
            "n": crude.n,
        },
        "e_value_crude": e_value_odds_ratio(crude.odds_ratio),
    }
    labels = [s[0] for s in (strata or [])]
    counts = [(s[1], s[2], s[3], s[4]) for s in (strata or [])]
    if not counts:
        out["adjusted"] = None
        out["leave_one_out"] = None
        return out
    mh = mantel_haenszel(counts)
    out["adjusted"] = {
        "method": "Mantel-Haenszel",
        "odds_ratio": mh["odds_ratio"],
        "ci_low": mh["ci_low"],
        "ci_high": mh["ci_high"],
        "p_value": mh["p_value"],
        "n_strata": mh["n_strata"],
        "n": mh["n"],
        "diagnostics": mh["diagnostics"],
        "e_value": e_value_odds_ratio(mh["odds_ratio"]),
    }
    if len(counts) >= 2:
        lo = hi = None
        lo_label = hi_label = ""
        for i, label in enumerate(labels):
            reduced = counts[:i] + counts[i + 1 :]
            value = mantel_haenszel(reduced)["odds_ratio"]
            if value is None:
                continue
            if lo is None or value < lo:
                lo, lo_label = value, label
            if hi is None or value > hi:
                hi, hi_label = value, label
        out["leave_one_out"] = {
            "min_odds_ratio": lo,
            "min_dropped": lo_label,
            "max_odds_ratio": hi,
            "max_dropped": hi_label,
        }
    else:
        out["leave_one_out"] = None
    return out


def associate_counts(
    a: int, b: int, c: int, d: int, diagnostics: list[str] | None = None
) -> StatResult:
    """纯 2×2 → OR/95% CI/Fisher p（供服务和科学基准复用）。"""
    diagnostics = list(diagnostics or [])
    table = {
        "gene_pos_resistant": a,
        "gene_pos_susceptible": b,
        "gene_neg_resistant": c,
        "gene_neg_susceptible": d,
    }
    n = a + b + c + d
    if n == 0:
        return StatResult(session_id="", table=table, n=0, diagnostics=diagnostics)
    aa, bb, cc, dd = float(a), float(b), float(c), float(d)
    if 0 in (a, b, c, d):
        aa, bb, cc, dd = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        diagnostics.append("zero cell(s): Haldane-Anscombe 0.5 correction applied to OR/CI")
    odds_ratio = (aa * dd) / (bb * cc) if bb * cc else None
    ci_low = ci_high = None
    if odds_ratio is not None and odds_ratio > 0:
        se = math.sqrt(1 / aa + 1 / bb + 1 / cc + 1 / dd)
        log_or = math.log(odds_ratio)
        ci_low = math.exp(log_or - _Z95 * se)
        ci_high = math.exp(log_or + _Z95 * se)
    p_value = _fisher_two_sided(a, b, c, d)
    if p_value is None:
        diagnostics.append("Fisher exact test unavailable")
    return StatResult(
        session_id="",
        table=table,
        odds_ratio=odds_ratio,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        n=n,
        diagnostics=diagnostics,
    )
