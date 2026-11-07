"""``bacmap agent`` CLI: list/export/install/doctor."""

from __future__ import annotations

import json
from pathlib import Path

from bacmap.interfaces.cli.main import main


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = 0
    message = ""
    try:
        main(argv)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            code = 1
            message = exc.code
        else:
            code = int(exc.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err + message


def test_agent_list_json(capsys):
    code, out, _ = _run(["agent", "list", "--json"], capsys)
    assert code == 0
    names = {item["name"] for item in json.loads(out)}
    assert {"hermes", "pi", "dsh", "generic"} <= names


def test_agent_export_instructions(capsys):
    code, out, _ = _run(["agent", "export", "--harness", "pi"], capsys)
    assert code == 0
    assert "bacmap operating rules" in out
    assert "bacmap_role_analyst" in out


def test_agent_export_mcp_config(capsys):
    code, out, _ = _run(
        ["agent", "export", "--harness", "hermes", "--format", "mcp-config"], capsys
    )
    assert code == 0
    assert "mcp_servers:" in out
    assert "start" in out


def test_agent_export_skill(capsys):
    code, out, _ = _run(
        ["agent", "export", "--harness", "pi", "--format", "skill", "--role", "analyst"],
        capsys,
    )
    assert code == 0
    assert out.startswith("---")
    assert "name: analyst" in out


def test_agent_install_and_doctor(tmp_path: Path, capsys):
    code, out, _ = _run(
        [
            "agent",
            "install",
            "--harness",
            "generic",
            "--target",
            str(tmp_path),
            "--json",
        ],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["harness"] == "generic"
    assert Path(payload["instructions"]).is_file()
    code, out, _ = _run(["agent", "doctor", "--target", str(tmp_path), "--json"], capsys)
    assert code == 0
    assert json.loads(out)["ok"] is True


def test_agent_install_unknown_harness(capsys):
    code, _, err = _run(
        ["agent", "install", "--harness", "nope", "--target", "/tmp"], capsys
    )
    assert code != 0
    assert "unknown harness" in err


def test_agent_doctor_missing_manifest(tmp_path: Path, capsys):
    code, out, _ = _run(["agent", "doctor", "--target", str(tmp_path), "--json"], capsys)
    assert code == 0
    assert json.loads(out)["ok"] is False
