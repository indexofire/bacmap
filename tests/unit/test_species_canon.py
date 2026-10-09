"""TDD 测试：analysis/species_canon.py（P1-1，评审 A5 收敛）。

行为等价锁：canonical_from_verdict 复刻 nli_reflector 原路由语义，
collapse_binomial 复刻 deterministic_verifier 原二名形折叠语义。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.species_canon import (  # noqa: E402
    ECOLI,
    SALMONELLA,
    SHIGELLA,
    VPARA,
    canonical_from_verdict,
    collapse_binomial,
)


class TestCanonicalFromVerdict:
    def test_plain_verdicts(self):
        assert canonical_from_verdict("Salmonella") == SALMONELLA
        assert canonical_from_verdict("Salmonella enterica") == SALMONELLA
        assert canonical_from_verdict("V. parahaemolyticus") == VPARA
        assert canonical_from_verdict("DEC") == ECOLI
        assert canonical_from_verdict("Shigella") == SHIGELLA

    def test_not_prefix_routes_by_ipah(self):
        assert canonical_from_verdict("not_Salmonella", "positive") == SHIGELLA
        assert canonical_from_verdict("not_Salmonella", "negative") == ECOLI
        assert canonical_from_verdict("not_Salmonella") == ECOLI

    def test_empty_and_unknown(self):
        assert canonical_from_verdict("") == "unknown"
        assert canonical_from_verdict("ambiguous") == "unknown"


class TestCollapseBinomial:
    def test_binomial_collapses_to_salmonella(self):
        assert collapse_binomial("Salmonella enterica") == SALMONELLA
        assert collapse_binomial("Salmonella") == SALMONELLA

    def test_not_prefix_passthrough(self):
        assert collapse_binomial("not_Salmonella") == "not_Salmonella"

    def test_unmatched_passthrough(self):
        assert collapse_binomial("Escherichia coli") == "Escherichia coli"
        assert collapse_binomial("ambiguous") == "ambiguous"
