"""暴发事件挖掘：时间/地点/来源聚类 + 表型关联（不做传播方向推断）。

本模块只消费**已存在的上下文元数据**（日期、地点、研究来源、谱系标签、表型），
不重新做组装、变异调用或系统发育。传播方向仍需外部 gmlst/SNP 工具 + 时间/流调证据。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field

from bacmap.research.stats import associate_counts, benjamini_hochberg

_YEAR = re.compile(r"^(\d{4})")
_MONTH = re.compile(r"^(\d{4})-(\d{2})")


class OutbreakEvent(BaseModel):
    """一个可挖掘的暴发/散在事件；字段来自外部元数据。"""

    case_id: str = Field(min_length=1, max_length=256)
    isolate_id: str = ""
    event_date: str = ""
    location: str = ""
    source: str = ""
    phenotype: str = ""  # resistant | susceptible | intermediate | unknown
    lineage: str = ""  # external cluster/lineage label; never computed here
    run_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)



class OutbreakAnalyzeRequest(BaseModel):
    events: list[OutbreakEvent] = Field(default_factory=list, max_length=10000)
    min_count: int = Field(default=5, ge=1, le=100)


def event_period(raw: str) -> str:
    """Coarsen a date to the precision actually recorded (year or year-month)."""
    text = (raw or "").strip()
    if not text or text.upper().startswith("XXXX"):
        return ""
    match = _MONTH.match(text)
    if match and match.group(2).isdigit() and 1 <= int(match.group(2)) <= 12:
        return f"{match.group(1)}-{match.group(2)}"
    match = _YEAR.match(text)
    return match.group(1) if match else ""


def _phenotype(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("r") or raw in {"resistant", "耐药"}:
        return "resistant"
    if raw.startswith("s") or raw in {"susceptible", "敏感"}:
        return "susceptible"
    if raw.startswith("i") or raw in {"intermediate", "中介"}:
        return "intermediate"
    return ""


def cluster_events(events: list[OutbreakEvent]) -> list[dict]:
    """Group events by location + recorded period (no finer than the data).

    Events with no period are kept in a separate ``unknown-date`` bucket and are
    reported as unclustered rather than silently assigned a date.
    """
    groups: dict[tuple[str, str], list[OutbreakEvent]] = defaultdict(list)
    for event in events:
        location = (event.location or "unknown").strip() or "unknown"
        period = event_period(event.event_date) or "unknown-date"
        groups[(location, period)].append(event)
    clusters: list[dict] = []
    for (location, period), members in sorted(groups.items()):
        identities = sorted(m.case_id for m in members)
        digest = hashlib.sha256(
            f"{location}|{period}|{','.join(identities)}".encode()
        ).hexdigest()[:12]
        phenotypes = Counter(_phenotype(m.phenotype) or "unknown" for m in members)
        clusters.append(
            {
                "cluster_id": f"oc-{digest}",
                "location": location,
                "period": period,
                "n": len(members),
                "case_ids": identities,
                "sources": dict(sorted(Counter(m.source or "unknown" for m in members).items())),
                "lineages": dict(
                    sorted(Counter(m.lineage or "unknown" for m in members).items())
                ),
                "phenotypes": dict(sorted(phenotypes.items())),
                "sporadic": len(members) == 1 or period == "unknown-date",
            }
        )
    return clusters


def _categories(
    events: list[OutbreakEvent], exposure: str, clustered_ids: set[str]
) -> dict[str, str]:
    out: dict[str, str] = {}
    for event in events:
        if exposure == "clustered":
            out[event.case_id] = "clustered" if event.case_id in clustered_ids else "sporadic"
        elif exposure == "source":
            out[event.case_id] = (event.source or "unknown").strip() or "unknown"
        elif exposure == "lineage":
            out[event.case_id] = (event.lineage or "unknown").strip() or "unknown"
        else:
            raise ValueError(f"unknown exposure: {exposure}")
    return out


def mine_categorical(
    events: list[OutbreakEvent],
    exposure: str = "source",
    min_count: int = 5,
    clustered_ids: set[str] | None = None,
) -> dict:
    """For each exposure category, compare phenotype against the rest.

    This is exploratory data mining: BH-adjusted, but not lineage-adjusted. An
    association here is a candidate, never a transmission or causal claim.
    """
    clustered_ids = clustered_ids or set()
    labels = _categories(events, exposure, clustered_ids)
    usable = [
        e for e in events
        if _phenotype(e.phenotype) in {"resistant", "susceptible"}
    ]
    total_r = sum(1 for e in usable if _phenotype(e.phenotype) == "resistant")
    total_s = len(usable) - total_r
    rows: list[dict] = []
    p_values: list[float | None] = []
    for category in sorted(set(labels[e.case_id] for e in usable)):
        members = [e for e in usable if labels[e.case_id] == category]
        if len(members) < min_count:
            continue
        a = sum(1 for e in members if _phenotype(e.phenotype) == "resistant")
        b = len(members) - a
        c = total_r - a
        d = total_s - b
        stat = associate_counts(a, b, c, d)
        rows.append(
            {
                "category": category,
                "n": len(members),
                "table": stat.table,
                "odds_ratio": stat.odds_ratio,
                "ci_low": stat.ci_low,
                "ci_high": stat.ci_high,
                "p_value": stat.p_value,
            }
        )
        p_values.append(stat.p_value)
    for row, q in zip(rows, benjamini_hochberg(p_values), strict=True):
        row["q_value"] = q
    rows.sort(key=lambda r: (r["q_value"] is None, r["q_value"] or 1.0, r["category"]))
    return {
        "exposure": exposure,
        "min_count": min_count,
        "n_events": len(usable),
        "n_tested": len(rows),
        "multiplicity": "Benjamini-Hochberg FDR across categories",
        "associations": rows,
        "caveat": (
            "Exploratory association only: no lineage adjustment, no transmission "
            "direction, and source/location may be confounded by sampling."
        ),
    }


def summarize_outbreak(events: list[OutbreakEvent], min_count: int = 5) -> dict:
    """Deterministic outbreak-context summary, clusters and categorical mining."""
    if not events:
        return {
            "n_events": 0,
            "clusters": [],
            "mining": [],
            "limits": ["no events"],
        }
    clusters = cluster_events(events)
    clustered_ids = {
        case_id
        for cluster in clusters
        if not cluster["sporadic"]
        for case_id in cluster["case_ids"]
    }
    phenotype_counts = Counter(_phenotype(e.phenotype) or "unknown" for e in events)
    periods = sorted({event_period(e.event_date) for e in events if event_period(e.event_date)})
    locations = Counter((e.location or "unknown").strip() or "unknown" for e in events)
    sources = Counter((e.source or "unknown").strip() or "unknown" for e in events)
    exposures = ["clustered", "source"]
    if any(e.lineage.strip() for e in events):
        exposures.append("lineage")
    mining = [
        mine_categorical(events, exposure, min_count, clustered_ids)
        for exposure in exposures
    ]
    return {
        "n_events": len(events),
        "n_cases_with_phenotype": sum(
            1 for e in events if _phenotype(e.phenotype) in {"resistant", "susceptible"}
        ),
        "phenotypes": dict(sorted(phenotype_counts.items())),
        "n_clusters": len(clusters),
        "n_clustered_events": len(clustered_ids),
        "n_sporadic_events": len(events) - len(clustered_ids),
        "date_range": [periods[0], periods[-1]] if periods else [],
        "locations": dict(sorted(locations.items())),
        "sources": dict(sorted(sources.items())),
        "clusters": sorted(clusters, key=lambda c: (-c["n"], c["cluster_id"])),
        "mining": mining,
        "limits": [
            "clustering uses only recorded location + date precision; no SNP/allele distances",
            "sporadic vs clustered is contextual, not a transmission classification",
            "association mining is exploratory and does not adjust for lineage",
            "transmission claims still require external typing + temporal/epidemiological evidence",
        ],
    }
