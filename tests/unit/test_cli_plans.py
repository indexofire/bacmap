"""``bacmap plan``（v1.5.1，ADR-21 可信确认面）：查看 / 确认提交 / 拒绝。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import bacmap.interfaces.cli.main as cli
from bacmap.application.plans import PlanService, plan_task_id
from bacmap.tasks.params import AnalyzeParams
from bacmap.tasks.spec import TaskId


class _Engine:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, str]] = []

    def submit(self, task_type, params, submitted_by, *, task_id=None):
        self.submitted.append((str(task_id), submitted_by))
        return TaskId(str(task_id))


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(cli, "_engine", lambda home: engine)
    service = PlanService(engine, tmp_path / "tasks.sqlite")
    rec = service.create([AnalyzeParams(samples=["SAM-001"])], "harness rationale", "mcp-x")
    return tmp_path, engine, rec


def _main(capsys, *argv: str) -> str:
    cli.main(list(argv))
    return capsys.readouterr().out


def test_show_and_list_json(env, capsys):
    home, _, rec = env
    shown = json.loads(_main(capsys, "plan", "show", rec.plan_id, "--home", str(home), "--json"))
    assert shown["plan_hash"] == rec.plan_hash and shown["state"] == "awaiting_confirmation"
    listed = json.loads(_main(capsys, "plan", "ls", "--home", str(home), "--json"))
    assert [p["plan_id"] for p in listed] == [rec.plan_id]


def test_show_prints_confirm_command(env, capsys):
    home, _, rec = env
    out = _main(capsys, "plan", "show", rec.plan_id, "--home", str(home))
    assert f"bacmap plan confirm {rec.plan_id} --version 1 --hash {rec.short_hash}" in out


def test_confirm_with_hash_submits(env, capsys):
    home, engine, rec = env
    out = json.loads(
        _main(
            capsys, "plan", "confirm", rec.plan_id, "--version", "1",
            "--hash", rec.short_hash, "--home", str(home), "--json",
        )
    )
    assert out["state"] == "submitted"
    assert engine.submitted[0][0] == plan_task_id(rec.plan_id, 1, 0)
    assert engine.submitted[0][1].startswith("cli:")


def test_confirm_wrong_hash_is_conflict(env):
    home, engine, rec = env
    with pytest.raises(SystemExit, match=r"\[conflict\]"):
        cli.main(["plan", "confirm", rec.plan_id, "--hash", "f" * 12, "--home", str(home)])
    assert engine.submitted == []


def test_interactive_confirm_shows_plan_then_submits(env, monkeypatch, capsys):
    home, engine, rec = env
    import rich.prompt

    monkeypatch.setattr(rich.prompt.Confirm, "ask", classmethod(lambda cls, *a, **k: True))
    out = _main(capsys, "plan", "confirm", rec.plan_id, "--home", str(home))
    assert "SAM-001" in out and len(engine.submitted) == 1


def test_interactive_decline_does_nothing(env, monkeypatch):
    home, engine, rec = env
    import rich.prompt

    monkeypatch.setattr(rich.prompt.Confirm, "ask", classmethod(lambda cls, *a, **k: False))
    with pytest.raises(SystemExit, match="已取消"):
        cli.main(["plan", "confirm", rec.plan_id, "--home", str(home)])
    assert engine.submitted == []


def test_reject(env, capsys):
    home, engine, rec = env
    _main(capsys, "plan", "reject", rec.plan_id, "--version", "1", "--reason", "no", "--home", str(home))
    shown = json.loads(_main(capsys, "plan", "show", rec.plan_id, "--home", str(home), "--json"))
    assert shown["state"] == "rejected" and engine.submitted == []


def test_unknown_plan(env):
    home, _, _ = env
    with pytest.raises(SystemExit, match=r"\[not_found\]"):
        cli.main(["plan", "show", "nope", "--home", str(home)])
