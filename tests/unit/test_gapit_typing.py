"""gapit 分型结果归一（run_gapit_typing.json → summary 字段）。"""

from __future__ import annotations

from bacmap.core.analysis.gapit_typing import summarize


def _payload(status: str, databases: dict) -> dict:
    return {"status": status, "databases": databases}


class TestSummarizeGapitTyping:
    def test_serogroup_extracted_from_doumith(self):
        out = summarize(
            _payload(
                "ran",
                {
                    "lm_doumith": {
                        "status": "ran",
                        "schemes": {"doumith_serogroup": "IIa"},
                        "confidence": "high",
                        "genes": ["lmo0737", "prs"],
                    }
                },
            )
        )
        assert out["serogroup"] == "IIa"
        assert out["serogroup_scheme"] == "doumith_serogroup"
        assert out["databases"]["lm_doumith"]["confidence"] == "high"
        assert out["databases"]["lm_doumith"]["genes"] == ["lmo0737", "prs"]

    def test_no_scheme_is_preserved(self):
        out = summarize(
            _payload(
                "empty",
                {"ecoh": {"status": "no_scheme", "error": "carries no typing scheme"}},
            )
        )
        assert out["serogroup"] == ""
        assert out["databases"]["ecoh"]["status"] == "no_scheme"
        assert "no typing scheme" in out["databases"]["ecoh"]["error"]

    def test_non_serogroup_scheme_not_used_as_serogroup(self):
        out = summarize(
            _payload("ran", {"ecoli_dec": {"status": "ran", "schemes": {"gb4789_6": "EHEC"}}})
        )
        assert out["serogroup"] == ""
        assert out["databases"]["ecoli_dec"]["schemes"] == {"gb4789_6": "EHEC"}

    def test_malformed_inputs_are_safe(self):
        for payload in (None, {}, {"databases": "oops"}, {"databases": {"db": None}}):
            out = summarize(payload)
            assert isinstance(out["databases"], dict)
            assert out["serogroup"] == ""
