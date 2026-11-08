"""物种→工具参考数据覆盖（bacmap.tool_selection/1）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bacmap.core.tool_selection import (
    GapitSelection,
    GmlstSelection,
    SampleSelection,
    SelectionError,
    SpeciesSelection,
    ToolSelection,
    load_selection,
    load_selection_data,
    selection_to_yaml,
    write_selection,
)
from bacmap.core.tool_selection_validate import (
    DbCatalogEntry,
    GmlstScheme,
    build_options,
    catalog_hash,
    diff_against_defaults,
    gmlst_catalog_hash,
    parse_catalog,
    parse_gmlst_schemes,
    validate_selection,
)


def _gspec_catalog() -> dict[str, DbCatalogEntry]:
    return {
        "vpa_vf": DbCatalogEntry(
            name="vpa_vf",
            kind="gene",
            typing=False,
            installed=True,
            source="catalog",
        ),
        "vpara_virulence": DbCatalogEntry(
            name="vpara_virulence",
            kind="gene",
            typing=False,
            installed=True,
            source="local",
        ),
        "vpa_ok": DbCatalogEntry(
            name="vpa_ok",
            kind="cluster",
            typing=True,
            installed=True,
            source="bundled",
            license="MIT",
        ),
        "vpa_pai": DbCatalogEntry(
            name="vpa_pai",
            kind="cluster",
            typing=False,
            installed=False,
            source="bundled",
        ),
        "card": DbCatalogEntry(
            name="card",
            kind="gene",
            typing=False,
            installed=False,
            source="",
            license="non-commercial",
        ),
    }


def _gmlst_catalog() -> dict[str, GmlstScheme]:
    return {
        "vparahaemolyticus_1": GmlstScheme(
            name="vparahaemolyticus_1",
            organism="Vibrio parahaemolyticus",
            scheme_type="mlst",
            downloaded=True,
        ),
        "vparahaemolyticus_3": GmlstScheme(
            name="vparahaemolyticus_3",
            organism="Vibrio parahaemolyticus",
            scheme_type="cgmlst",
            downloaded=True,
        ),
        "vparahaemolyticus_wg": GmlstScheme(
            name="vparahaemolyticus_wg",
            organism="Vibrio parahaemolyticus",
            scheme_type="wgmlst",
            downloaded=False,
        ),
    }


class TestGapitMerge:
    def test_empty_uses_registry_defaults(self):
        selection = ToolSelection()
        assert selection.effective_gspec_databases("VPA") == [
            "vpa_vf",
            "vpa_ok",
            "vpa_pai",
        ]

    def test_replace(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="replace", databases=["vpa_ok", "vpa_pai"])
                )
            }
        )
        assert selection.effective_gspec_databases("VPA") == ["vpa_ok", "vpa_pai"]

    def test_extend_keeps_defaults(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="extend", databases=["vpa_ok"])
                )
            }
        )
        assert selection.effective_gspec_databases("VPA") == [
            "vpa_vf",
            "vpa_ok",
            "vpa_pai",
        ]

    def test_sample_override_wins(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="replace", databases=["vpa_ok"])
                )
            },
            samples={
                "S1": SampleSelection(gspec=GapitSelection(databases=["vpa_pai"]))
            },
        )
        assert selection.effective_gspec_databases("VPA", sample="S1") == ["vpa_pai"]

    def test_unknown_code_has_no_defaults(self):
        assert ToolSelection().effective_gspec_databases("UNK") == []


class TestGmlstMerge:
    def test_default_plan(self):
        plan = ToolSelection().effective_gmlst("VPA")
        assert plan.modes == ["mlst", "cgmlst"]
        assert plan.schemes == {
            "mlst": "vparahaemolyticus_1",
            "cgmlst": "vparahaemolyticus_3",
        }

    def test_replace_modes_and_schemes(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        mode="replace",
                        modes=["cgmlst"],
                        schemes={"cgmlst": "vparahaemolyticus_3"},
                    )
                )
            }
        )
        plan = selection.effective_gmlst("VPA")
        assert plan.modes == ["cgmlst"]
        assert plan.schemes["cgmlst"] == "vparahaemolyticus_3"
        assert plan.schemes["mlst"] == "vparahaemolyticus_1"  # inherited scheme

    def test_extend_adds_tgmlst(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(mode="extend", modes=["tgmlst"])
                )
            }
        )
        assert selection.effective_gmlst("VPA").modes == [
            "mlst",
            "cgmlst",
            "tgmlst",
        ]

    def test_sample_override_inherits_species_schemes(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        mode="replace",
                        modes=["cgmlst"],
                        schemes={"cgmlst": "vparahaemolyticus_3"},
                    )
                )
            },
            samples={
                "S1": SampleSelection(
                    gmlst=GmlstSelection(modes=["tgmlst"])
                )
            },
        )
        plan = selection.effective_gmlst("VPA", sample="S1")
        assert plan.modes == ["cgmlst", "tgmlst"]
        assert plan.schemes["cgmlst"] == "vparahaemolyticus_3"

    def test_unknown_code_has_empty_plan(self):
        plan = ToolSelection().effective_gmlst("UNK")
        assert plan.modes == [] and plan.schemes == {}


class TestLoadWrite:
    def test_roundtrip_and_deterministic(self, tmp_path: Path):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(
                        mode="replace", databases=["vpa_ok", "vpa_pai"]
                    ),
                    gmlst=GmlstSelection(
                        mode="replace",
                        modes=["cgmlst"],
                        schemes={"cgmlst": "vparahaemolyticus_3"},
                    ),
                ),
                "ECO": SpeciesSelection(
                    gspec=GapitSelection(mode="extend", databases=["ecoh"])
                ),
            },
            samples={
                "S1": SampleSelection(gspec=GapitSelection(databases=["vpa_ok"]))
            },
        )
        target = tmp_path / "config" / "tool_selection.yaml"
        write_selection(selection, target)
        loaded = load_selection(target)
        assert loaded.effective_gspec_databases("VPA") == ["vpa_ok", "vpa_pai"]
        assert loaded.effective_gmlst("VPA").modes == ["cgmlst"]
        assert loaded.effective_gspec_databases("ECO") == ["eco_dec", "ecoh"]
        text = target.read_text(encoding="utf-8")
        assert text == selection_to_yaml(loaded)
        assert yaml.safe_load(text)["schema"] == "bacmap.tool_selection/1"

    def test_backup_keeps_previous(self, tmp_path: Path):
        target = tmp_path / "tool_selection.yaml"
        write_selection(ToolSelection(), target)
        first = target.read_text(encoding="utf-8")
        write_selection(
            ToolSelection(
                species={
                    "VPA": SpeciesSelection(
                        gspec=GapitSelection(databases=["vpa_ok"])
                    )
                }
            ),
            target,
        )
        assert (tmp_path / "tool_selection.yaml.bak").read_text(
            encoding="utf-8"
        ) == first

    def test_missing_file_is_empty(self, tmp_path: Path):
        assert load_selection(tmp_path / "nope.yaml") == ToolSelection()

    def test_legacy_shape_translates(self):
        selection = load_selection_data(
            {
                "schema": "bacmap.db_selection/1",
                "defaults": {"mode": "replace"},
                "species": {"VPA": {"databases": ["vpa_ok"]}},
            }
        )
        assert selection.effective_gspec_databases("VPA") == ["vpa_ok"]
        assert selection.defaults.gspec.mode == "replace"

    def test_list_shorthand_extends_gspec(self):
        selection = load_selection_data({"species": {"VPA": ["vpa_ok"]}})
        assert selection.effective_gspec_databases("VPA") == [
            "vpa_vf",
            "vpa_ok",
            "vpa_pai",
        ]

    def test_unknown_field_rejected(self):
        with pytest.raises(SelectionError):
            load_selection_data(
                {"schema": "bacmap.tool_selection/1", "species": {"VPA": {"oops": 1}}}
            )


class TestGapitValidation:
    def test_unknown_species(self):
        selection = ToolSelection(
            species={
                "XXX": SpeciesSelection(gspec=GapitSelection(databases=["card"]))
            }
        )
        report = validate_selection(selection, catalog=_gspec_catalog())
        assert not report.ok
        assert any(issue.code == "UNKNOWN_SPECIES" for issue in report.errors)

    def test_unknown_database(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(gspec=GapitSelection(databases=["nope"]))
            }
        )
        report = validate_selection(selection, catalog=_gspec_catalog())
        assert not report.ok
        assert any(issue.code == "UNKNOWN_DATABASE" for issue in report.errors)

    def test_unsafe_database_name_rejected(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(gspec=GapitSelection(databases=["../escape"]))
            }
        )
        report = validate_selection(selection, catalog=_gspec_catalog())
        assert not report.ok
        assert any(issue.code == "INVALID_DATABASE_NAME" for issue in report.errors)

    def test_bundled_not_installed_is_fine(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(gspec=GapitSelection(databases=["vpa_pai"]))
            }
        )
        report = validate_selection(selection, catalog=_gspec_catalog())
        assert report.ok
        assert not any(issue.code == "DATABASE_NOT_INSTALLED" for issue in report.warnings)

    def test_provider_not_installed_warns(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(gspec=GapitSelection(databases=["card"]))
            }
        )
        report = validate_selection(selection, catalog=_gspec_catalog())
        assert any(issue.code == "DATABASE_NOT_INSTALLED" for issue in report.warnings)
        assert any(issue.code == "LICENSE_REVIEW" for issue in report.warnings)


class TestGmlstValidation:
    def test_unknown_scheme(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        modes=["cgmlst"], schemes={"cgmlst": "nope"}
                    )
                )
            }
        )
        report = validate_selection(
            selection, gmlst_catalog=_gmlst_catalog()
        )
        assert not report.ok
        assert any(issue.code == "UNKNOWN_GMLST_SCHEME" for issue in report.errors)

    def test_scheme_type_mismatch(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        modes=["mlst"], schemes={"mlst": "vparahaemolyticus_3"}
                    )
                )
            }
        )
        report = validate_selection(
            selection, gmlst_catalog=_gmlst_catalog()
        )
        assert any(issue.code == "GMLST_SCHEME_TYPE" for issue in report.errors)

    def test_not_downloaded_warns(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        mode="replace",
                        modes=["wgmlst"],
                        schemes={"wgmlst": "vparahaemolyticus_wg"},
                    )
                )
            }
        )
        report = validate_selection(
            selection, gmlst_catalog=_gmlst_catalog()
        )
        assert report.ok
        assert any(
            issue.code == "GMLST_SCHEME_NOT_DOWNLOADED" for issue in report.warnings
        )

    def test_cgmlst_wgmlst_conflict(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        modes=["cgmlst", "wgmlst"],
                        schemes={
                            "cgmlst": "vparahaemolyticus_3",
                            "wgmlst": "vparahaemolyticus_wg",
                        },
                    )
                )
            }
        )
        report = validate_selection(
            selection, gmlst_catalog=_gmlst_catalog()
        )
        assert any(issue.code == "GMLST_MODE_CONFLICT" for issue in report.errors)

    def test_tgmlst_has_no_scheme(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(
                        modes=["tgmlst"], schemes={"tgmlst": "x"}
                    )
                )
            }
        )
        report = validate_selection(
            selection, gmlst_catalog=_gmlst_catalog()
        )
        assert any(issue.code == "GMLST_TGMLST_SCHEME" for issue in report.errors)

    def test_missing_scheme_for_mode(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gmlst=GmlstSelection(mode="replace", modes=["wgmlst"])
                )
            }
        )
        report = validate_selection(
            selection, gmlst_catalog=_gmlst_catalog()
        )
        assert any(issue.code == "GMLST_SCHEME_MISSING" for issue in report.errors)


class TestOptions:
    def test_vpa_options_include_extra_databases(self):
        selection = ToolSelection()
        doc = build_options(
            selection,
            catalog=_gspec_catalog(),
            gmlst_catalog=_gmlst_catalog(),
            species="VPA",
        )
        assert [row.code for row in doc.species] == ["VPA"]
        names = {db.name for db in doc.species[0].databases}
        assert {"vpa_vf", "vpa_ok", "vpa_pai"} <= names
        default = {db.name for db in doc.species[0].databases if db.default}
        assert default == {"vpa_vf", "vpa_ok", "vpa_pai"}
        assert doc.species[0].gmlst.effective.modes == ["mlst", "cgmlst"]
        assert doc.gmlst_catalog_available is True
        assert doc.catalog_hash == catalog_hash(_gspec_catalog())
        assert doc.gmlst_catalog_hash == gmlst_catalog_hash(_gmlst_catalog())

    def test_unknown_species_filter_raises(self):
        with pytest.raises(SelectionError):
            build_options(
                ToolSelection(),
                catalog=_gspec_catalog(),
                gmlst_catalog=_gmlst_catalog(),
                species="not_a_species",
            )

    def test_diff_only_changed_species(self):
        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="replace", databases=["vpa_ok"])
                )
            }
        )
        diff = diff_against_defaults(selection)
        assert [row.code for row in diff.species] == ["VPA"]
        assert diff.species[0].removed == ["vpa_vf", "vpa_pai"]
        assert diff.species[0].added == []  # vpa_ok 本就在默认清单


class TestCatalogs:
    def test_parse_gspec_and_hash(self):
        payload = {
            "schema": "gspec.dblist/1",
            "providers": [
                {"name": "vpa_ok", "kind": "cluster", "typing": True, "installed": True},
                {"name": "card", "kind": "gene", "typing": False, "installed": False},
            ],
        }
        catalog = parse_catalog(payload)
        assert catalog["vpa_ok"].kind == "cluster"
        assert len(catalog_hash(catalog)) == 64

    def test_parse_gmlst(self):
        payload = {
            "schema_version": "gmlst-scheme-list-v1",
            "data": [
                {
                    "scheme_name": "vparahaemolyticus_3",
                    "organism": "Vibrio parahaemolyticus",
                    "scheme_type": "cgmlst",
                    "n_loci": 2254,
                    "downloaded": True,
                }
            ],
        }
        catalog = parse_gmlst_schemes(payload)
        assert catalog["vparahaemolyticus_3"].scheme_type == "cgmlst"
        assert catalog["vparahaemolyticus_3"].downloaded is True
        assert len(gmlst_catalog_hash(catalog)) == 64

    def test_missing_providers_raises(self):
        with pytest.raises(SelectionError):
            parse_catalog({})
