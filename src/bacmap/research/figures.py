"""Publication figure contract.

A figure is not "an AI drawing".  The numbers and provenance come from bacmap as a typed
``FigureSpec``; rendering is either deterministic (standard figures) or an agent-authored
script executed in the existing ``mine`` sandbox (custom figures).  Either way the output is
registered with spec/data/code/output hashes so a reviewer can reproduce it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bacmap import __version__
from bacmap.research import figure_checks
from bacmap.research.models import AnalysisSession, StatResult

SCHEMA: Literal["bacmap.figure_spec/1"] = "bacmap.figure_spec/1"
ARTIFACT_SCHEMA: Literal["bacmap.figure_artifact/1"] = "bacmap.figure_artifact/1"

FigureKind = Literal["association_bar", "forest", "flow", "custom"]
Renderer = Literal["bacmap-deterministic", "agent-script"]


class FigureStyle(BaseModel):
    """Journal-facing defaults; all values are explicit so a script cannot guess."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    width_mm: float = 180.0
    height_mm: float = 120.0
    dpi: int = 300
    formats: list[str] = Field(default_factory=lambda: ["pdf", "svg", "png"])
    font_family: str = "Arial"
    font_size_pt: float = 8.0
    palette: str = "colorblind-safe"
    palette_colors: list[str] = Field(default_factory=list)
    line_width_pt: float = 0.75
    journal: str = ""
    panel_layout: str = "single"
    reference_note: str = Field(
        default="",
        description=(
            "Human-provided style reference (journal/example), never a copied image. "
            "The agent extracts a brief; the image itself is not stored or redistributed."
        ),
    )


class FigureSource(BaseModel):
    """Identifiers a reviewer needs to trace every number in the figure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    run_id: str
    stat_sha256: str
    plan_id: str = ""
    plan_hash: str = ""
    data_class: int = 2


class FigureSpec(BaseModel):
    """Machine-readable figure contract emitted by bacmap."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["bacmap.figure_spec/1"] = Field(default=SCHEMA, alias="schema")
    figure_id: str
    recipe_id: str = "association_bar"
    kind: FigureKind
    title: str
    caption: str
    data: dict[str, Any]
    style: FigureStyle = Field(default_factory=FigureStyle)
    source: FigureSource
    constraints: list[str] = Field(default_factory=list)
    generated_by: str = "bacmap"
    bacmap_version: str = __version__


class FigureArtifact(BaseModel):
    """Provenance manifest for a rendered figure (deterministic or agent-authored)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["bacmap.figure_artifact/1"] = Field(
        default=ARTIFACT_SCHEMA, alias="schema"
    )
    figure_id: str
    recipe_id: str = ""
    renderer: Renderer
    output: str
    output_sha256: str
    spec_sha256: str
    data_sha256: str
    code_sha256: str = ""
    code_path: str = ""
    environment: dict[str, str] = Field(default_factory=dict)
    source: FigureSource
    created_at: str


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stat_sha256(stat: StatResult) -> str:
    return sha256_text(_canonical(stat.model_dump(mode="json")))


def spec_sha256(spec: FigureSpec) -> str:
    return sha256_text(_canonical(spec.model_dump(mode="json", by_alias=True)))


def data_sha256(spec: FigureSpec) -> str:
    return sha256_text(_canonical(spec.data))


def build_association_spec(session: AnalysisSession, stat: StatResult) -> FigureSpec:
    """Standard figure contract for the P1 2×2 association."""
    table = dict(stat.table)
    data = {
        "gene": session.gene,
        "test_name": session.test_name,
        "table": table,
        "n": stat.n,
        "odds_ratio": stat.odds_ratio,
        "ci_low": stat.ci_low,
        "ci_high": stat.ci_high,
        "p_value": stat.p_value,
        "diagnostics": list(stat.diagnostics),
        "label": session.label or session.status.value,
    }
    return FigureSpec(
        figure_id=f"{session.session_id}-fig1",
        kind="association_bar",
        title=f"{session.gene} × {session.test_name}",
        caption=(
            "Counts of gene-positive/negative strains by recorded phenotype. "
            "Odds ratio with 95% confidence interval and two-sided Fisher exact p-value "
            "are shown in the report; the figure must not add unrequested data."
        ),
        data=data,
        source=FigureSource(
            session_id=session.session_id,
            run_id=session.run_id,
            stat_sha256=stat_sha256(stat),
            plan_id=session.plan_id,
            data_class=session.data_class,
        ),
        constraints=[
            "counts and statistics must match this spec exactly",
            "show the 95% confidence interval in the legend or panel",
            "use a colorblind-safe palette",
            "prefer vector (PDF/SVG); raster output must be >= 300 dpi",
            "no unrequested samples, genes or phenotypes",
        ],
    )


def build_forest_spec(session: AnalysisSession, stat: StatResult) -> FigureSpec:
    """Forest-plot contract: effect estimates with 95% CIs from the session stat.

    The renderer draws one row per effect; today the association session emits a
    single row, and stratified/logistic specs can add rows later without a
    schema change.
    """
    effects = [
        {
            "label": f"{session.gene} × {session.test_name}",
            "odds_ratio": stat.odds_ratio,
            "ci_low": stat.ci_low,
            "ci_high": stat.ci_high,
            "p_value": stat.p_value,
        }
    ]
    data = {
        "gene": session.gene,
        "test_name": session.test_name,
        "n": stat.n,
        "effects": effects,
        "diagnostics": list(stat.diagnostics),
        "label": session.label or session.status.value,
    }
    return FigureSpec(
        figure_id=f"{session.session_id}-fig-forest",
        recipe_id="forest",
        kind="forest",
        title=f"Forest plot — {session.gene} × {session.test_name}",
        caption=(
            "Odds ratio with 95% confidence interval (log scale) on a dashed "
            "no-effect line at 1.0. Numbers come from the session statistics only."
        ),
        data=data,
        source=FigureSource(
            session_id=session.session_id,
            run_id=session.run_id,
            stat_sha256=stat_sha256(stat),
            plan_id=session.plan_id,
            data_class=session.data_class,
        ),
        constraints=[
            "effect estimates and confidence intervals must match this spec exactly",
            "draw the 95% confidence interval, not just the point estimate",
            "use a log scale for odds ratios with a visible no-effect line at 1.0",
            "use a colorblind-safe palette",
            "prefer vector (PDF/SVG); raster output must be >= 300 dpi",
            "no unrequested samples, genes or phenotypes",
        ],
    )


def build_flow_spec(
    session: AnalysisSession,
    stat: StatResult,
    *,
    run_strains: int,
    cohort_note: str = "",
) -> FigureSpec:
    """STROBE-style flow contract from counts bacmap actually holds.

    ``run_strains`` is the run roster size; the exclusion count is derived, never
    typed in by an agent. ``cohort_note`` is an annotation line, not a data row.
    """
    excluded = max(0, run_strains - stat.n)
    data = {
        "gene": session.gene,
        "test_name": session.test_name,
        "run_strains": run_strains,
        "label": session.label or session.status.value,
        "stages": [
            {"label": "Isolates in run", "n": run_strains},
            {"label": "Analysed (2×2 association)", "n": stat.n},
        ],
        "exclusions": [
            {
                "after": 0,
                "label": "no AMR genotype or usable phenotype",
                "n": excluded,
            }
        ],
        "cohort_note": cohort_note,
    }
    return FigureSpec(
        figure_id=f"{session.session_id}-fig-flow",
        recipe_id="strobe_flow",
        kind="flow",
        title=f"Study flow — {session.gene} × {session.test_name}",
        caption=(
            "Inclusion/exclusion flow with counts from the run roster and the "
            "session statistics (STROBE item 13). The exclusion count is derived; "
            "nothing is estimated or added."
        ),
        data=data,
        source=FigureSource(
            session_id=session.session_id,
            run_id=session.run_id,
            stat_sha256=stat_sha256(stat),
            plan_id=session.plan_id,
            data_class=session.data_class,
        ),
        constraints=[
            "stage and exclusion counts must match this spec exactly",
            "every exclusion box must name its reason",
            "show the run roster, the analysed n and the excluded n",
            "prefer vector (PDF/SVG); raster output must be >= 300 dpi",
            "no unrequested samples, genes or phenotypes",
        ],
    )


def build_artifact(
    spec: FigureSpec,
    output: str | Path,
    *,
    renderer: Renderer,
    code: str | Path | None = None,
    environment: dict[str, str] | None = None,
) -> FigureArtifact:
    """Validate a rendered figure and produce its provenance manifest."""
    output_path = Path(output).expanduser().resolve()
    if not output_path.is_file():
        raise ValueError(f"figure output not found: {output_path}")
    suffix = output_path.suffix.lower().lstrip(".")
    if suffix not in {fmt.lower() for fmt in spec.style.formats}:
        raise ValueError(
            f"output format {suffix!r} is not allowed by the spec "
            f"({', '.join(spec.style.formats)})"
        )
    problems = figure_checks.validate_output(output_path, min_dpi=spec.style.dpi)
    if problems:
        raise ValueError(
            "figure output failed the quality gate (PDF/PNG/SVG checks): "
            + "; ".join(problems)
        )
    code_path = Path(code).expanduser().resolve() if code else None
    if code_path is not None and not code_path.is_file():
        raise ValueError(f"figure script not found: {code_path}")
    return FigureArtifact(
        figure_id=spec.figure_id,
        recipe_id=spec.recipe_id,
        renderer=renderer,
        output=str(output_path),
        output_sha256=sha256_file(output_path),
        spec_sha256=spec_sha256(spec),
        data_sha256=data_sha256(spec),
        code_sha256=sha256_file(code_path) if code_path is not None else "",
        code_path=str(code_path) if code_path is not None else "",
        environment=dict(environment or {}),
        source=spec.source,
        created_at=datetime.now(UTC).isoformat(),
    )


def write_spec(spec: FigureSpec, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        spec.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2
    )
    target.write_text(payload + "\n", encoding="utf-8")
    return target


def load_spec(path: str | Path) -> FigureSpec:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return FigureSpec.model_validate(raw)
