"""Builtin figure recipes 第二批：forest / strobe_flow 渲染与 render_figure 服务。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from bacmap.research.figures import (
    FigureSpec,
    build_flow_spec,
    build_forest_spec,
)
from bacmap.research.models import (
    CreateSessionRequest,
    ResearchError,
    ResearchProfile,
    SessionView,
)
from bacmap.research.render import (
    render_association_svg,
    render_figure_svg,
    render_flow_svg,
    render_forest_svg,
)
from bacmap.research.service import ResearchService
from bacmap.store import runs


def _workflow_dir(home: Path) -> Path:
    wf = home / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 2\niqu_tree_seed: 42\n")
    return wf


def _run(home: Path, strains: list[str], run_id: str = "run-1") -> None:
    wf = _workflow_dir(home)
    run = runs.create_run(
        "bacmap", wf, strains, db_path=home / "runs.sqlite", task_id="task-1"
    )
    assert run.run_id
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute("UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", (run_id, run.run_id))


def _gom(home: Path, genes: dict[str, list[str]]) -> None:
    from bacmap.store.genome_object_service import ensure_gom_schema

    ensure_gom_schema(home / "gom.sqlite")
    with sqlite3.connect(home / "gom.sqlite") as conn:
        for sid, names in genes.items():
            for name in names:
                conn.execute(
                    "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                    " VALUES (?,?,?)",
                    (sid, name, "card"),
                )


def _labs(home: Path, values: dict[str, str]) -> None:
    from bacmap.store.lab_results import LabResultService

    with LabResultService(home / "data" / "bacmap.sqlite") as svc:
        for sid, interp in values.items():
            svc.add(sid, "mic", "meropenem", "0.25", interpretation=interp)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    strains = [f"S{i}" for i in range(16)]
    _run(tmp_path, strains)
    _gom(tmp_path, {s: ["blaKPC-33"] for s in strains[:7]})
    _labs(
        tmp_path,
        {
            **{s: "R" for s in strains[:6]},
            "S6": "S",
            # S7..S8 have no phenotype record -> excluded from the flow
            **{s: "R" for s in strains[9:11]},
            **{s: "S" for s in strains[11:]},
        },
    )
    return tmp_path


def _session(home: Path) -> SessionView:
    return ResearchService(home).create_session(
        CreateSessionRequest(
            run_id="run-1",
            gene="blaKPC-33",
            test_name="meropenem",
            profile=ResearchProfile.RESEARCH,
        ),
        actor="tester",
    )


def _respec(spec: FigureSpec, data: dict) -> FigureSpec:
    """Round-trip a spec with new data (frozen model: rebuild, never mutate)."""
    payload = spec.model_dump(mode="json", by_alias=True)
    payload["data"] = data
    return FigureSpec.model_validate(payload)


class TestAssociationRendererRefactor:
    def test_spec_based_renderer_matches_legacy_signature(self, home: Path):
        view = _session(home)
        service = ResearchService(home)
        spec = service.figure_spec(view.session.session_id)
        assert render_association_svg(spec) == render_figure_svg(
            view.session, view.stat
        )


class TestForest:
    def test_spec_carries_effect_row(self, home: Path):
        view = _session(home)
        spec = build_forest_spec(view.session, view.stat)
        assert spec.recipe_id == "forest"
        assert spec.kind == "forest"
        assert spec.figure_id == f"{view.session.session_id}-fig-forest"
        effect = spec.data["effects"][0]
        assert effect["odds_ratio"] == view.stat.odds_ratio
        assert effect["ci_low"] == view.stat.ci_low
        assert effect["ci_high"] == view.stat.ci_high
        assert spec.source.stat_sha256

    def test_svg_contains_or_ci_and_no_effect_line(self, home: Path):
        view = _session(home)
        svg = render_forest_svg(build_forest_spec(view.session, view.stat))
        assert svg.startswith("<svg")
        assert "Forest plot" in svg
        assert "OR (95% CI)" in svg
        assert "no-effect line at OR = 1" in svg
        assert "blaKPC-33 × meropenem" in svg
        assert 'stroke-dasharray="4 3"' in svg

    def test_svg_handles_missing_estimate(self, home: Path):
        view = _session(home)
        spec = build_forest_spec(view.session, view.stat)
        empty = _respec(spec, {"n": 0, "effects": [{"label": "empty"}]})
        svg = render_forest_svg(empty)
        assert "(NA–NA)" in svg
        assert "empty" in svg


class TestFlow:
    def test_spec_derives_exclusion_from_roster(self, home: Path):
        view = _session(home)
        spec = build_flow_spec(
            view.session, view.stat, run_strains=16, cohort_note="cohort rc-1"
        )
        assert spec.recipe_id == "strobe_flow"
        assert spec.kind == "flow"
        assert spec.data["run_strains"] == 16
        assert spec.data["stages"][0] == {"label": "Isolates in run", "n": 16}
        assert spec.data["stages"][1]["n"] == view.stat.n
        assert spec.data["exclusions"][0]["n"] == 16 - view.stat.n
        assert spec.data["cohort_note"] == "cohort rc-1"

    def test_svg_contains_stage_and_exclusion_counts(self, home: Path):
        view = _session(home)
        spec = build_flow_spec(view.session, view.stat, run_strains=16)
        svg = render_flow_svg(spec)
        assert "Isolates in run" in svg
        assert "Analysed (2×2 association)" in svg
        # the reason label wraps across two lines inside the exclusion box
        assert "no AMR genotype or usable" in svg and "phenotype" in svg
        assert f"n = {16 - view.stat.n}" in svg
        assert "run run-1" in svg

    def test_svg_skips_out_of_range_exclusion(self, home: Path):
        view = _session(home)
        spec = build_flow_spec(view.session, view.stat, run_strains=16)
        data = dict(spec.data)
        data["exclusions"] = [{"after": 5, "label": "zz-out-of-range", "n": 1}]
        svg = render_flow_svg(_respec(spec, data))
        assert "zz-out-of-range" not in svg


class TestRenderService:
    def test_render_forest_registers_artifact_and_ledger(self, home: Path):
        view = _session(home)
        result = ResearchService(home).render_figure(
            view.session.session_id, "forest", actor="tester"
        )
        path = Path(result["path"])
        assert path.name == "figure_forest.svg"
        assert path.is_relative_to(home / "research" / view.session.session_id)
        assert path.read_text(encoding="utf-8").startswith("<svg")
        after = ResearchService(home).get_session(view.session.session_id)
        figures = [a for a in after.artifacts if a.kind.value == "figure"]
        assert str(path) in {a.path for a in figures}
        ledger = ResearchService(home).ledger(view.session.session_id)
        entry = next(e for e in ledger if e["event"] == "figure.rendered")
        detail = json.loads(entry["payload_json"])
        assert detail["recipe_id"] == "forest"
        assert detail["renderer"] == "bacmap-deterministic"
        assert detail["sha256"] == result["sha256"]
        assert len(detail["spec_sha256"]) == 64

    def test_render_flow_derives_counts_from_run_roster(self, home: Path):
        view = _session(home)
        result = ResearchService(home).render_figure(
            view.session.session_id, "strobe_flow"
        )
        svg = Path(result["path"]).read_text(encoding="utf-8")
        assert "Isolates in run" in svg
        assert f"n = {view.stat.n}" in svg

    def test_render_association_bar_matches_session_figure(self, home: Path):
        view = _session(home)
        result = ResearchService(home).render_figure(view.session.session_id)
        original = (home / "research" / view.session.session_id / "figure.svg").read_text(
            encoding="utf-8"
        )
        assert Path(result["path"]).read_text(encoding="utf-8") == original

    def test_render_rejects_planned_and_sandbox_recipes(self, home: Path):
        view = _session(home)
        service = ResearchService(home)
        with pytest.raises(ResearchError) as exc:
            service.render_figure(view.session.session_id, "volcano")
        assert exc.value.code == "validation_error"
        with pytest.raises(ResearchError) as exc:
            service.render_figure(view.session.session_id, "custom")
        assert "sandbox" in exc.value.message
        with pytest.raises(ResearchError) as exc:
            service.render_figure(view.session.session_id, "nope")
        assert exc.value.code == "validation_error"

    def test_render_requires_existing_session(self, home: Path):
        with pytest.raises(ResearchError) as exc:
            ResearchService(home).render_figure("rs-nope", "forest")
        assert exc.value.code == "not_found"


class TestSubmissionPackageIntegration:
    def test_package_keeps_multiple_figures_per_session(self, home: Path):
        from bacmap.research import reporting
        from bacmap.research.service import ResearchObjectService

        objects = ResearchObjectService(home)
        study = objects.create_study("Does blaKPC-33 matter?", "KPN", 2, "tester")
        service = ResearchService(home)
        view = service.create_session(
            CreateSessionRequest(
                run_id="run-1",
                gene="blaKPC-33",
                test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
                study_id=study.study_id,
            ),
            actor="tester",
        )
        service.render_figure(view.session.session_id, "forest", actor="tester")

        out = home / "package"
        package = reporting.build_submission_package(home, study.study_id, out)
        session_dir = out / "artifacts" / view.session.session_id
        bar = session_dir / "figure.svg"
        forest = session_dir / "figure_forest.svg"
        assert bar.is_file() and forest.is_file()
        by_path = {entry.path: entry.sha256 for entry in package.files}
        for target in (bar, forest):
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            assert by_path[str(target)] == digest


class TestFigureTemplate:
    def test_template_is_self_contained_and_honors_contract(self):
        from bacmap.research import figure_template

        content = figure_template.render_template()
        assert "bacmap.figure_spec/1" in content
        assert "matplotlib" in content
        assert "import bacmap" not in content
        assert "figure attach" in content
        target = Path("/tmp/opencode") / "tpl-test" / "figure_script.py"
        written = figure_template.write_template(target)
        assert written == target
        assert target.read_text(encoding="utf-8") == content
        compile(content, "figure_script.py", "exec")

    def test_template_validates_output_format(self, home: Path):
        view = _session(home)
        spec = ResearchService(home).figure_spec(view.session.session_id)
        spec_file = Path("/tmp/opencode") / "tpl-test" / "spec.json"
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        spec_file.write_text(
            spec.model_dump_json(by_alias=True), encoding="utf-8"
        )
        from bacmap.research import figure_template

        script = Path("/tmp/opencode") / "tpl-test" / "figure_script.py"
        figure_template.write_template(script)
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, str(script), "--spec", str(spec_file),
             "--out", str(spec_file.parent / "out.tiff")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode != 0
        assert "not allowed by the spec" in completed.stderr
