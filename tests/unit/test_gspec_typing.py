"""gspec 分型结果归一（run_gspec_typing.json → summary 字段）。"""

from __future__ import annotations

from bacmap.core.analysis.gspec_typing import summarize


def _payload(status: str, databases: dict) -> dict:
    return {"status": status, "databases": databases}


class TestSummarizeGspecTyping:
    def test_serogroup_extracted_from_doumith(self):
        out = summarize(
            _payload(
                "ran",
                {
                    "lmo_sero": {
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
        assert out["databases"]["lmo_sero"]["confidence"] == "high"
        assert out["databases"]["lmo_sero"]["genes"] == ["lmo0737", "prs"]

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
            _payload("ran", {"eco_dec": {"status": "ran", "schemes": {"gb4789_6": "EHEC"}}})
        )
        assert out["serogroup"] == ""
        assert out["databases"]["eco_dec"]["schemes"] == {"gb4789_6": "EHEC"}

    def test_malformed_inputs_are_safe(self):
        for payload in (None, {}, {"databases": "oops"}, {"databases": {"db": None}}):
            out = summarize(payload)
            assert isinstance(out["databases"], dict)
            assert out["serogroup"] == ""


class TestClusterPreservation:
    def test_cluster_fields_pass_through(self):
        out = summarize(
            _payload(
                "ran",
                {
                    "vpa_ok": {
                        "kind": "cluster",
                        "status": "ran",
                        "best_locus": "OL3",
                        "type": "O3",
                        "phenotype": "O3:K6",
                        "phenotypes": {
                            "o_group": {"phenotype": "O3", "confidence": "high"},
                            "k_group": {"phenotype": "K6", "confidence": "high"},
                        },
                        "loci_count": 2,
                        "raw_schema": "gspec.cluster/2",
                    }
                },
            )
        )
        entry = out["databases"]["vpa_ok"]
        assert entry["kind"] == "cluster"
        assert entry["phenotype"] == "O3:K6"
        assert entry["phenotypes"]["o_group"]["phenotype"] == "O3"
        assert entry["best_locus"] == "OL3"
        assert entry["loci_count"] == 2
