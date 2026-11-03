"""暴发事件挖掘、敏感性分析与真实数据敏感性字段。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.research.outbreak import OutbreakEvent, event_period, summarize_outbreak
from bacmap.research.stats import e_value_odds_ratio, sensitivity_summary


class TestOutbreakEvents:
    def test_period_precision(self):
        assert event_period("2012-03-14") == "2012-03"
        assert event_period("2012-XX-XX") == "2012"
        assert event_period("XXXX-XX-XX") == ""
        assert event_period("") == ""
        assert event_period("2012-13-01") == "2012"
        assert event_period("2012-00-01") == "2012"

    def test_clusters_are_location_period_and_unknown_is_sporadic(self):
        events = [
            OutbreakEvent(case_id="A", event_date="2020-01-02", location="Ward1",
                          source="S1", phenotype="Resistant"),
            OutbreakEvent(case_id="B", event_date="2020-01-20", location="Ward1",
                          source="S1", phenotype="Susceptible"),
            OutbreakEvent(case_id="C", event_date="2020-02-01", location="Ward1",
                          source="S1", phenotype="Resistant"),
            OutbreakEvent(case_id="D", event_date="XXXX-XX-XX", location="Ward1",
                          source="S2", phenotype="Resistant"),
        ]
        report = summarize_outbreak(events)
        assert report["n_events"] == 4
        assert report["n_clusters"] == 3
        assert report["n_clustered_events"] == 2
        assert report["n_sporadic_events"] == 2
        assert any(c["period"] == "unknown-date" and c["sporadic"] for c in report["clusters"])

    def test_source_mining_and_caveat(self):
        events = [
            OutbreakEvent(case_id=f"R{i}", event_date="2020-01", location="W",
                          source="OutbreakA", phenotype="Resistant")
            for i in range(8)
        ] + [
            OutbreakEvent(case_id=f"S{i}", event_date="2020-02", location="W",
                          source="SporadicB", phenotype="Susceptible")
            for i in range(8)
        ]
        report = summarize_outbreak(events, min_count=5)
        source = next(m for m in report["mining"] if m["exposure"] == "source")
        top = source["associations"][0]
        assert top["category"] == "OutbreakA"
        assert top["odds_ratio"] > 1
        assert top["q_value"] is not None and top["q_value"] < 0.05
        assert "no transmission direction" in source["caveat"]

    def test_lineage_mining_only_when_present(self):
        events = [
            OutbreakEvent(case_id="A", event_date="2020", source="S", phenotype="R",
                          lineage="L1"),
            OutbreakEvent(case_id="B", event_date="2020", source="S", phenotype="S"),
        ]
        report = summarize_outbreak(events, min_count=1)
        assert {m["exposure"] for m in report["mining"]} == {"clustered", "source", "lineage"}


class TestStatInputValidation:
    def test_bh_rejects_out_of_range_p(self):
        from bacmap.research.stats import benjamini_hochberg

        with pytest.raises(ValueError, match="out of range"):
            benjamini_hochberg([-0.1])
        with pytest.raises(ValueError, match="out of range"):
            benjamini_hochberg([1.1])

    def test_counts_reject_negative_cells(self):
        from bacmap.research.stats import associate_counts

        with pytest.raises(ValueError, match="non-negative"):
            associate_counts(-1, 2, 3, 4)

    def test_large_n_approximation_is_disclosed(self):
        from bacmap.research.stats import associate_counts

        stat = associate_counts(1000, 1000, 1000, 1000)
        assert stat.odds_ratio == pytest.approx(1.0)
        assert any("normal approximation" in d for d in stat.diagnostics)


class TestSensitivity:
    def test_e_value(self):
        assert e_value_odds_ratio(None) is None
        assert e_value_odds_ratio(1.0) == pytest.approx(1.0)
        assert e_value_odds_ratio(4.0) == pytest.approx(2 + 2 ** 0.5)
        assert e_value_odds_ratio(0.25) == pytest.approx(2 + 2 ** 0.5)

    def test_mantel_haenszel_removes_confounding_and_leave_one_out(self):
        table = (70, 60, 30, 20)
        strata = [
            ("A", 30, 20, 5, 2),
            ("B", 25, 25, 10, 8),
            ("C", 15, 15, 15, 10),
        ]
        out = sensitivity_summary(table, strata)
        assert out["crude"]["odds_ratio"] is not None
        assert out["adjusted"]["odds_ratio"] is not None
        assert out["adjusted"]["n_strata"] == 3
        assert out["adjusted"]["e_value"] is not None
        assert out["leave_one_out"]["min_odds_ratio"] <= out["adjusted"]["odds_ratio"]
        assert out["leave_one_out"]["max_odds_ratio"] >= out["adjusted"]["odds_ratio"]

    def test_sensitivity_without_strata(self):
        out = sensitivity_summary((6, 1, 2, 7))
        assert out["adjusted"] is None and out["leave_one_out"] is None
        assert out["e_value_crude"] is not None


class TestRealBenchmarkSensitivity:
    def test_bvbrc_benchmark_reports_adjusted_and_loo(self, tmp_path: Path):
        from bacmap.research.benchmarks import run_bvbrc_amr_benchmark

        (tmp_path / "labels.csv").write_text(
            "genome_id,phenotype,isolation_source\n"
            "G1,Resistant,blood\nG2,Resistant,blood\n"
            "G3,Susceptible,urine\nG4,Susceptible,urine\n",
            encoding="utf-8",
        )
        (tmp_path / "genes.csv").write_text(
            "genome_id,gene,product\n"
            "G1,KPC-2,KPC family\nG2,KPC-2,KPC family\n",
            encoding="utf-8",
        )
        out = run_bvbrc_amr_benchmark(tmp_path)
        kpc = next(c for c in out["cases"] if c["target"] == "KPC")
        assert kpc["sensitivity"]["adjusted"]["method"] == "Mantel-Haenszel"
        assert kpc["sensitivity"]["adjusted"]["n_strata"] == 2
        assert kpc["sensitivity"]["leave_one_out"] is not None
