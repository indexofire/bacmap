"""TDD 测试：Deterministic Verifier（project.md §8.2 Layer 2）。"""

from __future__ import annotations

from bacmap.core.verify.deterministic_verifier import (
    DeterministicVerifier,
)


class TestSpeciesVerification:
    def test_salmonella_passes(self):
        v = DeterministicVerifier()
        result = v.verify_species("Salmonella")
        assert result.passed is True

    def test_not_salmonella_fails(self):
        v = DeterministicVerifier()
        result = v.verify_species("not_Salmonella")
        assert result.passed is False
        assert "not_Salmonella" in result.message

    def test_ambiguous_fails(self):
        v = DeterministicVerifier()
        result = v.verify_species("ambiguous")
        assert result.passed is False

    def test_empty_fails(self):
        v = DeterministicVerifier()
        result = v.verify_species("")
        assert result.passed is False


class TestMLSTVerification:
    def test_valid_st_passes(self):
        v = DeterministicVerifier()
        alleles = {
            "aroC": "10",
            "dnaN": "7",
            "hemD": "12",
            "hisD": "9",
            "purE": "5",
            "sucA": "9",
            "thrA": "2",
        }
        result = v.verify_mlst("19", alleles)
        assert result.passed is True

    def test_missing_st_fails(self):
        v = DeterministicVerifier()
        alleles = {
            "aroC": "10",
            "dnaN": "7",
            "hemD": "12",
            "hisD": "9",
            "purE": "5",
            "sucA": "9",
            "thrA": "2",
        }
        result = v.verify_mlst("-", alleles)
        assert result.passed is False

    def test_missing_allele_fails(self):
        v = DeterministicVerifier()
        alleles = {
            "aroC": "-",
            "dnaN": "7",
            "hemD": "12",
            "hisD": "9",
            "purE": "5",
            "sucA": "9",
            "thrA": "2",
        }
        result = v.verify_mlst("19", alleles)
        assert result.passed is False

    def test_incomplete_loci_fails(self):
        v = DeterministicVerifier()
        alleles = {"aroC": "10", "dnaN": "7"}
        result = v.verify_mlst("19", alleles)
        assert result.passed is False

    def test_non_numeric_st_fails(self):
        v = DeterministicVerifier()
        alleles = {
            "aroC": "10",
            "dnaN": "7",
            "hemD": "12",
            "hisD": "9",
            "purE": "5",
            "sucA": "9",
            "thrA": "2",
        }
        result = v.verify_mlst("N/A", alleles)
        assert result.passed is False


class TestSerotypeVerification:
    def test_known_serovar_passes(self):
        v = DeterministicVerifier()
        result = v.verify_serotype("Typhimurium", "B")
        assert result.passed is True

    def test_na_serovar_fails(self):
        v = DeterministicVerifier()
        result = v.verify_serotype("N/A", "")
        assert result.passed is False

    def test_empty_serovar_fails(self):
        v = DeterministicVerifier()
        result = v.verify_serotype("", "")
        assert result.passed is False

    def test_known_serogroup_passes(self):
        v = DeterministicVerifier()
        result = v.verify_serotype("Enteritidis", "D1")
        assert result.passed is True


class TestAMRVerification:
    def test_known_gene_passes(self):
        v = DeterministicVerifier()
        result = v.verify_amr_genes(["blaTEM-1", "tet(A)", "sul1"])
        assert result.passed is True

    def test_empty_list_passes(self):
        v = DeterministicVerifier()
        result = v.verify_amr_genes([])
        assert result.passed is True

    def test_suspicious_gene_flagged(self):
        v = DeterministicVerifier()
        result = v.verify_amr_genes(["blaXXX-FAKE-99"])
        assert result.passed is True
        assert result.details.get("warnings") is not None

    def test_empty_string_gene_fails(self):
        v = DeterministicVerifier()
        result = v.verify_amr_genes([""])
        assert result.passed is False

    def test_critical_genes_flagged(self):
        v = DeterministicVerifier()
        result = v.verify_amr_genes(["blaCTX-M-15", "mcr-1", "blaNDM-1"])
        assert result.details.get("critical_resistance") is True


class TestVerifyAll:
    def test_clean_result_passes(self):
        v = DeterministicVerifier()
        summary = {
            "steps": {
                "species": {"verdict": "Salmonella"},
                "mlst": "FILE\tSCHEME\tST\taroC\tdnaN\themD\thisD\tpurE\tsucA\tthrA\n"
                "sample\tsalmonella_2\t19\t10\t7\t12\t9\t5\t9\t2",
                "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
                "amr": {"abricate_card": [{"GENE": "blaTEM-1"}, {"GENE": "tet(A)"}]},
            }
        }
        result = v.verify_all(summary)
        assert result.passed is True
        assert result.failed_count == 0

    def test_bad_species_fails(self):
        v = DeterministicVerifier()
        summary = {
            "steps": {
                "species": {"verdict": "not_Salmonella"},
                "mlst": "",
                "serotype": {},
                "amr": {},
            }
        }
        result = v.verify_all(summary)
        assert result.passed is False
        assert result.failed_count >= 1

    def test_needs_human_review_on_critical_amr(self):
        v = DeterministicVerifier()
        summary = {
            "steps": {
                "species": {"verdict": "Salmonella"},
                "mlst": "FILE\tSCHEME\tST\taroC\tdnaN\themD\thisD\tpurE\tsucA\tthrA\n"
                "sample\tsalmonella_2\t19\t10\t7\t12\t9\t5\t9\t2",
                "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
                "amr": {"abricate_card": [{"GENE": "mcr-1"}, {"GENE": "blaNDM-1"}]},
            }
        }
        result = v.verify_all(summary)
        assert result.needs_human_review is True

    def test_real_summary_species_key_shape(self):
        """真实 summary 用 steps.species.species（统一 species.smk 输出），
        非旧 fixtures 的 verdict 键——回归：修复前该形态 species 检查必失败。"""
        v = DeterministicVerifier()
        summary = {
            "steps": {
                "species": {"species": "Salmonella", "confidence": "high"},
                "mlst": "FILE\tSCHEME\tST\taroC\tdnaN\themD\thisD\tpurE\tsucA\tthrA\n"
                "sample\tsalmonella_2\t19\t10\t7\t12\t9\t5\t9\t2",
                "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
                "amr": {"abricate_card": [{"GENE": "blaTEM-1"}]},
            }
        }
        result = v.verify_all(summary)
        assert result.passed is True
        assert result.checks[0].name == "species"
        assert result.checks[0].passed is True

    def test_binomial_species_name_canonicalized(self):
        v = DeterministicVerifier()
        summary = {
            "steps": {
                "species": {"species": "Salmonella enterica"},
                "mlst": "FILE\tSCHEME\tST\taroC\tdnaN\themD\thisD\tpurE\tsucA\tthrA\n"
                "sample\tsalmonella_2\t19\t10\t7\t12\t9\t5\t9\t2",
                "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
                "amr": {"abricate_card": []},
            }
        }
        result = v.verify_all(summary)
        assert result.checks[0].passed is True


class TestSpeciesCommonPathogens:
    """Layer 2 物种校验：识别常见病原（不再只认 Salmonella）。"""

    def test_ecoli_and_common_pathogens_confirmed(self):
        v = DeterministicVerifier()
        for verdict in ("E. coli", "Shigella", "V. parahaemolyticus", "Klebsiella_pneumoniae"):
            assert v.verify_species(verdict).passed is True, verdict

    def test_negative_and_unknown_still_fail(self):
        v = DeterministicVerifier()
        for verdict in ("not_Salmonella", "", "ambiguous", "Unknown"):
            assert v.verify_species(verdict).passed is False, verdict

    def test_verify_all_tolerates_non_str_mlst(self):
        v = DeterministicVerifier()
        result = v.verify_all(
            {"steps": {"species": {"verdict": "Klebsiella_pneumoniae"}, "mlst": {"st": "1"}}}
        )
        assert result.checks[0].passed is True  # 物种识别
        assert result.passed is False  # mlst/serotype 缺失 → 未通过，但不崩
