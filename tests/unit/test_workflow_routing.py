"""工作流路由：按病原注册表决定每个样本适用的种以下步骤（v1.4.24）。

回归：ECO 样本曾无条件触发 SISTR（沙门菌工具）、ShigaTyper/vpara 步骤；
vpa/dec/shigella 规则与 report 依赖都未按物种门控。
"""

from __future__ import annotations

from bacmap.core.analysis.routing import report_inputs, serotype_engine, uses_gspec_db

_COMMON = {
    "qc_json",
    "assembly_stats",
    "species_id",
    "mlst",
    "vfdb",
    "card",
    "amrfinderplus",
    "plasmidfinder",
    "gspec_typing",
    "annotation",
}


def _extra(species_value: str) -> set[str]:
    return set(report_inputs("S1", species_value, "/w")) - _COMMON


class TestAssemblyEntryGating:
    """v1.4.33 assembly 直入：无 reads 的样本 qc_json 不进 DAG。"""

    def test_fasta_sample_drops_qc(self):
        files = report_inputs("S1", "SAL", "/w", has_qc=False)
        assert "qc_json" not in files
        assert files["assembly_stats"] == "/w/S1/assembly/assembly_stats.tsv"

    def test_reads_sample_keeps_qc_by_default(self):
        files = report_inputs("S1", "SAL", "/w")
        assert files["qc_json"] == "/w/S1/qc/S1_fastp.json"


class TestSerotypeEngine:
    def test_engines(self):
        assert serotype_engine("SAL") == "sistr"
        assert serotype_engine("Shigella") == "shigatyper"
        assert serotype_engine("DEC") == "ecoh"
        assert serotype_engine("Escherichia_coli") == "ecoh"

    def test_no_engine(self):
        assert serotype_engine("Listeria_monocytogenes") == ""
        assert serotype_engine("not_a_species") == ""


class TestGapitDbRouting:
    def test_eco_dec_only_where_declared(self):
        assert uses_gspec_db("DEC", "eco_dec") is True
        # 志贺菌的血清型走 ShigaTyper；registry 未为其声明 eco_dec
        assert uses_gspec_db("Shigella", "eco_dec") is False
        assert uses_gspec_db("SAL", "eco_dec") is False
        assert uses_gspec_db("V_parahaemolyticus", "eco_dec") is False

    def test_vpara_only_for_vpara(self):
        assert uses_gspec_db("V_parahaemolyticus", "vpara_virulence") is True
        assert uses_gspec_db("DEC", "vpara_virulence") is False


class TestReportInputsGating:
    """summary 依赖只含适用步骤：不适用者不进入 DAG（也就不会跑外部工具）。"""

    def test_ecoli(self):
        extra = _extra("DEC")
        assert extra == {"ectyper", "pathotype"}

    def test_salmonella(self):
        extra = _extra("SAL")
        assert extra == {"sistr"}

    def test_shigella(self):
        extra = _extra("Shigella")
        assert extra == {"shigella_serotype"}

    def test_vpara(self):
        extra = _extra("V_parahaemolyticus")
        assert extra == {"vpa_serotype", "vpa_virulence"}

    def test_listeria_uses_none_of_them(self):
        # LMO 的血清群由 gspec lmo_sero 给出（走 gspec_typing），不额外起步骤
        assert _extra("Listeria_monocytogenes") == set()

    def test_unknown_species_has_no_species_steps(self):
        assert _extra("not_a_species") == set()

    def test_common_inputs_always_present(self):
        files = report_inputs("S1", "DEC", "/w")
        assert set(files) >= _COMMON
        assert files["gspec_typing"] == "/w/S1/gspec/typing.json"


class TestSelectionAwareRouting:
    def test_replace_removes_vpara_special_steps(self):
        from bacmap.core.tool_selection import (
            GapitSelection,
            SpeciesSelection,
            ToolSelection,
        )

        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="replace", databases=["vpa_ok", "vpa_pai"])
                )
            }
        )
        assert uses_gspec_db("V_parahaemolyticus", "vpa_ok", selection=selection) is True
        assert (
            uses_gspec_db("V_parahaemolyticus", "vpara_virulence", selection=selection)
            is False
        )
        extra = set(
            report_inputs(
                "S1", "V_parahaemolyticus", "/w", selection=selection
            )
        ) - _COMMON
        # vpa_ok/vpa_pai ride the generic gspec_typing aggregate; the factual
        # vpa_serotype placeholder stays (gspec fills it when vpa_ok runs).
        assert extra == {"vpa_serotype"}

    def test_extend_keeps_vpara_special_steps(self):
        from bacmap.core.tool_selection import (
            GapitSelection,
            SpeciesSelection,
            ToolSelection,
        )

        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="extend", databases=["vpa_ok"])
                )
            }
        )
        extra = set(
            report_inputs(
                "S1", "V_parahaemolyticus", "/w", selection=selection
            )
        ) - _COMMON
        assert extra == {"vpa_serotype", "vpa_virulence"}

    def test_sample_override_applies_to_special_steps(self):
        from bacmap.core.tool_selection import (
            GapitSelection,
            SampleSelection,
            SpeciesSelection,
            ToolSelection,
        )

        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GapitSelection(mode="replace", databases=["vpa_ok"])
                )
            },
            samples={
                "S1": SampleSelection(
                    gspec=GapitSelection(databases=["vpara_virulence"])
                )
            },
        )
        assert (
            uses_gspec_db(
                "V_parahaemolyticus", "vpara_virulence", selection=selection, sample="S1"
            )
            is True
        )
