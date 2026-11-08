"""CLI 研究对象的端到端冒烟（不启动 DBOS/Web）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bacmap.interfaces.cli.main import main


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["bacmap", *argv])
    code = 0
    message = ""
    try:
        main()
    except SystemExit as exc:
        if isinstance(exc.code, int):
            code = exc.code
        else:
            code = 1
            message = str(exc.code)
    out, err = capsys.readouterr()
    return code, out, err + message


def test_research_object_lifecycle_via_cli(tmp_path: Path, monkeypatch, capsys):
    home = str(tmp_path)

    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "study", "create", "--question", "KPC vs meropenem",
         "--pathogen", "KPN", "--home", home, "--json"],
    )
    assert code == 0
    study_id = json.loads(out)["study_id"]

    members = tmp_path / "members.json"
    members.write_text(
        json.dumps([{"isolate_id": "I1", "run_id": "run-1"}]), encoding="utf-8"
    )
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "cohort", "create", "--study", study_id, "--name", "discovery",
         "--members", str(members), "--home", home, "--json"],
    )
    assert code == 0
    cohort_id = json.loads(out)["cohort_id"]

    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "cohort", "freeze", cohort_id, "--home", home, "--json"],
    )
    assert code == 0 and json.loads(out)["status"] == "frozen"

    spec = json.dumps({"run_id": "run-1", "gene": "blaKPC", "test_name": "meropenem"})
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "plan", "create", "--study", study_id, "--cohort", cohort_id,
         "--spec", spec, "--home", home, "--json"],
    )
    assert code == 0
    plan_id = json.loads(out)["plan_id"]
    _run(
        monkeypatch, capsys,
        ["research", "plan", "freeze", plan_id, "--home", home, "--json"],
    )

    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "experiment", "record", "--plan", plan_id, "--status", "success",
         "--run-id", "run-1", "--outcome", '{"n":16}', "--home", home, "--json"],
    )
    assert code == 0 and json.loads(out)["status"] == "success"

    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "claim", "create", "--study", study_id, "--type", "association",
         "--wording", "blaKPC is associated with meropenem resistance", "--level", "E2",
         "--evidence", '{"run_id":"run-1"}', "--home", home, "--json"],
    )
    assert code == 0
    claim_id = json.loads(out)["claim_id"]
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "claim", "review", claim_id, "--decision", "approve",
         "--home", home, "--json"],
    )
    assert code == 0 and json.loads(out)["status"] == "approved_for_export"

    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "publication", study_id, "--home", home, "--json"],
    )
    assert code == 0
    report = json.loads(out)
    assert report["ready"] is True, report


def test_cohort_preview_reports_missing_run(tmp_path: Path, monkeypatch, capsys):
    home = str(tmp_path)
    _, out, _ = _run(
        monkeypatch, capsys,
        ["research", "study", "create", "--question", "q", "--home", home, "--json"],
    )
    study_id = json.loads(out)["study_id"]
    members = tmp_path / "members.json"
    members.write_text(
        json.dumps([{"isolate_id": "I1", "run_id": "missing-run"}]), encoding="utf-8"
    )
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "cohort", "preview", "--study", study_id,
         "--members", str(members), "--home", home],
    )
    assert code == 0
    assert json.loads(out)["missing_runs"] == ["missing-run"]


def test_experiment_deviation_requires_note(tmp_path: Path, monkeypatch, capsys):
    home = str(tmp_path)
    _, out, _ = _run(
        monkeypatch, capsys,
        ["research", "study", "create", "--question", "q", "--home", home, "--json"],
    )
    study_id = json.loads(out)["study_id"]
    members = tmp_path / "members.json"
    members.write_text(json.dumps([{"isolate_id": "I1"}]), encoding="utf-8")
    _, out, _ = _run(
        monkeypatch, capsys,
        ["research", "cohort", "create", "--study", study_id,
         "--members", str(members), "--home", home, "--json"],
    )
    cohort_id = json.loads(out)["cohort_id"]
    _run(monkeypatch, capsys,
         ["research", "cohort", "freeze", cohort_id, "--home", home, "--json"])
    _, out, _ = _run(
        monkeypatch, capsys,
        ["research", "plan", "create", "--study", study_id, "--cohort", cohort_id,
         "--spec", '{"endpoint":"mic"}', "--home", home, "--json"],
    )
    plan_id = json.loads(out)["plan_id"]
    _run(monkeypatch, capsys,
         ["research", "plan", "freeze", plan_id, "--home", home, "--json"])
    code, _, err = _run(
        monkeypatch, capsys,
        ["research", "experiment", "record", "--plan", plan_id, "--status", "deviated",
         "--home", home],
    )
    assert code != 0
    assert "deviation" in err


def test_outbreak_sensitivity_and_explore_cli(tmp_path: Path, monkeypatch, capsys):
    home = str(tmp_path)
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            [
                {"case_id": f"R{i}", "event_date": "2020-01-01", "location": "W",
                 "source": "A", "phenotype": "Resistant"}
                for i in range(6)
            ]
            + [
                {"case_id": f"S{i}", "event_date": "2020-02-01", "location": "W",
                 "source": "B", "phenotype": "Susceptible"}
                for i in range(6)
            ]
        ),
        encoding="utf-8",
    )
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "outbreak", "--events", str(events), "--min-count", "5",
         "--home", home],
    )
    assert code == 0
    report = json.loads(out)
    assert report["n_events"] == 12
    assert report["n_clusters"] == 2

    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "sensitivity", "--table", "20,2,2,20",
         "--strata", '[["A",10,1,1,10],["B",10,1,1,10]]', "--home", home],
    )
    assert code == 0
    assert json.loads(out)["adjusted"]["method"] == "Mantel-Haenszel"

    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps([{"exposure": "KPC", "outcome": "meropenem",
                     "table": [20, 2, 2, 20]}]), encoding="utf-8"
    )
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "explore", "--study", "study-cli", "--cases", str(cases),
         "--min-n", "10", "--home", home],
    )
    assert code == 0
    explore = json.loads(out)
    assert explore["role"] == "screening"
    assert explore["candidates"][0]["exposure"] == "KPC"


def test_research_figure_recipes_cli(monkeypatch, capsys):
    code, out, _ = _run(
        monkeypatch, capsys, ["research", "figure", "recipes", "--json"]
    )
    assert code == 0
    ids = {item["recipe_id"] for item in json.loads(out)}
    assert {"association_bar", "tree_rectangular", "custom"} <= ids


def test_research_figure_runtimes_cli(monkeypatch, capsys):
    code, out, _ = _run(
        monkeypatch, capsys, ["research", "figure", "runtimes", "--json"]
    )
    assert code == 0
    items = {item["recipe_id"]: item for item in json.loads(out)}
    assert items["association_bar"]["available"] is True
    assert items["tree_rectangular"]["runtime"]["kind"] == "container"


def test_research_package_cli(tmp_path: Path, monkeypatch, capsys):
    home = str(tmp_path)
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "study", "create", "--question", "q", "--home", home, "--json"],
    )
    assert code == 0
    study_id = json.loads(out)["study_id"]
    outdir = tmp_path / "package"
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "package", study_id, "--out", str(outdir),
         "--home", home, "--json"],
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["schema"] == "bacmap.submission_package/1"
    assert (outdir / "submission_manifest.json").is_file()


def test_research_stats_logistic_cli(tmp_path: Path, monkeypatch, capsys):
    table = tmp_path / "cohort.csv"
    rows = ["dose,outcome"]
    values = [0, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    for index, outcome in enumerate(values):
        rows.append(f"{index - 5},{outcome}")
    table.write_text("\n".join(rows) + "\n", encoding="utf-8")
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "stats", "logistic", "--data", str(table),
         "--outcome", "outcome", "--predictors", "dose", "--json"],
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["schema"] == "bacmap.logistic_regression/1"
    assert payload["result"]["converged"] is True


def _seed_home(tmp_path: Path) -> str:
    """Seed a minimal home so `research create` can compute a real stat."""
    import sqlite3

    from bacmap.store import runs as runs_store
    from bacmap.store.genome_object_service import ensure_gom_schema
    from bacmap.store.lab_results import LabResultService

    home = tmp_path
    wf = home / "workflows" / "bacmap" / "config"
    wf.mkdir(parents=True)
    (wf / "config.yaml").write_text("threads: 2\niqu_tree_seed: 42\n")
    run = runs_store.create_run(
        "bacmap", home / "workflows" / "bacmap", [f"S{i}" for i in range(12)],
        db_path=home / "runs.sqlite", task_id="task-1",
    )
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute(
            "UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", ("run-1", run.run_id)
        )
    ensure_gom_schema(home / "gom.sqlite")
    with sqlite3.connect(home / "gom.sqlite") as conn:
        for sid in [f"S{i}" for i in range(5)]:
            conn.execute(
                "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                " VALUES (?,?,?)",
                (sid, "blaKPC-33", "card"),
            )
    with LabResultService(home / "data" / "bacmap.sqlite") as svc:
        for sid in [f"S{i}" for i in range(4)]:
            svc.add(sid, "mic", "meropenem", "0.25", interpretation="R")
        for sid in [f"S{i}" for i in range(4, 12)]:
            svc.add(sid, "mic", "meropenem", "0.25", interpretation="S")
    return str(home)


def test_research_figure_render_cli(tmp_path: Path, monkeypatch, capsys):
    home = _seed_home(tmp_path)
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "create", "--run-id", "run-1", "--gene", "blaKPC-33",
         "--test-name", "meropenem", "--home", home, "--json"],
    )
    assert code == 0
    session_id = json.loads(out)["session"]["session_id"]

    for recipe in ("forest", "strobe_flow", "association_bar"):
        code, out, _ = _run(
            monkeypatch, capsys,
            ["research", "figure", "render", session_id, "--recipe", recipe,
             "--home", home, "--json"],
        )
        assert code == 0
        payload = json.loads(out)
        assert payload["recipe_id"] == recipe
        assert (tmp_path / "research" / session_id / f"figure_{recipe}.svg").is_file()

    code, _, err = _run(
        monkeypatch, capsys,
        ["research", "figure", "render", session_id, "--recipe", "volcano",
         "--home", home, "--json"],
    )
    assert code != 0
    assert "planned" in err


def test_research_figure_template_cli(tmp_path: Path, monkeypatch, capsys):
    target = tmp_path / "figure_script.py"
    code, out, _ = _run(
        monkeypatch, capsys,
        ["research", "figure", "template", "--output", str(target), "--json"],
    )
    assert code == 0
    assert json.loads(out)["path"] == str(target)
    content = target.read_text(encoding="utf-8")
    assert "bacmap.figure_spec/1" in content

    code, out, _ = _run(monkeypatch, capsys, ["research", "figure", "template"])
    assert code == 0
    assert "matplotlib" in out
