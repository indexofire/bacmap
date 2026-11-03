"""P3 第一片：候选评分、预算与防泄漏边界。"""

from __future__ import annotations

import pytest

from bacmap.research.discovery import (
    ExploreBudget,
    explore_candidates,
    score_candidate,
)


def _cases():
    return [
        {"exposure": "KPC", "outcome": "meropenem", "table": (20, 2, 2, 20)},
        {"exposure": "CTX-M", "outcome": "meropenem", "table": (5, 5, 5, 5)},
        {"exposure": "rare", "outcome": "meropenem", "table": (1, 0, 0, 1)},
    ]


class TestCandidateScoring:
    def test_score_rewards_low_q_and_large_effect(self):
        assert score_candidate(None, 4.0, 100) == 0.0
        assert score_candidate(0.01, 4.0, 100) > score_candidate(0.04, 4.0, 100)
        assert score_candidate(0.01, 10.0, 100) > score_candidate(0.01, 2.0, 100)
        assert score_candidate(0.01, 4.0, 200) > score_candidate(0.01, 4.0, 50)

    def test_explore_filters_and_ranks(self):
        out = explore_candidates("study-1", _cases(), ExploreBudget(min_n=20, max_q=0.05))
        assert out["role"] == "screening"
        assert [c["exposure"] for c in out["candidates"]] == ["KPC"]
        assert out["candidates"][0]["q_value"] < 0.05
        assert out["candidates"][0]["status"] == "proposed"
        assert "independent" in out["guard"]

    def test_candidate_id_is_deterministic(self):
        first = explore_candidates("study-1", _cases())["candidates"]
        second = explore_candidates("study-1", _cases())["candidates"]
        assert [c["candidate_id"] for c in first] == [c["candidate_id"] for c in second]

    def test_confirmatory_role_is_forbidden(self):
        with pytest.raises(ValueError, match="screening"):
            explore_candidates("study-1", _cases(), role="confirmatory")

    def test_budget_caps_tests_and_candidates(self):
        cases = [
            {"exposure": f"G{i}", "outcome": "meropenem", "table": (20, 2, 2, 20)}
            for i in range(10)
        ]
        out = explore_candidates(
            "study-1", cases, ExploreBudget(max_tests=5, max_candidates=2, min_n=10)
        )
        assert out["n_tested"] == 5
        assert out["n_candidates"] == 2
        assert out["stopped_reason"] == "max_candidates"

    def test_small_n_is_excluded(self):
        out = explore_candidates(
            "study-1", _cases(), ExploreBudget(min_n=100, max_q=1.0)
        )
        assert out["candidates"] == []
