"""P4 样本量/把握度与外部验证（确定性、纯标准库）。"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from bacmap.research import power
from bacmap.research.models import CreateSessionRequest, ResearchError, ResearchProfile
from bacmap.research.service import ResearchService
from bacmap.research.stats import associate_counts
from bacmap.store import runs


def _workflow_dir(home: Path) -> Path:
    wf = home / "workflows" / "bacmap" / "config"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "config.yaml").write_text("threads: 2\n")
    return home / "workflows" / "bacmap"


def _run(home: Path, strains: list[str], run_id: str) -> None:
    _workflow_dir(home)
    run = runs.create_run(
        "bacmap", home / "workflows" / "bacmap", strains,
        db_path=home / "runs.sqlite", task_id="task-1",
    )
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute(
            "UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", (run_id, run.run_id)
        )


def _gom(home: Path, genes: dict[str, list[str]]) -> None:
    from bacmap.store.genome_object_service import ensure_gom_schema

    ensure_gom_schema(home / "gom.sqlite")
    with sqlite3.connect(home / "gom.sqlite") as conn:
        for sid, names in genes.items():
            for name in names:
                conn.execute(
                    "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                    " VALUES (?,?,?)",
                    (sid, name, "card"),
                )


def _labs(home: Path, values: dict[str, str]) -> None:
    from bacmap.store.lab_results import LabResultService

    with LabResultService(home / "data" / "bacmap.sqlite") as svc:
        for sid, interp in values.items():
            svc.add(sid, "mic", "meropenem", "0.25", interpretation=interp)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    strains = [f"S{i}" for i in range(16)]
    _run(tmp_path, strains, "run-1")
    _gom(tmp_path, {s: ["blaKPC-33"] for s in strains[:7]})
    _labs(
        tmp_path,
        {
            **{s: "R" for s in strains[:6]},
            "S6": "S",
            **{s: "R" for s in strains[7:9]},
            **{s: "S" for s in strains[9:]},
        },
    )
    return tmp_path


class TestProportionsFromOdds:
    def test_conversion_roundtrip(self):
        p1 = power.proportions_from_odds(0.2, 4.0)
        assert p1 == pytest.approx(0.5)
        assert power.proportions_from_odds(0.2, 1.0) == pytest.approx(0.2)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            power.proportions_from_odds(1.5, 2.0)
        with pytest.raises(ValueError):
            power.proportions_from_odds(0.2, 0.0)


class TestSampleSize:
    def test_size_reaches_target_power(self):
        # 自洽闭环：ceil 后的 n 代回把握度应 >= 目标（正态近似主式自洽）
        plan = power.sample_size_two_proportions(p1=0.65, p2=0.45)
        check = power.achieved_power_two_proportions(
            n1=plan["n1"], n2=plan["n2"], p1=0.65, p2=0.45
        )
        assert check["power"] >= 0.80
        assert plan["n1"] == plan["n2"]  # ratio=1
        assert plan["n_total"] == plan["n1"] + plan["n2"]

    def test_smaller_difference_needs_more_samples(self):
        big = power.sample_size_two_proportions(p1=0.80, p2=0.20)
        small = power.sample_size_two_proportions(p1=0.55, p2=0.45)
        assert small["n1"] > big["n1"]

    def test_higher_power_needs_more_samples(self):
        low = power.sample_size_two_proportions(p1=0.6, p2=0.3, power=0.80)
        high = power.sample_size_two_proportions(p1=0.6, p2=0.3, power=0.90)
        assert high["n1"] > low["n1"]

    def test_stricter_alpha_needs_more_samples(self):
        lax = power.sample_size_two_proportions(p1=0.6, p2=0.3, alpha=0.10)
        strict = power.sample_size_two_proportions(p1=0.6, p2=0.3, alpha=0.01)
        assert strict["n1"] > lax["n1"]

    def test_ratio_allocates_uneven_groups(self):
        plan = power.sample_size_two_proportions(p1=0.6, p2=0.3, ratio=2.0)
        assert plan["n2"] >= 2 * plan["n1"] - 1  # ceil 后近似 2:1

    def test_equal_proportions_rejected(self):
        with pytest.raises(ValueError, match="nothing to detect"):
            power.sample_size_two_proportions(p1=0.5, p2=0.5)

    def test_extreme_proportion_cautioned(self):
        plan = power.sample_size_two_proportions(p1=0.99, p2=0.90)
        assert any("extreme" in note for note in plan["caution"])

    def test_reference_case_two_sided_0505_80pct(self):
        # 教科书常用例（0.65 vs 0.45）量级合理性：百例/组附近，不数百倍偏差
        plan = power.sample_size_two_proportions(p1=0.65, p2=0.45)
        assert 80 <= plan["n1"] <= 200


class TestAchievedPower:
    def test_power_grows_with_n(self):
        small = power.achieved_power_two_proportions(n1=20, n2=20, p1=0.7, p2=0.3)
        large = power.achieved_power_two_proportions(n1=200, n2=200, p1=0.7, p2=0.3)
        assert large["power"] > small["power"] > 0
        assert large["power"] <= 1

    def test_null_rejected(self):
        with pytest.raises(ValueError, match="null"):
            power.achieved_power_two_proportions(n1=10, n2=10, p1=0.5, p2=0.5)

    def test_design_input_note_present(self):
        out = power.achieved_power_two_proportions(n1=50, n2=50, p1=0.7, p2=0.4)
        assert "post-hoc" in out["note"]


class TestSessionPower:
    def test_power_for_session_uses_observed_proportions(self, home: Path):
        view = ResearchService(home).create_session(
            CreateSessionRequest(
                run_id="run-1", gene="blaKPC-33", test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
            ),
            actor="t",
        )
        plan = power.power_for_session(home, view.session.session_id)
        assert plan["schema"] == power.POWER_SCHEMA
        assert plan["design_input_from_session"] == view.session.session_id
        obs = plan["observed"]
        assert obs["p1_resistant_given_gene_pos"] == pytest.approx(6 / 7)
        assert obs["n1_gene_pos"] == 7
        assert 0 <= obs["achieved_power_at_current_n"] <= 1
        assert "not" in plan["note"]  # 明示不是事后功效

    def test_missing_session(self, home: Path):
        with pytest.raises(ResearchError) as exc:
            power.power_for_session(home, "rs-nope")
        assert exc.value.code == "not_found"


class TestExternalValidation:
    def test_identical_estimates_are_consistent(self):
        stat = associate_counts(20, 2, 2, 20)
        out = power.external_validation(stat, associate_counts(20, 2, 2, 20))
        assert out["schema"] == power.VALIDATION_SCHEMA
        assert out["consistent"] is True
        assert out["q_statistic"] == pytest.approx(0.0, abs=1e-9)
        assert out["p_value"] == pytest.approx(1.0)

    def test_opposite_estimates_are_heterogeneous(self):
        derivation = associate_counts(20, 2, 2, 20)  # OR ~ 100
        validation = associate_counts(2, 20, 20, 2)  # OR ~ 0.01
        out = power.external_validation(derivation, validation)
        assert out["consistent"] is False
        assert out["p_value"] < 0.05
        assert "contradicts" in out["interpretation"]

    def test_pooled_or_between_estimates(self):
        strong = associate_counts(20, 2, 2, 20)
        weak = associate_counts(6, 2, 2, 6)  # 同向、更弱
        out = power.external_validation(strong, weak)
        ors = sorted(s["odds_ratio"] for s in out["cohorts"])
        assert ors[0] <= out["pooled_odds_ratio"] <= ors[1] + 1e-9

    def test_validate_sessions_end_to_end(self, home: Path):
        _run(home, [f"T{i}" for i in range(12)], "run-2")
        _gom(home, {f"T{i}": ["blaKPC-33"] for i in range(4)})
        _labs(
            home,
            {**{f"T{i}": "R" for i in range(3)}, **{f"T{i}": "S" for i in range(3, 12)}},
        )
        service = ResearchService(home)
        first = service.create_session(
            CreateSessionRequest(
                run_id="run-1", gene="blaKPC-33", test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
            ),
            actor="t",
        )
        second = service.create_session(
            CreateSessionRequest(
                run_id="run-2", gene="blaKPC-33", test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
            ),
            actor="t",
        )
        out = power.validate_sessions(
            home, first.session.session_id, second.session.session_id
        )
        assert out["derivation_session"] == first.session.session_id
        assert out["validation_session"] == second.session.session_id
        assert len(out["cohorts"]) == 2
        assert math.isfinite(out["pooled_odds_ratio"])

    def test_missing_validation_session(self, home: Path):
        view = ResearchService(home).create_session(
            CreateSessionRequest(
                run_id="run-1", gene="blaKPC-33", test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
            ),
            actor="t",
        )
        with pytest.raises(ResearchError) as exc:
            power.validate_sessions(home, view.session.session_id, "rs-nope")
        assert exc.value.code == "not_found"
