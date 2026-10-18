"""DEC 致病型结果归一（gapit typing_result → summary 字段）。"""

from __future__ import annotations

from bacmap.core.analysis.dec_pathotype import summarize


def _ran(phenotypes: dict, genes: list[str] | None = None) -> dict:
    return {
        "status": "ran",
        "db": "ecoli_dec",
        "files": [
            {
                "file": "contigs.fasta",
                "genes": genes or ["escV", "stx1a", "uidA"],
                "phenotypes": phenotypes,
            }
        ],
    }


class TestSummarize:
    def test_prefers_gb4789_6_scheme(self):
        payload = _ran(
            {
                "gb4789_6": {
                    "phenotype": "EHEC",
                    "score": 1.0,
                    "confidence": "high",
                    "runner_up": {"phenotype": "STEC", "score": 0.0},
                },
                "risk_monitoring": {"phenotype": "STEC", "confidence": "medium"},
            }
        )
        out = summarize(payload)
        assert out["pathotype"] == "EHEC"
        assert out["pathotype_scheme"] == "gb4789_6"
        assert out["pathotype_confidence"] == "high"
        assert out["pathotype_runner_up"] == "STEC"
        assert out["pathotype_genes"] == ["escV", "stx1a", "uidA"]
        assert out["pathotype_schemes"] == {"gb4789_6": "EHEC", "risk_monitoring": "STEC"}

    def test_falls_back_to_first_scheme(self):
        out = summarize(_ran({"custom": {"phenotype": "ETEC", "confidence": "low"}}))
        assert out["pathotype"] == "ETEC"
        assert out["pathotype_scheme"] == "custom"

    def test_non_dec_phenotype_is_kept(self):
        out = summarize(_ran({"gb4789_6": {"phenotype": "non-DEC", "confidence": "high"}}))
        assert out["pathotype"] == "non-DEC"

    def test_skipped_and_failed_are_na(self):
        for payload in (
            {"status": "skipped", "reason": "gapit not found"},
            {"status": "failed", "stage": "screen", "error": "boom"},
            None,
            {},
            "not-a-dict",
        ):
            out = summarize(payload)
            assert out["pathotype"] == "N/A"
            assert out["pathotype_genes"] == []

    def test_malformed_files_do_not_crash(self):
        assert summarize({"status": "ran", "files": "oops"})["pathotype"] == "N/A"
        assert summarize({"status": "ran", "files": [{"phenotypes": None}]})["pathotype"] == "N/A"
        assert summarize({"status": "ran", "files": [{"phenotypes": {"gb4789_6": None}}]})[
            "pathotype"
        ] == "N/A"
