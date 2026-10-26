"""``bacmap record``（v1.7）：记录类任务只经任务层提交。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import bacmap.interfaces.cli.main as cli


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []
        self.error: ValueError | None = None

    def submit(self, task_type, params, submitted_by):
        self.calls.append((str(task_type), dict(params), submitted_by))
        if self.error is not None:
            raise self.error
        return "t" * 32


@pytest.fixture
def engine(monkeypatch):
    e = _Engine()
    monkeypatch.setattr(cli, "_engine", lambda home: e)
    return e


def _run(capsys, *argv: str) -> str:
    cli.main(list(argv))
    return capsys.readouterr().out


def test_metadata_record(engine, capsys, tmp_path: Path):
    out = _run(
        capsys, "record", "metadata", "--strain-id", "S1",
        "--field", "province=Guangdong", "--field", "sample_source=food",
        "--home", str(tmp_path), "--json",
    )
    assert json.loads(out)["kind"] == "metadata"
    kind, params, by = engine.calls[0]
    assert kind == "record"
    assert params["strain_id"] == "S1" and params["sample_id"] == "S1"
    assert params["fields"] == {"province": "Guangdong", "sample_source": "food"}
    assert params["kind"] == "metadata" and by == "cli"


def test_lab_record(engine, capsys, tmp_path: Path):
    _run(
        capsys, "record", "lab", "--strain-id", "S1", "--category", "mic",
        "--test-name", "meropenem", "--result", "0.25", "--unit", "mg/L",
        "--home", str(tmp_path),
    )
    params = engine.calls[0][1]
    assert params["kind"] == "lab_result" and params["unit"] == "mg/L"
    assert "result" in params and params["category"] == "mic"


def test_knowledge_import_and_approve(engine, capsys, tmp_path: Path):
    _run(
        capsys, "record", "knowledge-import", "--title", "Paper",
        "--identifier", "PMID:123", "--year", "2025", "--home", str(tmp_path),
    )
    params = engine.calls[0][1]
    assert params["kind"] == "knowledge_import" and params["entry_kind"] == "literature"
    assert "authors" not in params  # 空值不提交，交由模型默认

    _run(capsys, "record", "knowledge-approve", "7", "--home", str(tmp_path), "--json")
    assert engine.calls[1][1] == {"entry_id": 7, "kind": "knowledge_approve"}


def test_bad_field_and_engine_error(engine, capsys, tmp_path: Path):
    with pytest.raises(SystemExit, match="k=v"):
        _run(capsys, "record", "metadata", "--strain-id", "S1", "--field", "province",
             "--home", str(tmp_path))
    engine.error = ValueError("invalid record: metadata.strain_id: Field required")
    with pytest.raises(SystemExit, match="提交失败"):
        _run(capsys, "record", "metadata", "--strain-id", "S1", "--home", str(tmp_path))


def test_record_is_in_help(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["bacmap", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "record" in out and "task" in out
