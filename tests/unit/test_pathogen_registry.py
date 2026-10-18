"""Unit tests for bacmap.core.pathogen_registry（码为准，v1.4.16）。

键 = 三字母物种码；marker 基因归 gside（不再出现在 registry）。golden 值锁定
既有 4 病原的 MLST/cgMLST/AMRFinder 方案不变，只是键从名称改为码。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bacmap.config import DATA_DIR
from bacmap.core.species_codes import GSIDE_MARKER_LABELS, code_map

EXPECTED_CODES = set(code_map(list(GSIDE_MARKER_LABELS)))

GOLDEN_MLST_SCHEMES = {
    "SAL": "salmonella_2",
    "SHI": "ecoli_1",
    "ECO": "ecoli_1",
    "VPA": "vparahaemolyticus_1",
}
GOLDEN_CGMLST_SCHEMES = {
    "SAL": "senterica_2",
    "SHI": "ecoli_2",
    "ECO": "ecoli_2",
    "VPA": "vparahaemolyticus_3",
}
GOLDEN_AMRFINDER_ORGANISMS = {
    "SAL": "Salmonella",
    "SHI": "Escherichia",
    "ECO": "Escherichia",
    # V.parahaemolyticus 故意缺席：AMRFinderPlus 无其策展库 → 不传 -O。
}
GOLDEN_GAPIT_SCREENS = {
    "ECO": ["ecoli_dec", "ecoh"],
    "VPA": ["vpara_virulence"],
    "LMO": ["lm_doumith"],
    "KPN": ["kpsc_k", "kpsc_o"],
    "ABA": ["ab_k", "ab_o"],
}
GOLDEN_SNP_GROUPS = {
    "salmonella": (DATA_DIR / "reference/genomes/salmonella_LT2.fasta", ["SAL"]),
    "ecoli": (DATA_DIR / "reference/genomes/ecoli_k12.fasta", ["SHI", "ECO"]),
    "vpara": (DATA_DIR / "reference/genomes/vpara_rimd.fasta", ["VPA"]),
}


def _default_registry_path() -> Path:
    import bacmap.core.pathogen_registry as pr

    return Path(pr.__file__).parent / "pathogens.yaml"


def _write_registry(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "pathogens.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


MINIMAL_VALID: dict = {
    "pathogens": {
        "SAL": {
            "display_name": "沙门菌",
            "gside_labels": ["Salmonella"],
            "mlst_scheme": "salmonella_2",
            "snp_group": "salmonella",
        },
        "ECO": {
            "display_name": "大肠埃希菌",
            "gside_labels": ["DEC"],
            "mlst_scheme": "ecoli_1",
            "snp_group": "ecoli",
        },
    },
    "snp_groups": {
        "salmonella": {
            "ref": "data/reference/genomes/salmonella_LT2.fasta",
            "organism": "Salmonella enterica",
        },
        "ecoli": {
            "ref": "data/reference/genomes/ecoli_k12.fasta",
            "organism": "Escherichia coli",
        },
    },
}


class TestDefaultRegistryLoads:
    def test_packaged_yaml_exists(self):
        assert _default_registry_path().is_file()

    def test_load_default_registry_covers_gside_marker_labels(self):
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert set(reg.pathogens) == EXPECTED_CODES
        # 40 条 gside 标签 → 38 个码（VCH 合并 cholerae/O1/O139）
        assert len(EXPECTED_CODES) == 38

    def test_all_default_pathogens_enabled(self):
        from bacmap.core.pathogen_registry import load_registry

        assert all(p.enabled for p in load_registry().pathogens.values())


class TestGoldenMigration:
    """既有 4 病原的方案不变，只是键从名称改为码。"""

    def test_mlst_schemes(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().mlst_schemes() == GOLDEN_MLST_SCHEMES

    def test_cgmlst_schemes(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().cgmlst_schemes() == GOLDEN_CGMLST_SCHEMES

    def test_amrfinder_organisms(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().amrfinder_organisms() == GOLDEN_AMRFINDER_ORGANISMS

    def test_gapit_screens(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().gapit_screens() == GOLDEN_GAPIT_SCREENS

    def test_snp_groups_derived_from_membership(self):
        from bacmap.core.pathogen_registry import load_registry

        groups = load_registry().snp_groups()
        assert set(groups) == set(GOLDEN_SNP_GROUPS)
        for name, (ref, members) in GOLDEN_SNP_GROUPS.items():
            assert Path(groups[name]["ref"]) == ref
            assert groups[name]["species"] == members

    def test_plan_flags(self):
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert reg.pathogens["SAL"].wants("snp") is True
        assert reg.pathogens["SAL"].wants("recombination") is True
        assert reg.pathogens["KPN"].wants("snp") is False  # 无参考基因组

    def test_recombination_groups_from_plan(self):
        from bacmap.core.pathogen_registry import get_workflow_tables, load_registry

        assert load_registry().groups_with_plan("recombination") == ["salmonella"]
        assert get_workflow_tables().recombination_groups == ["salmonella"]


class TestResolveDualAccept:
    def test_code_label_and_display_name(self):
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert reg.resolve("SAL") == "SAL"
        assert reg.resolve("Salmonella") == "SAL"
        assert reg.resolve("沙门菌") == "SAL"
        assert reg.resolve("V_parahaemolyticus") == "VPA"
        assert reg.resolve("V. parahaemolyticus") == "VPA"
        assert reg.resolve("E. coli") == "ECO"
        assert reg.resolve("DEC") == "ECO"

    def test_unknown_and_placeholder(self):
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert reg.resolve("") is None
        assert reg.resolve("Unknown") is None
        assert reg.resolve("not_Salmonella") is None
        assert reg.resolve("Nonexistent_genus") is None

    def test_gside_common_pathogen(self):
        from bacmap.core.pathogen_registry import load_registry

        assert load_registry().resolve("Klebsiella_pneumoniae") == "KPN"

    def test_gapit_screens_for(self):
        from bacmap.core.pathogen_registry import gapit_screens_for

        assert gapit_screens_for("E.coli") == ["ecoli_dec", "ecoh"]
        assert gapit_screens_for("Listeria_monocytogenes") == ["lm_doumith"]
        assert gapit_screens_for("Salmonella") == []
        assert gapit_screens_for("Unknown") == []


class TestValidation:
    def _load(self, tmp_path, data):
        from bacmap.core.pathogen_registry import load_registry

        return load_registry(_write_registry(tmp_path, data))

    def test_unknown_field_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["SAL"]["frobnicate"] = 1
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="frobnicate"):
            self._load(tmp_path, data)

    def test_missing_display_name_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        del data["pathogens"]["SAL"]["display_name"]
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="display_name"):
            self._load(tmp_path, data)

    def test_non_code_key_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["Salmonella"] = data["pathogens"].pop("SAL")
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="3-letter"):
            self._load(tmp_path, data)

    def test_gside_label_code_mismatch_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["SAL"]["gside_labels"] = ["Vibrio_cholerae"]
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="mismatch"):
            self._load(tmp_path, data)

    def test_unknown_snp_group_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["SAL"]["snp_group"] = "nonexistent"
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="nonexistent"):
            self._load(tmp_path, data)

    def test_invalid_plan_key_rejected(self, tmp_path):
        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["SAL"]["plan"] = {"frobnicate": True}
        from bacmap.core.pathogen_registry import RegistryError

        with pytest.raises(RegistryError, match="plan keys"):
            self._load(tmp_path, data)


class TestDisabledPathogens:
    def test_disabled_excluded_from_query_maps(self, tmp_path):
        from bacmap.core.pathogen_registry import load_registry

        data = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID))
        data["pathogens"]["ECO"]["enabled"] = False
        reg = load_registry(_write_registry(tmp_path, data))

        assert "ECO" in reg.pathogens
        assert "ECO" not in reg.mlst_schemes()
        # 分组按成员派生：禁用的 ECO 使 ecoli 组无成员 → 组消失
        assert "ecoli" not in reg.snp_groups()


class TestEnvOverride:
    def test_env_var_selects_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "BACMAP_PATHOGEN_REGISTRY", str(_write_registry(tmp_path, MINIMAL_VALID))
        )
        from bacmap.core.pathogen_registry import load_registry

        reg = load_registry()
        assert set(reg.pathogens) == {"SAL", "ECO"}
