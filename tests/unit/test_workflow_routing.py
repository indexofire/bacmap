"""工作流路由：按病原注册表决定每个样本适用的种以下步骤（v1.4.24）。

回归：ECO 样本曾无条件触发 SISTR（沙门菌工具）、ShigaTyper/vpara 步骤（ShigaTyper 已迁 gspec shi_sero）；
vpa/dec/shigella 规则与 report 依赖都未按物种门控。
"""

from __future__ import annotations

from bacmap.core.analysis.routing import report_inputs, serotype_engine, uses_gspec_db

_COMMON = {
    "qc_json",
    "assembly_stats",
    "quast",
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
        assert serotype_engine("SAL") == ""  # v1.10.24：沙门菌迁移到 gspec sen_sero_sistr
        assert serotype_engine("Shigella") == ""  # 志贺菌血清型由 gspec shi_sero 承担
        assert serotype_engine("DEC") == "ecoh"
        assert serotype_engine("Escherichia_coli") == "ecoh"

    def test_no_engine(self):
        assert serotype_engine("Listeria_monocytogenes") == ""
        assert serotype_engine("not_a_species") == ""


class TestGspecDbRouting:
    def test_eco_dec_only_where_declared(self):
        assert uses_gspec_db("DEC", "eco_dec") is True
        # 志贺菌血清型走 gspec shi_sero；registry 未为其声明 eco_dec
        assert uses_gspec_db("Shigella", "eco_dec") is False
        assert uses_gspec_db("SAL", "eco_dec") is False
        assert uses_gspec_db("V_parahaemolyticus", "eco_dec") is False

    def test_vpara_only_for_vpara(self):
        # v1.4.41：VPA 默认库为官方 gspec catalog 的 vpa_vf/vpa_ok/vpa_pai；
        # 旧私有库名 vpara_virulence 仅在用户显式 override 时生效。
        assert uses_gspec_db("V_parahaemolyticus", "vpa_vf") is True
        assert uses_gspec_db("DEC", "vpa_vf") is False


class TestReportInputsGating:
    """summary 依赖只含适用步骤：不适用者不进入 DAG（也就不会跑外部工具）。"""

    def test_ecoli(self):
        # ecoh O/H 能力状态出自 gspec typing.json（collect_summary 归一），
        # 不再有逐菌占位文件（v1.4.41）。
        extra = _extra("DEC")
        assert extra == {"pathotype"}

    def test_salmonella(self):
        # v1.10.24：沙门菌迁移到 gspec sen_sero_sistr——无 SISTR 专用输入
        extra = _extra("SAL")
        assert extra == set()

    def test_shigella(self):
        # 志贺菌血清型由 gspec shi_sero（通用 gspec_typing 产物）承担，
        # 不再有读段级 ShigaTyper 专用输入。
        assert _extra("Shigella") == set()

    def test_vpara(self):
        # v1.4.41：毒力标记（vpara_virulence）与 O/K（vpa_ok）都由通用
        # gspec_typing 聚合产物提供，无逐菌专用输入。
        extra = _extra("V_parahaemolyticus")
        assert extra == set()

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
            GspecSelection,
            SpeciesSelection,
            ToolSelection,
        )

        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GspecSelection(mode="replace", databases=["vpa_ok", "vpa_pai"])
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
        # v1.4.41：replace 掉 vpara_virulence 后无任何逐菌专用输入；
        # vpa_ok/vpa_pai 全部经 gspec_typing 聚合产物进入 summary。
        assert extra == set()

    def test_extend_keeps_vpara_special_steps(self):
        from bacmap.core.tool_selection import (
            GspecSelection,
            SpeciesSelection,
            ToolSelection,
        )

        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GspecSelection(mode="extend", databases=["vpa_ok"])
                )
            }
        )
        extra = set(
            report_inputs(
                "S1", "V_parahaemolyticus", "/w", selection=selection
            )
        ) - _COMMON
        assert extra == set()

    def test_sample_override_applies_to_special_steps(self):
        from bacmap.core.tool_selection import (
            GspecSelection,
            SampleSelection,
            SpeciesSelection,
            ToolSelection,
        )

        selection = ToolSelection(
            species={
                "VPA": SpeciesSelection(
                    gspec=GspecSelection(mode="replace", databases=["vpa_ok"])
                )
            },
            samples={
                "S1": SampleSelection(
                    gspec=GspecSelection(databases=["vpara_virulence"])
                )
            },
        )
        assert (
            uses_gspec_db(
                "V_parahaemolyticus", "vpara_virulence", selection=selection, sample="S1"
            )
            is True
        )
