"""Unit tests for bacmap.core.pathogen_registry.

Golden values are transcribed verbatim from the pre-refactor hardcoded dicts
(typing_amr.smk / snp.smk / cgmlst.smk / species_identifier.py) and the
registry must reproduce them exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bacmap.config import DATA_DIR

GOLDEN_MLST_SCHEMES = {
    "Salmonella": "salmonella_2",
    "E.coli": "ecoli_1",
    "Shigella": "ecoli_1",
    "V.parahaemolyticus": "vparahaemolyticus_1",
}

GOLDEN_CGMLST_SCHEMES = {
    "Salmonella": "senterica_2",
    "E.coli": "ecoli_2",
    "Shigella": "ecoli_2",
    "V.parahaemolyticus": "vparahaemolyticus_3",
}

GOLDEN_AMRFINDER_ORGANISMS = {
    "Salmonella": "Salmonella",
    "E.coli": "Escherichia",
    # V.parahaemolyticus is deliberately absent: AMRFinderPlus has no curated
    # organism database for it. Adding the key would change rule behaviour.
    "Shigella": "Escherichia",
}

GOLDEN_GENE_TO_SPECIES = {
    "inva": ("Salmonella", "high"),
    "uida": ("DEC", "high"),
    "ipah": ("Shigella/EIEC", "high"),
    "toxr": ("V_parahaemolyticus", "high"),
    "tlh": ("V_parahaemolyticus", "high"),
}

GOLDEN_SPECIES_PRIORITY = ["inva", "ipah", "toxr", "tlh", "uida"]

GOLDEN_SNP_GROUPS = {
    "salmonella": {
        "ref": DATA_DIR / "reference/genomes/salmonella_LT2.fasta",
        "species": ["Salmonella"],
        "organism": "Salmonella enterica",
    },
    "ecoli": {
        "ref": DATA_DIR / "reference/genomes/ecoli_k12.fasta",
        "species": ["E.coli", "Shigella"],
        "organism": "Escherichia coli / Shigella",
    },
    "vpara": {
        "ref": DATA_DIR / "reference/genomes/vpara_rimd.fasta",
        "species": ["V.parahaemolyticus"],
        "organism": "Vibrio parahaemolyticus",
    },
}


def _default_registry_path() -> Path:
    import bacmap

    return Path(bacmap.core.pathogen_registry.__file__).parent / "pathogens.yaml"


def _write_registry(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "pathogens.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


MINIMAL_VALID: dict = {
    "pathogens": {
        "Salmonella": {
            "display_name": "沙门菌",
            "marker_genes": ["inva"],
            "mlst_scheme": "salmonella_2",
            "snp_group": "salmonella",
        },
        "E.coli": {
            "display_name": "大肠埃希菌",
            "marker_genes": ["uida"],
            "mlst_scheme": "ecoli_1",
            "snp_group": "ecoli",
        },
    },
    "snp_groups": {
        "salmonella": {
            "ref": "data/reference/genomes/salmonella_LT2.fasta",
            "species": ["Salmonella"],
            "organism": "Salmonella enterica",
        },
        "ecoli": {
            "ref": "data/reference/genomes/ecoli_k12.fasta",
            "species": ["E.coli"],
            "organism": "Escherichia coli",
        },
    },
}


class TestDefaultRegistryLoads:
    def test_packaged_yaml_exists(self):
        assert _default_registry_path().is_file()

    def test_load_default_registry(self):
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert set(reg.pathogens) == {
            "Salmonella",
            "E.coli",
            "Shigella",
            "V.parahaemolyticus",
        }

    def test_all_default_pathogens_enabled(self):
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert all(p.enabled for p in reg.pathogens.values())


class TestGoldenMigration:
    """The registry must reproduce the pre-refactor dicts exactly."""

    def test_mlst_schemes(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().mlst_schemes() == GOLDEN_MLST_SCHEMES

    def test_cgmlst_schemes(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().cgmlst_schemes() == GOLDEN_CGMLST_SCHEMES

    def test_amrfinder_organisms(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().amrfinder_organisms() == GOLDEN_AMRFINDER_ORGANISMS

    def test_species_markers(self):
        from bacmap.core.pathogen_registry import load_registry

        gene_map, priority = load_registry().species_markers()
        assert dict(gene_map) == GOLDEN_GENE_TO_SPECIES
        assert priority == GOLDEN_SPECIES_PRIORITY

    def test_snp_groups_resolved(self):
        from bacmap.core.pathogen_registry import load_registry

        groups = load_registry().snp_groups()
        assert set(groups) == set(GOLDEN_SNP_GROUPS)
        for name, golden in GOLDEN_SNP_GROUPS.items():
            got = groups[name]
            assert Path(got["ref"]) == golden["ref"]
            assert got["species"] == golden["species"]
            assert got["organism"] == golden["organism"]

    def test_snp_group_reference_genomes_exist(self):
        pytest.skip("参考基因组随第 4 步（workflow/数据部署）落地后启用")
        from bacmap.core.pathogen_registry import load_registry

        for group in load_registry().snp_groups().values():
            assert Path(group["ref"]).is_file(), group["ref"]


class TestValidation:
    def _load(self, tmp_path, data):
        from bacmap.core.pathogen_registry import load_registry

        return load_registry(_write_registry(tmp_path, data))

    def test_unknown_field_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["Salmonella"]["frobnicate"] = 1
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="frobnicate"):
            self._load(tmp_path, data)

    def test_missing_required_field_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        del data["pathogens"]["Salmonella"]["mlst_scheme"]
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="mlst_scheme"):
            self._load(tmp_path, data)

    def test_duplicate_marker_gene_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["E.coli"]["marker_genes"] = ["inva"]
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="inva"):
            self._load(tmp_path, data)

    def test_unknown_snp_group_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["Salmonella"]["snp_group"] = "nonexistent"
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="nonexistent"):
            self._load(tmp_path, data)

    def test_snp_group_lists_unregistered_species_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["snp_groups"]["ecoli"]["species"].append("Testomonas")
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="Testomonas"):
            self._load(tmp_path, data)

    def test_empty_marker_genes_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["Salmonella"]["marker_genes"] = []
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="marker"):
            self._load(tmp_path, data)


class TestDisabledPathogens:
    def test_disabled_excluded_from_query_maps(self, tmp_path):
        from bacmap.core.pathogen_registry import load_registry

        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["E.coli"]["enabled"] = False
        reg = load_registry(_write_registry(tmp_path, data))

        assert "E.coli" in reg.pathogens
        assert "E.coli" not in reg.mlst_schemes()
        assert "uida" not in reg.species_markers()[1]


class TestEnvOverride:
    def test_env_var_selects_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "BACMAP_PATHOGEN_REGISTRY", str(_write_registry(tmp_path, MINIMAL_VALID))
        )
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert set(reg.pathogens) == {"Salmonella", "E.coli"}
