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
