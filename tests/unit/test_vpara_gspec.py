"""gspec 通用筛查归一测试（ADR-20；v1.4.41 起无逐菌专用规则与打包私有库）。

覆盖：毒力标记（tdh/trh/tlh，按基因名扫库）与 ecoh O/H 血清型的 core 归一。
库本体来自官方 gspec catalog（``vpa_vf``/``vpa_ok``/``lmo_sero``/``ecoh`` …），
经 ``gspec db install`` 安装，由通用 gspec_typing 规则筛查。
"""

from __future__ import annotations

from bacmap.core.analysis.gspec_typing import (
    ecoh_serotype_summary,
    summarize,
    virulence_marks,
)


class TestVirulenceMarks:
    def test_marks_from_official_vpa_vf(self):
        out = virulence_marks(
            {"vpa_vf": {"status": "ran", "genes": ["tdh", "tlh"]}}
        )
        assert out["tool"] == "gspec"
        assert out["database"] == "vpa_vf"
        assert out["tdh"] is True and out["tlh"] is True and out["trh"] is False
        assert out["n_hits"] == 2 and len(out["hits"]) == 2

    def test_legacy_custom_db_still_counts(self):
        """v1.4.41 前的私有 vpara_virulence 库（用户显式 override）同样命中。"""
        out = virulence_marks(
            {"vpara_virulence": {"status": "ran", "genes": ["TDH", "TRH"]}}
        )
        assert out["database"] == "vpara_virulence"
        assert out["tdh"] is True and out["trh"] is True

    def test_none_when_no_db_ran(self):
        assert virulence_marks({}) is None
        assert virulence_marks(None) is None
        # 库未安装（unavailable）→ 能力未就绪，不产生毒力段
        assert virulence_marks({"vpa_vf": {"status": "unavailable", "genes": []}}) is None

    def test_no_scheme_library_still_counts(self):
        """gene 库无 typing scheme（如 vpa_vf）——screen 命中仍是有效结论。"""
        out = virulence_marks(
            {"vpa_vf": {"status": "no_scheme", "genes": ["tlh", "tdh"]}}
        )
        assert out["tdh"] is True and out["tlh"] is True
        assert out["database"] == "vpa_vf"

    def test_failed_library_ignored(self):
        assert (
            virulence_marks({"vpa_vf": {"status": "failed", "genes": ["tdh"]}}) is None
        )

    def test_no_marker_genes_means_none(self):
        # 库跑了但不含 tdh/trh/tlh → 该样本无毒力标记段
        assert (
            virulence_marks({"vpa_pai": {"status": "ran", "genes": ["VP1258"]}}) is None
        )

    def test_multiple_dbs_merged(self):
        out = virulence_marks(
            {
                "vpa_vf": {"status": "ran", "genes": ["tdh"]},
                "other": {"status": "ran", "genes": ["trh"]},
            }
        )
        assert out["tdh"] is True and out["trh"] is True


class TestEcohSerotypeSummary:
    def test_none_when_db_absent(self):
        assert ecoh_serotype_summary(None) is None

    def test_no_scheme_reports_unavailable(self):
        out = ecoh_serotype_summary(
            {"status": "no_scheme", "error": "database 'ecoh' carries no typing scheme"}
        )
        assert out["serotype"] == "N/A"
        assert out["status"] == "no_scheme"
        assert "reason" in out

    def test_schemes_become_serotype(self):
        out = ecoh_serotype_summary(
            {
                "status": "ran",
                "schemes": {"oh_serotype": "O157:H7", "o_type": "O157", "h_type": "H7"},
            }
        )
        assert out["serotype"] == "O157:H7"
        assert out["o_type"] == "O157" and out["h_type"] == "H7"


class TestSummarizeShape:
    def test_databases_passthrough_with_genes(self):
        out = summarize(
            {
                "status": "ran",
                "databases": {"vpa_vf": {"status": "ran", "genes": ["tlh"]}},
            }
        )
        assert out["databases"]["vpa_vf"]["genes"] == ["tlh"]
