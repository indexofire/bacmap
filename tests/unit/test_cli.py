"""bacmap 控制台命令冒烟（参数解析层，不启动服务器）。"""

from __future__ import annotations

import sys

import pytest

from bacmap.interfaces.cli.main import main


def test_version_prints_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["bacmap", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "bacmap" in capsys.readouterr().out


def test_missing_subcommand_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["bacmap"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_mcp_help_lists_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["bacmap", "mcp", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--read-only" in out
    assert "--home" in out


def test_task_submit_help_lists_flags(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bacmap", "task", "submit", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--samples" in out and "--type" in out and "--scope" in out


def test_overview_and_sample_ls_json(tmp_path, monkeypatch):
    import argparse
    import json

    from bacmap.interfaces.cli.main import _run_overview, _run_sample_ls

    rep = tmp_path / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(
        json.dumps(
            {
                "sample": "SAM-001",
                "steps": {
                    "species": {"verdict": "Salmonella"},
                    "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
                    "serotype": {"sistr": "Typhimurium"},
                    "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
                },
            }
        )
    )
    # 用 print 收集器而非 capsys：避免 DBOS 日志处理器绑定到被关闭的捕获流
    out: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a)))
    try:
        _run_overview(argparse.Namespace(home=str(tmp_path), json=True))
        ov = json.loads(out[-1])
        assert ov["paths"]["BACMAP_HOME"] == str(tmp_path)

        out.clear()
        _run_sample_ls(argparse.Namespace(home=str(tmp_path), json=True))
        rows = json.loads(out[-1])
        assert [r["sample_id"] for r in rows] == ["SAM-001"]
        assert rows[0]["st"] == "19"
    finally:
        import bacmap.tasks.engine.dbos_engine as eng

        eng.shutdown_dbos()


def test_task_submit_rejects_unknown_type(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bacmap", "task", "submit", "--type", "mine"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2  # argparse choices 拒绝


def test_task_show_unknown_task_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["bacmap", "task", "show", "nope", "--home", str(tmp_path)]
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert "任务不存在" in str(exc.value)
    import bacmap.tasks.engine.dbos_engine as eng

    eng.shutdown_dbos()


def test_task_submit_rejects_traversal_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["bacmap", "task", "submit", "--type", "analyze", "--samples", "../evil",
         "--home", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert "提交失败" in str(exc.value)
    import bacmap.tasks.engine.dbos_engine as eng

    eng.shutdown_dbos()


def test_ask_help_lists_flags(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bacmap", "ask", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "--yes" in capsys.readouterr().out


def test_ask_json_shows_plan(tmp_path, monkeypatch):
    import argparse
    import json

    from bacmap.agent.session import AgentReply, AnalysisPlan, PlannedTask
    from bacmap.interfaces import assistant as A
    from bacmap.interfaces.cli.main import _run_ask

    class _FakeSession:
        def respond(self, text):
            return AgentReply(
                message="规划完成",
                plan=AnalysisPlan(
                    reply="规划完成",
                    tasks=[PlannedTask(task_type="analyze", params={"samples": ["SAM-001"]})],
                ),
            )

    monkeypatch.setattr(A, "build_session", lambda engine, submitted_by="assistant": _FakeSession())
    out: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a))))
    try:
        _run_ask(
            argparse.Namespace(
                home=str(tmp_path), text="跑 SAM-001", json=True, yes=False, by="cli"
            )
        )
        data = json.loads(out[-1])
        assert data["plan"]["tasks"][0]["task_type"] == "analyze"
    finally:
        import bacmap.tasks.engine.dbos_engine as eng

        eng.shutdown_dbos()
