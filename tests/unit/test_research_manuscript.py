"""P5：英文 IMRAD 稿、数字审计与导出命名。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bacmap.interfaces.cli import research_dag as cli
from bacmap.research.dagstore import DagStore
from bacmap.research.models import StatResult
from bacmap.research.numeric_audit import audit_numbers
from bacmap.research.operators import get_operator
from bacmap.research.operators.spec import OperatorContext
from bacmap.research.report_dag import render_imrad_manuscript

STAT = StatResult(
    session_id="",
    table={
        "gene_pos_resistant": 3,
        "gene_pos_susceptible": 0,
        "gene_neg_resistant": 0,
        "gene_neg_susceptible": 2,
    },
    odds_ratio=35.0,
    ci_low=0.50,
    ci_high=2435.69,
    p_value=0.1,
    n=5,
    diagnostics=["zero cell(s): Haldane-Anscombe 0.5 correction applied to OR/CI"],
)


def _render(stat: StatResult = STAT) -> dict:
    return render_imrad_manuscript(
        run_id="run-1",
        gene="blaCTX-M-15",
        drug="meropenem",
        stat=stat,
        table_artifact="sha256:abc",
        figure_artifact="sha256:def",
    )


def test_imrad_sections_and_numbers() -> None:
    rendered = _render()
    md = rendered["markdown"]
    for heading in ("## Abstract", "## Introduction", "## Methods", "## Results", "## Discussion"):
        assert heading in md
    assert "blaCTX-M-15" in md
    assert "meropenem" in md
    assert "OR was 35.00" in md
    assert "95% CI 0.50–2435.69" in md
    assert rendered["slots"]["n"] == 5


def test_imrad_numbers_pass_audit() -> None:
    rendered = _render()
    assert audit_numbers(rendered["markdown"], rendered["slots"]) == []


def test_imrad_small_p_value_passes_audit() -> None:
    stat = STAT.model_copy(update={"p_value": 0.0001})
    rendered = _render(stat)
    assert "<0.001" in rendered["markdown"]
    assert audit_numbers(rendered["markdown"], rendered["slots"]) == []


def test_imrad_claims_carry_evidence() -> None:
    rendered = _render()
    assert rendered["claims"]
    assert all(claim["evidence"] for claim in rendered["claims"])


def test_manuscript_operator(tmp_path: Path) -> None:
    ctx = OperatorContext(
        home=tmp_path,
        task_id="t1",
        node_id="m",
        params={"template": "imrad-en", "title": ""},
        inputs={
            "table": {
                "run_id": "run-1",
                "gene": "blaCTX-M-15",
                "test_name": "meropenem",
                "stat": STAT.model_dump(mode="json"),
            },
            "figure": {"format": "svg", "data": "<svg/>"},
        },
        input_artifacts={"table": "sha256:abc", "figure": "sha256:def"},
        workdir=tmp_path,
    )
    out = get_operator("text.manuscript@1.0").fn(ctx)
    text = out["text"]
    assert text["template"] == "imrad-en"
    assert text["audit"]["ok"] is True
    assert "## Results" in text["markdown"]


def test_export_names_manuscript(tmp_path: Path) -> None:
    with DagStore(tmp_path) as store:
        store.ensure_run("t1", "hash", 2)
        store.put_artifact(
            type_="Text",
            value={"template": "imrad-en", "markdown": "# Manuscript"},
            task_id="t1",
            node_id="m",
        )
    out_dir = tmp_path / "export"
    cli.run_export(
        argparse.Namespace(home=str(tmp_path), task_id="t1", out=str(out_dir), json=True)
    )
    assert (out_dir / "manuscript.md").read_text(encoding="utf-8").startswith("# Manuscript")
    provenance = json.loads((out_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["template"] == "imrad-en"
