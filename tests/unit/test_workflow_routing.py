"""工作流路由：按病原注册表决定每个样本适用的种以下步骤（v1.4.24）。

回归：ECO 样本曾无条件触发 SISTR（沙门菌工具）、ShigaTyper/vpara 步骤；
vpa/dec/shigella 规则与 report 依赖都未按物种门控。
"""

from __future__ import annotations

from bacmap.core.analysis.routing import report_inputs, serotype_engine, uses_gapit_db

_COMMON = {
    "qc_json",
    "assembly_stats",
    "species_id",
    "mlst",
    "vfdb",
    "card",
    "amrfinderplus",
    "plasmidfinder",
    "gapit_typing",
    "annotation",
}


def _extra(species_value: str) -> set[str]:
    return set(report_inputs("S1", species_value, "/w")) - _COMMON


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
    def test_ecoli_dec_only_where_declared(self):
        assert uses_gapit_db("DEC", "ecoli_dec") is True
        # 志贺菌的血清型走 ShigaTyper；registry 未为其声明 ecoli_dec
        assert uses_gapit_db("Shigella", "ecoli_dec") is False
        assert uses_gapit_db("SAL", "ecoli_dec") is False
        assert uses_gapit_db("V_parahaemolyticus", "ecoli_dec") is False

    def test_vpara_only_for_vpara(self):
        assert uses_gapit_db("V_parahaemolyticus", "vpara_virulence") is True
        assert uses_gapit_db("DEC", "vpara_virulence") is False


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
        # LMO 的血清群由 gapit lm_doumith 给出（走 gapit_typing），不额外起步骤
        assert _extra("Listeria_monocytogenes") == set()

    def test_unknown_species_has_no_species_steps(self):
        assert _extra("not_a_species") == set()

    def test_common_inputs_always_present(self):
        files = report_inputs("S1", "DEC", "/w")
        assert _COMMON <= set(files)
        assert files["gapit_typing"] == "/w/S1/gapit/typing.json"
