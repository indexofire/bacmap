"""物种三字母码：规则、覆盖、哨兵与冲突检测（码为准迁移的地基）。"""

from __future__ import annotations

from bacmap.core.species_codes import (
    GSIDE_MARKER_LABELS,
    INTENTIONAL_MERGES,
    UNK,
    code_map,
    species_code,
)

EXPECTED = {
    "Salmonella": "SAL",
    "V_parahaemolyticus": "VPA",
    "Listeria_monocytogenes": "LMO",
    "Vibrio_cholerae": "VCH",
    "Vibrio_cholerae_O1": "VCH",
    "Vibrio_cholerae_O139": "VCH",
    "Vibrio_vulnificus": "VVU",
    "Staphylococcus_aureus": "SAU",
    "Klebsiella_pneumoniae": "KPN",
    "Acinetobacter_baumannii": "ABA",
    "Pseudomonas_aeruginosa": "PAE",
    "Enterococcus_faecalis": "EFA",
    "Enterococcus_faecium": "EFM",
    "Streptococcus_pneumoniae": "SPN",
    "Streptococcus_pyogenes": "SPY",
    "Streptococcus_agalactiae": "SAG",
    "Neisseria_meningitidis": "NME",
    "Neisseria_gonorrhoeae": "NGO",
    "Clostridioides_difficile": "CDI",
    "Cronobacter_sakazakii": "CSA",
    "Legionella_pneumophila": "LPN",
    "Mycoplasma_pneumoniae": "MPN",
    "Helicobacter_pylori": "HPY",
    "Bordetella_pertussis": "BPE",
    "Corynebacterium_diphtheriae": "CDP",
    "Haemophilus_influenzae": "HIN",
    "Streptococcus_suis": "SSU",
    "Burkholderia_pseudomallei": "BPS",
    "Leptospira_interrogans": "LIN",
    "Treponema_pallidum": "TPA",
    "Bacillus_anthracis": "BAN",
    "Yersinia_pestis": "YPE",
    "Yersinia_enterocolitica": "YEN",
    "Aeromonas_hydrophila": "AHY",
    "Clostridium_botulinum": "CBO",
    "Clostridium_perfringens": "CPE",
    "DEC": "ECO",
    "Shigella_EIEC": "SHI",
    "Campylobacter_jejuni": "CJE",
    "Campylobacter_coli": "CCO",
}


class TestGsideMarkerCoverage:
    def test_all_40_labels_have_expected_codes(self):
        assert set(GSIDE_MARKER_LABELS) == set(EXPECTED)
        for label, code in EXPECTED.items():
            assert species_code(label) == code, label

    def test_no_accidental_collisions(self):
        grouped = code_map(list(GSIDE_MARKER_LABELS))
        # 唯一的多标签码必须是有意合并（VCH）
        multi = {c: v for c, v in grouped.items() if len(v) > 1}
        assert set(multi) <= set(INTENTIONAL_MERGES)
        assert multi["VCH"] == sorted(INTENTIONAL_MERGES["VCH"])


class TestRulesAndOverrides:
    def test_genus_initial_plus_two_letters(self):
        assert species_code("Klebsiella_pneumoniae") == "KPN"
        assert species_code("Acinetobacter_baumannii") == "ABA"

    def test_display_name_forms_equivalent(self):
        assert species_code("E. coli") == "ECO"
        assert species_code("V. parahaemolyticus") == "VPA"
        assert species_code("Escherichia coli") == "ECO"
        assert species_code("Salmonella enterica") == "SAL"
        assert species_code("Shigella") == "SHI"
        assert species_code("Shigella/EIEC") == "SHI"
        assert species_code("Klebsiella pneumoniae") == "KPN"


class TestSentinel:
    def test_placeholders_and_negatives_are_unknown(self):
        for v in (
            "",
            "Unknown",
            "N/A",
            "unclassified",
            "pending_gside",
            "not_Salmonella",
            "not_Salmonella (DEC)",
        ):
            assert species_code(v) == UNK, v

    def test_not_salmonella_must_not_be_misread_as_salmonella(self):
        # 回归：子串匹配曾把否定读成肯定
        assert species_code("not_Salmonella") != "SAL"


class TestCollisionGuard:
    def test_unexpected_collision_raises(self):
        try:
            code_map(["Clostridioides_difficile", "Corynebacterium_diphtheriae_XX"])
        except ValueError as exc:
            assert "collision" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError on code collision")

    def test_intentional_merge_allowed(self):
        grouped = code_map(["Vibrio_cholerae", "Vibrio_cholerae_O1", "Vibrio_cholerae_O139"])
        assert grouped["VCH"] == [
            "Vibrio_cholerae",
            "Vibrio_cholerae_O1",
            "Vibrio_cholerae_O139",
        ]
