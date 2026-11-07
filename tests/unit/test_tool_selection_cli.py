"""bacmap selection CLI：select/show/validate/options（gspec + gmlst）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bacmap.core.tool_selection_validate import DbCatalogEntry, GmlstScheme
from bacmap.interfaces.cli import selection as selection_cli


def _gspec_catalog() -> dict[str, DbCatalogEntry]:
    return {
        "vpara_virulence": DbCatalogEntry(
            name="vpara_virulence", kind="gene", installed=True, source="local"
        ),
        "vpa_ok": DbCatalogEntry(
            name="vpa_ok", kind="cluster", typing=True, installed=True, source="bundled"
        ),
        "vpa_pai": DbCatalogEntry(
            name="vpa_pai", kind="cluster", installed=True, source="bundled"
        ),
    }


def _gmlst_catalog() -> dict[str, GmlstScheme]:
    return {
        "vparahaemolyticus_1": GmlstScheme(
            name="vparahaemolyticus_1", scheme_type="mlst", downloaded=True
        ),
        "vparahaemolyticus_3": GmlstScheme(
            name="vparahaemolyticus_3", scheme_type="cgmlst", downloaded=True
        ),
    }


def _args(tmp_path: Path, **overrides):
    base = {
        "home": str(tmp_path),
        "selection": "",
        "datadir": "",
        "species": "",
        "databases": "",
        "modes": "",
        "schemes": "",
        "from_json": "",
        "from_yaml": "",
        "mode": "replace",
        "yes": True,
        "dry_run": False,
        "json": True,
        "path": "",
        "diff": False,
        "tool": "all",
        "downloaded_only": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _patch_catalogs(monkeypatch) -> None:
    monkeypatch.setattr(
        selection_cli, "fetch_gspec_catalog", lambda **kwargs: _gspec_catalog()
    )
    monkeypatch.setattr(
        selection_cli, "fetch_gmlst_schemes", lambda **kwargs: _gmlst_catalog()
    )


def test_select_gspec_writes_nested_section(tmp_path, monkeypatch, capsys):
    _patch_catalogs(monkeypatch)
    selection_cli.run_selection_select(
        _args(tmp_path, tool="gspec", species="VPA", databases="vpa_ok,vpa_pai")
    )
    target = tmp_path / "config" / "tool_selection.yaml"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "schema: bacmap.tool_selection/1" in text
    assert "gspec:" in text and "vpa_ok" in text and "vpa_pai" in text
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_select_gmlst_writes_modes_and_schemes(tmp_path, monkeypatch, capsys):
    _patch_catalogs(monkeypatch)
    selection_cli.run_selection_select(
        _args(
            tmp_path,
            tool="gmlst",
            species="VPA",
            modes="mlst,cgmlst",
            schemes="mlst=vparahaemolyticus_1,cgmlst=vparahaemolyticus_3",
        )
    )
    target = tmp_path / "config" / "tool_selection.yaml"
    text = target.read_text(encoding="utf-8")
    assert "gmlst:" in text
    assert "vparahaemolyticus_1" in text and "vparahaemolyticus_3" in text
    assert "gspec:" not in text  # this run only edited the gmlst section
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_validate_unknown_database_fails(tmp_path, monkeypatch, capsys):
    _patch_catalogs(monkeypatch)
    target = tmp_path / "tool_selection.yaml"
    target.write_text(
        "schema: bacmap.tool_selection/1\n"
        "species:\n"
        "  VPA:\n"
        "    gspec:\n"
        "      databases: [nope]\n",
        encoding="utf-8",
    )
    try:
        selection_cli.run_selection_validate(_args(tmp_path, path=str(target)))
    except SystemExit as exc:
        assert exc.code == 1
    else:  # pragma: no cover
        raise AssertionError("validate should exit 1")
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "UNKNOWN_DATABASE"


def test_validate_gmlst_unknown_scheme_fails(tmp_path, monkeypatch, capsys):
    _patch_catalogs(monkeypatch)
    target = tmp_path / "tool_selection.yaml"
    target.write_text(
        "schema: bacmap.tool_selection/1\n"
        "species:\n"
        "  VPA:\n"
        "    gmlst:\n"
        "      modes: [cgmlst]\n"
        "      schemes: {cgmlst: nope}\n",
        encoding="utf-8",
    )
    try:
        selection_cli.run_selection_validate(_args(tmp_path, path=str(target)))
    except SystemExit as exc:
        assert exc.code == 1
    else:  # pragma: no cover
        raise AssertionError("validate should exit 1")
    payload = json.loads(capsys.readouterr().out)
    assert any(error["code"] == "UNKNOWN_GMLST_SCHEME" for error in payload["errors"])


def test_select_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    _patch_catalogs(monkeypatch)
    selection_cli.run_selection_select(
        _args(
            tmp_path,
            tool="gspec",
            species="VPA",
            databases="vpa_ok",
            dry_run=True,
        )
    )
    assert not (tmp_path / "config" / "tool_selection.yaml").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "bacmap.tool_selection_proposal/1"
    assert "vpa_ok" in payload["yaml"]


def test_show_diff_json(tmp_path, monkeypatch, capsys):
    _patch_catalogs(monkeypatch)
    selection_cli.run_selection_select(
        _args(tmp_path, tool="gspec", species="VPA", databases="vpa_ok")
    )
    capsys.readouterr()
    selection_cli.run_selection_show(_args(tmp_path, diff=True))
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "bacmap.tool_selection_show/1"
    diff = payload["diff"]
    assert [row["code"] for row in diff["species"]] == ["VPA"]
    assert diff["species"][0]["added"] == ["vpa_ok"]


def test_options_json_uses_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        selection_cli,
        "options_payload",
        lambda **kwargs: {
            "schema": "bacmap.tool_selection_options/1",
            "catalog_available": True,
            "gmlst_catalog_available": True,
            "species": [],
        },
    )
    selection_cli.run_selection_options(_args(tmp_path, species="VPA"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "bacmap.tool_selection_options/1"
