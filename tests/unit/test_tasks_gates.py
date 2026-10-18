"""门框架测试（冻结设计 §8 V11① 核心语义：矛盾解读必须被拦截）。"""

from __future__ import annotations

from bacmap.tasks import gates
from bacmap.tasks.gates import GateVerdict


def _summary(steps: dict) -> dict:
    return {"sample": "SAM-001", "steps": steps}


def _salmonella_steps() -> dict:
    return {
        "species": {"verdict": "Salmonella", "markers": {"invA": "positive"}},
        "mlst": (
            "FILE\tSCHEME\tST\taroC\tdnaN\themD\thisD\tpurE\tsucA\tthrA\n"
            "contigs\tsalmonella_2\t19\t2\t7\t12\t9\t5\t9\t3"
        ),
        "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
        "amr": {
            "abricate_card": [{"GENE": "blaCTX-M-15"}, {"GENE": "tet(A)"}],
            "abricate_vfdb": [{"GENE": "ssrA"}],
        },
        "plasmid": {"plasmidfinder": [{"GENE": "IncFIB"}]},
        "dec": {},
    }


class TestAnalysisClaimsGate:
    def test_consistent_interpretation_passes(self):
        s = _summary(_salmonella_steps())
        r = gates.evaluate_analysis_claims(
            "该菌株鉴定为 Salmonella，ST19，血清型 Typhimurium，检出 blaCTX-M-15。",
            s,
            "SAM-001",
        )
        assert r.verdict == GateVerdict.PASS
        assert r.gate == "analysis_claims"
        assert r.details["sample_id"] == "SAM-001"

    def test_contradictory_species_and_negated_amr_needs_review(self):
        s = _summary(_salmonella_steps())
        r = gates.evaluate_analysis_claims(
            "该菌株为 E. coli，未检出 blaCTX-M-15。",
            s,
            "SAM-001",
        )
        assert r.verdict == GateVerdict.NEEDS_HUMAN_REVIEW
        assert r.details["contradicted_count"] >= 1

    def test_unsupported_species_rejected(self):
        steps = _salmonella_steps()
        steps["species"] = {"verdict": "Listeria"}
        r = gates.evaluate_analysis_claims(
            "该菌株为 Listeria。", _summary(steps), "SAM-001"
        )
        assert r.verdict == GateVerdict.REJECT
        assert r.details["reason"] == "species_not_supported"

    def test_dec_verdict_is_supported_not_rejected(self):
        steps = _salmonella_steps()
        steps["species"] = {"verdict": "DEC"}
        r = gates.evaluate_analysis_claims(
            "检出 blaCTX-M-15。", _summary(steps), "SAM-001"
        )
        assert r.verdict != GateVerdict.REJECT

    def test_empty_interpretation_passes_with_zero_verifiable(self):
        s = _summary(_salmonella_steps())
        r = gates.evaluate_analysis_claims("", s, "SAM-001")
        assert r.verdict == GateVerdict.PASS
        assert r.details["verifiable_count"] == 0

    def test_placeholder_gside_species_not_rejected(self):
        steps = _salmonella_steps()
        steps["species"] = {"species": "pending_gside"}
        r = gates.evaluate_analysis_claims("检出 blaCTX-M-15。", _summary(steps), "SAM-001")
        # pending_gside 无法映射到支持集 —— 但这是占位而非数据错误？
        # 当前设计：不可映射即 REJECT（占位期解读门以此暴露集成缺口）
        assert r.verdict == GateVerdict.REJECT


class TestGateRegistry:
    def test_evaluate_dispatches_analysis_claims(self):
        s = _summary(_salmonella_steps())
        payload = {
            "interpretation_text": "鉴定为 Salmonella。",
            "summary": s,
            "sample_id": "SAM-001",
        }
        r = gates.evaluate(gates.GateSubject(gate="analysis_claims", payload=payload))
        assert r.gate == "analysis_claims"

    def test_unknown_gate_raises(self):
        import pytest

        with pytest.raises(KeyError):
            gates.evaluate(gates.GateSubject(gate="nope", payload={}))

    def test_all_four_gates_dispatch(self):
        """四道门全部真实实现后，evaluate 均可分发（不再有占位门）。"""
        for name in ("analysis_claims", "baseline_release", "mining", "citation"):
            assert name in gates.GATES, f"gate {name} not registered"


class TestCitationGateDoi:
    """DOI 引用必须被提取并过门（修复前：DOI 完全绕过引用门）。"""

    def test_unknown_doi_rejected(self):
        res = gates.evaluate_citation(
            {"draft": "结论见 (doi:10.1128/JCM.00123-23)。", "known_citations": []}
        )
        assert res.verdict.value == "reject"
        assert "10.1128/jcm.00123-23" in res.details["unknown"]

    def test_known_doi_passes(self):
        res = gates.evaluate_citation(
            {
                "draft": "结论见 (doi:10.1128/JCM.00123-23)。",
                "known_citations": ["10.1128/JCM.00123-23"],
            }
        )
        assert res.verdict.value == "pass"

    def test_doi_case_insensitive_and_trimming(self):
        res = gates.evaluate_citation(
            {"draft": "见 doi:10.1093/JAC/dkaa123.", "known_citations": ["10.1093/jac/dkaa123"]}
        )
        assert res.verdict.value == "pass"
        assert res.details["citations_found"] == ["10.1093/jac/dkaa123"]

    def test_pmid_still_works_regression(self):
        res = gates.evaluate_citation({"draft": "见 PMID:12345678", "known_citations": []})
        assert res.verdict.value == "reject"
        assert res.details["unknown"] == ["12345678"]


class TestCitationGateDoiResearch:
    """循环 3（调研驱动）：Crossref 推荐字符类 + CJK 贴邻可匹配。"""

    def test_doi_glued_to_cjk_matches(self):
        res = gates.evaluate_citation(
            {"draft": "见文献10.1128/JCM.00123-23。", "known_citations": []}
        )
        assert res.verdict.value == "reject"
        assert "10.1128/jcm.00123-23" in res.details["unknown"]

    def test_no_false_positive_inside_number(self):
        res = gates.evaluate_citation(
            {"draft": "样本编号210.1234/abc", "known_citations": []}
        )
        assert res.details["citations_found"] == []

    def test_doi_tail_restricted_to_crossref_charset(self):
        res = gates.evaluate_citation(
            {"draft": "见 10.1128/JCM.00123-23后面的中文", "known_citations": []}
        )
        assert res.details["citations_found"] == ["10.1128/jcm.00123-23"]


class TestGateInputRobustness:
    """门必须对畸形输入 fail-closed（REJECT），不得在门里抛异常（C5 强制力）。"""

    def test_baseline_release_malformed_strains_rejected(self):
        r = gates.evaluate_baseline_release({"strains": "not-a-list"})
        assert r.verdict == GateVerdict.REJECT
        assert "empty_candidate" in r.details["problems"]

    def test_baseline_release_non_dict_excluded_counted_as_zero(self):
        r = gates.evaluate_baseline_release({"strains": [], "excluded": 3})
        assert r.details["n_excluded"] == 0

    def test_mining_malformed_artifacts_rejected(self):
        r = gates.evaluate_mining({"artifacts": "oops", "signed_by": "x"})
        assert r.verdict == GateVerdict.REJECT
        assert "malformed_artifacts" in r.details["problems"]

    def test_mining_artifact_without_name_rejected(self):
        r = gates.evaluate_mining({"artifacts": [{"reproducible": True}], "signed_by": "x"})
        assert r.verdict == GateVerdict.REJECT
        assert "artifact_missing_name" in r.details["problems"]

    def test_citation_non_list_known_is_fail_closed(self):
        r = gates.evaluate_citation(
            {"draft": "见 [12345678]", "known_citations": "12345678"}
        )
        assert r.verdict == GateVerdict.REJECT
