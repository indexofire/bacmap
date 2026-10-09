"""Deterministic Verifier — project.md §8.2 Layer 2。

非 LLM 的确定性规则校验器。检查分析结果是否符合已知规则。
每个结论必须通过此校验才能进入报告。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bacmap.core.utils import parse_mlst

from ..analysis.species_canon import collapse_binomial
from ..analysis.species_consensus import SpeciesConsensus

_KNOWN_SEROGROUPS = frozenset(
    {
        "A",
        "B",
        "C1",
        "C2-C3",
        "D1",
        "D2",
        "E1",
        "E4",
        "F",
        "G",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
        "N",
        "O",
        "P",
        "R",
        "S",
        "T",
        "U",
        "V",
        "W",
        "X",
        "Z",
        "51",
        "53",
        "54",
        "55",
        "56",
        "57",
        "58",
        "59",
        "60",
        "61",
        "65",
        "66",
    }
)

_MLST_LOCI = ("aroC", "dnaN", "hemD", "hisD", "purE", "sucA", "thrA")

_CRITICAL_AMR_PATTERNS = [
    re.compile(r"^mcr-\d", re.IGNORECASE),
    re.compile(r"^bla(NDM|KPC|OXA-48|VIM|IMP)", re.IGNORECASE),
    re.compile(r"^blaCTX-M", re.IGNORECASE),
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: list[CheckResult]
    failed_count: int
    needs_human_review: bool


class DeterministicVerifier:
    """project.md §8.2 Layer 2 确定性规则校验。"""

    def verify_species(self, verdict: str) -> CheckResult:
        if verdict == "Salmonella":
            return CheckResult("species", True, f"Species confirmed: {verdict}")
        return CheckResult("species", False, f"Species NOT confirmed: {verdict!r}")

    def verify_species_consensus(self, consensus: SpeciesConsensus) -> CheckResult:
        passed = consensus.agreement != "conflict" or not consensus.needs_review
        return CheckResult(
            "species_consensus",
            passed,
            f"agreement={consensus.agreement}, resolved={consensus.resolved_species!r}, "
            f"basis={consensus.basis}",
            {
                "agreement": consensus.agreement,
                "resolved_species": consensus.resolved_species,
                "basis": consensus.basis,
                "needs_human_review": consensus.needs_review,
                "methods": [m.method for m in consensus.methods],
                "disagreeing_methods": consensus.disagreeing_methods,
            },
        )

    def verify_mlst(self, st: str, alleles: dict[str, str]) -> CheckResult:
        if not st or st in ("-", "N/A", ""):
            return CheckResult("mlst", False, f"MLST ST missing: {st!r}")

        if not st.lstrip("-").isdigit():
            return CheckResult("mlst", False, f"MLST ST not numeric: {st!r}")

        missing = []
        for locus in _MLST_LOCI:
            val = alleles.get(locus, "-")
            if val in ("-", "", "N/A"):
                missing.append(locus)

        if missing:
            return CheckResult(
                "mlst",
                False,
                f"MLST alleles missing for: {', '.join(missing)}",
                {"missing_loci": missing},
            )

        return CheckResult(
            "mlst",
            True,
            f"MLST ST={st}, all 7 loci present",
            {"st": st, "alleles": alleles},
        )

    def verify_serotype(self, serovar: str, serogroup: str) -> CheckResult:
        if not serovar or serovar in ("N/A", ""):
            return CheckResult("serotype", False, "Serovar missing")

        details: dict[str, Any] = {"serovar": serovar}
        if serogroup and serogroup != "-":
            details["serogroup"] = serogroup
            if serogroup not in _KNOWN_SEROGROUPS:
                return CheckResult(
                    "serotype",
                    False,
                    f"Unknown serogroup: {serogroup!r}",
                    details,
                )

        return CheckResult("serotype", True, f"Serovar: {serovar}, serogroup: {serogroup}", details)

    def verify_amr_genes(self, genes: list[str]) -> CheckResult:
        warnings = []
        critical = []

        for gene in genes:
            if not gene or not gene.strip():
                return CheckResult("amr", False, "Empty AMR gene name found")

            for pattern in _CRITICAL_AMR_PATTERNS:
                if pattern.search(gene):
                    critical.append(gene)
                    break

            if len(gene) < 3 or "XXX" in gene.upper() or "FAKE" in gene.upper():
                warnings.append(gene)

        details: dict[str, Any] = {"gene_count": len(genes)}
        if warnings:
            details["warnings"] = warnings
        if critical:
            details["critical_resistance"] = True
            details["critical_genes"] = critical

        msg = f"{len(genes)} AMR genes verified"
        if critical:
            msg += f" (CRITICAL: {', '.join(critical)})"

        return CheckResult("amr", True, msg, details)

    def verify_all(self, summary: dict[str, Any]) -> VerificationResult:
        steps = summary.get("steps", {})

        sp_raw = steps.get("species", {})
        # 真实 summary（species.smk 统一输出）用 "species" 键存判决；
        # 旧 fixtures 用 "verdict"。两者都读（与 nli_reflector.extract_facts 一致）。
        if isinstance(sp_raw, dict):
            verdict = str(sp_raw.get("verdict") or sp_raw.get("species") or "")
        else:
            verdict = str(sp_raw)
        species_check = self.verify_species(collapse_binomial(verdict))

        mlst_raw = steps.get("mlst", "")
        st, alleles = self._parse_mlst(mlst_raw)
        mlst_check = self.verify_mlst(st, alleles)

        sero_raw = steps.get("serotype", {})
        serovar = sero_raw.get("sistr", "N/A") if isinstance(sero_raw, dict) else "N/A"
        serogroup = sero_raw.get("serogroup", "") if isinstance(sero_raw, dict) else ""
        sero_check = self.verify_serotype(serovar, serogroup)

        amr_raw = steps.get("amr", {})
        card_genes = []
        if isinstance(amr_raw, dict):
            card = amr_raw.get("abricate_card", [])
            if isinstance(card, list):
                card_genes = [r.get("GENE", "") for r in card if isinstance(r, dict)]
        amr_check = self.verify_amr_genes(card_genes)

        checks = [species_check, mlst_check, sero_check, amr_check]
        failed = [c for c in checks if not c.passed]

        needs_review = bool(amr_check.details.get("critical_resistance"))

        return VerificationResult(
            passed=len(failed) == 0,
            checks=checks,
            failed_count=len(failed),
            needs_human_review=needs_review,
        )

    @staticmethod
    def _parse_mlst(mlst_text: str) -> tuple[str, dict[str, str]]:
        parsed = parse_mlst(mlst_text)
        raw_alleles = parsed.get("alleles", {})

        st = parsed.get("st", "")
        if st == "N/A":
            st = ""

        alleles: dict[str, str] = {}
        for locus in _MLST_LOCI:
            if locus.lower() in raw_alleles:
                alleles[locus] = raw_alleles[locus.lower()]

        return st, alleles
