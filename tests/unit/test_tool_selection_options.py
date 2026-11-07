"""bio_tool_selection_options（只读、D0）：AI 选择工具参考数据的选项面。"""

from __future__ import annotations

import json

from bacmap.core.tool_selection_validate import DbCatalogEntry, GmlstScheme
from bacmap.tools import tool_catalog


def _gapit_catalog() -> dict[str, DbCatalogEntry]:
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


def test_options_payload_vpa(monkeypatch):
    monkeypatch.setattr(
        tool_catalog, "fetch_gapit_catalog", lambda **kwargs: _gapit_catalog()
    )
    monkeypatch.setattr(
        tool_catalog, "fetch_gmlst_schemes", lambda **kwargs: _gmlst_catalog()
    )
    payload = tool_catalog.options_payload(
        tool="all", species="VPA", home="/tmp/nonexistent-bacmap-home"
    )
    assert payload["schema"] == "bacmap.tool_selection_options/1"
    assert payload["catalog_available"] is True
    assert payload["gmlst_catalog_available"] is True
    assert [row["code"] for row in payload["species"]] == ["VPA"]
    row = payload["species"][0]
    assert row["defaults"] == ["vpara_virulence"]
    names = {db["name"] for db in row["databases"]}
    assert {"vpara_virulence", "vpa_ok", "vpa_pai"} <= names
    assert row["gmlst"]["effective"]["modes"] == ["mlst", "cgmlst"]
    assert row["gmlst"]["effective"]["schemes"]["cgmlst"] == "vparahaemolyticus_3"


def test_agent_handler_returns_json(monkeypatch):
    monkeypatch.setattr(
        tool_catalog, "fetch_gapit_catalog", lambda **kwargs: _gapit_catalog()
    )
    monkeypatch.setattr(
        tool_catalog, "fetch_gmlst_schemes", lambda **kwargs: _gmlst_catalog()
    )
    raw = tool_catalog.tool_selection_options({"tool": "all", "species": "VPA"})
    payload = json.loads(raw)
    assert payload["schema"] == "bacmap.tool_selection_options/1"
    assert payload["species"][0]["code"] == "VPA"


def test_legacy_handler_alias(monkeypatch):
    monkeypatch.setattr(
        tool_catalog, "fetch_gapit_catalog", lambda **kwargs: _gapit_catalog()
    )
    monkeypatch.setattr(
        tool_catalog, "fetch_gmlst_schemes", lambda **kwargs: _gmlst_catalog()
    )
    raw = tool_catalog.gapit_db_options({"tool": "gapit", "species": "VPA"})
    assert json.loads(raw)["species"][0]["code"] == "VPA"
