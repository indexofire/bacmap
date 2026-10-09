"""Tests for StrainGenotypeIndex — denormalized genotype traceability index."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.store.strain_index import StrainGenotypeIndex, _extract_genotype  # noqa: E402


@pytest.fixture
def idx(tmp_path):
    db = tmp_path / "test_genotype.sqlite"
    index = StrainGenotypeIndex(db)
    yield index
    index.close()


@pytest.fixture
def populated_idx(idx):
    idx.upsert(
        strain_id="SAM-001",
        organism="Salmonella enterica",
        species="Salmonella",
        serotype="Typhimurium",
        serotype_method="SISTR",
        mlst_scheme="salmonella_2",
        mlst_st="ST19",
        amr_genes=[
            {"gene": "blaCTX-M-15", "database": "card", "coverage": 100.0, "identity": 99.5},
            {"gene": "tet(A)", "database": "card", "coverage": 100.0, "identity": 98.0},
            {"gene": "marA", "database": "card", "coverage": 95.0, "identity": 100.0},
        ],
        object_id="obj-001",
        pipeline_version="v0.1",
    )
    idx.upsert(
        strain_id="SAM-002",
        organism="Salmonella enterica",
        species="Salmonella",
        serotype="Typhimurium",
        serotype_method="SISTR",
        mlst_scheme="salmonella_2",
        mlst_st="ST19",
        amr_genes=[
            {"gene": "blaCTX-M-15", "database": "card", "coverage": 100.0, "identity": 100.0},
            {"gene": "qnrS", "database": "card", "coverage": 98.0, "identity": 99.0},
        ],
        object_id="obj-002",
        pipeline_version="v0.1",
    )
    idx.upsert(
        strain_id="SAM-003",
        organism="Salmonella enterica",
        species="Salmonella",
        serotype="Enteritidis",
        serotype_method="SISTR",
        mlst_scheme="salmonella_2",
        mlst_st="ST11",
        amr_genes=[
            {"gene": "tet(A)", "database": "card", "coverage": 100.0, "identity": 97.0},
        ],
        object_id="obj-003",
        pipeline_version="v0.1",
    )
    idx.upsert(
        strain_id="DEC-001",
        organism="Escherichia coli",
        species="E.coli",
        serotype="O157:H7",
        serotype_method="ecoh_serotyper",
        mlst_scheme="ecoli_1",
        mlst_st="ST11",
        amr_genes=[
            {"gene": "blaCTX-M-15", "database": "card", "coverage": 100.0, "identity": 99.0},
        ],
        object_id="obj-004",
        pipeline_version="v0.1",
    )
    return idx


class TestUpsertAndSearch:
    def test_search_by_serotype(self, populated_idx):
        results = populated_idx.search(serotype="Typhimurium")
        assert len(results) == 2
        strain_ids = {r.strain_id for r in results}
        assert strain_ids == {"SAM-001", "SAM-002"}

    def test_search_by_mlst_st(self, populated_idx):
        results = populated_idx.search(mlst_st="ST19")
        assert len(results) == 2
        assert all(r.mlst_st == "ST19" for r in results)

    def test_search_by_mlst_st_normalized(self, populated_idx):
        results = populated_idx.search(mlst_st="19")
        assert len(results) == 2

    def test_search_by_amr_gene(self, populated_idx):
        results = populated_idx.search(amr_gene="blaCTX-M-15")
        assert len(results) == 3
        ids = {r.strain_id for r in results}
        assert ids == {"SAM-001", "SAM-002", "DEC-001"}

    def test_search_by_organism(self, populated_idx):
        results = populated_idx.search(organism="Escherichia")
        assert len(results) == 1
        assert results[0].strain_id == "DEC-001"

    def test_search_multi_field_and(self, populated_idx):
        results = populated_idx.search(serotype="Typhimurium", amr_gene="blaCTX-M-15")
        assert len(results) == 2
        ids = {r.strain_id for r in results}
        assert ids == {"SAM-001", "SAM-002"}

    def test_search_serotype_and_mlst_exclude(self, populated_idx):
        results = populated_idx.search(serotype="Typhimurium", mlst_st="ST11")
        assert len(results) == 0

    def test_search_returns_amr_genes(self, populated_idx):
        results = populated_idx.search(serotype="Enteritidis")
        assert len(results) == 1
        assert "tet(A)" in results[0].amr_genes

    def test_search_limit(self, populated_idx):
        results = populated_idx.search(mlst_st="ST11", limit=1)
        assert len(results) == 1

    def test_count(self, populated_idx):
        assert populated_idx.count() == 4


class TestFindSimilar:
    def test_find_similar_same_serotype_and_mlst(self, populated_idx):
        results = populated_idx.find_similar("SAM-001")
        ids = {r.strain_id for r in results}
        assert "SAM-002" in ids
        assert "SAM-001" not in ids

    def test_find_similar_match_reasons(self, populated_idx):
        results = populated_idx.find_similar("SAM-001")
        for m in results:
            if m.strain_id == "SAM-002":
                assert any("serotype" in r for r in m.match_reasons)
                assert any("MLST" in r for r in m.match_reasons)

    def test_find_similar_excludes_self(self, populated_idx):
        results = populated_idx.find_similar("SAM-003")
        assert all(r.strain_id != "SAM-003" for r in results)


class TestGetProfile:
    def test_get_profile(self, populated_idx):
        profile = populated_idx.get_profile("SAM-001")
        assert profile is not None
        assert profile["serotype"] == "Typhimurium"
        assert profile["mlst_st"] == "ST19"
        assert len(profile["amr_genes"]) == 3

    def test_get_profile_not_found(self, populated_idx):
        assert populated_idx.get_profile("NOPE") is None


class TestExtractGenotype:
    def test_extract_from_full_payload(self):
        payload = {
            "species_verdict": "Salmonella",
            "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t10",
            "amr": {
                "abricate_card": [
                    {
                        "GENE": "blaCTX-M-15",
                        "%COVERAGE": "100.00",
                        "%IDENTITY": "99.50",
                        "PRODUCT": "beta-lactamase",
                    },
                    {"GENE": "tet(A)", "%COVERAGE": "100.00", "%IDENTITY": "98.00"},
                ],
                "abricate_vfdb": [],
            },
            "plasmid": {
                "plasmidfinder": [{"GENE": "IncFIB"}],
            },
        }
        result = _extract_genotype(payload)
        assert result["species"] == "Salmonella"
        assert result["serotype"] == "Typhimurium"
        assert result["serotype_method"] == "SISTR"
        assert result["mlst_scheme"] == "salmonella_2"
        assert result["mlst_st"] == "ST19"
        assert len(result["amr_genes"]) == 2
        assert result["amr_genes"][0]["gene"] == "blaCTX-M-15"
        assert result["plasmid_types"] == ["IncFIB"]

    def test_extract_empty_payload(self):
        result = _extract_genotype({})
        assert result["serotype"] == ""
        assert result["mlst_st"] == ""
        assert result["amr_genes"] == []

    def test_extract_dec_serotype(self):
        payload = {
            "species_verdict": "E.coli",
            "serotype": {},
            "dec": {
                "primary_serotype": "O157:H7",
                "serotype_method": "ecoh_serotyper (DEC/EIEC)",
            },
            "mlst": "FILE\tSCHEME\tST\ncontigs\tecoli_1\t11",
        }
        result = _extract_genotype(payload)
        assert result["serotype"] == "O157:H7"
        assert result["serotype_method"] == "ecoh_serotyper (DEC/EIEC)"
        assert result["mlst_st"] == "ST11"


class TestExtractGenotypeEdgeCases:
    def test_st_dash_not_prefixed(self):
        payload = {
            "species_verdict": "Salmonella",
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t-\t10",
        }
        result = _extract_genotype(payload)
        assert result["mlst_st"] in ("", "-")
        assert result["mlst_st"] != "ST-"

    def test_st_na_not_prefixed(self):
        payload = {
            "species_verdict": "Salmonella",
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\tN/A\t10",
        }
        result = _extract_genotype(payload)
        assert result["mlst_st"] == ""

    def test_serotype_as_string(self):
        payload = {
            "species_verdict": "Salmonella",
            "serotype": "Typhimurium",
        }
        result = _extract_genotype(payload)
        assert result["serotype"] == "Typhimurium"

    def test_serotype_as_none(self):
        payload = {
            "species_verdict": "Salmonella",
            "serotype": None,
        }
        result = _extract_genotype(payload)
        assert result["serotype"] == ""

    def test_amr_gene_empty_name_skipped(self):
        payload = {
            "species_verdict": "Salmonella",
            "amr": {
                "abricate_card": [
                    {"GENE": "", "%COVERAGE": "100.00"},
                    {"GENE": "blaCTX-M-15", "%COVERAGE": "100.00"},
                    {"GENE": "  ", "%COVERAGE": "100.00"},
                ],
            },
        }
        result = _extract_genotype(payload)
        assert len(result["amr_genes"]) == 1
        assert result["amr_genes"][0]["gene"] == "blaCTX-M-15"
