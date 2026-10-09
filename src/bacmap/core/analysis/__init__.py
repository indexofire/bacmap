"""Analysis algorithms: gene scanning, species ID, taxonomy, annotation, verification."""

from .failure_diagnostics import Diagnosis, diagnose, diagnose_from_log
from .gene_identity import normalize_amr
from .species_canon import (
    ECOLI,
    SALMONELLA,
    SHIGELLA,
    VPARA,
    canonical_from_verdict,
    collapse_binomial,
)

__all__ = [
    "AnnotationResult",
    "AtomicClaim",
    "CheckResult",
    "ClaimType",
    "ClaimVerdict",
    "DeterministicVerifier",
    "Diagnosis",
    "ECOLI",
    "Feature",
    "ReflectionResult",
    "SALMONELLA",
    "SHIGELLA",
    "SpeciesIdResult",
    "StrainFacts",
    "TaxonomyResult",
    "VerificationResult",
    "Verdict",
    "VPARA",
    "annotate",
    "canonical_from_verdict",
    "collapse_binomial",
    "diagnose",
    "diagnose_from_log",
    "extract_facts",
    "identify",
    "normalize_amr",
    "reflect",
    "scan",
    "validate_genome",
]

# verify 三件套已移至 bacmap.core.verify（冻结设计 §6）。
# 经 __getattr__ 惰性再导出，避免 verify -> analysis.gene_identity 的循环导入。
_VERIFY_LAZY: dict[str, tuple[str, str]] = {
    "CheckResult": ("bacmap.core.verify.deterministic_verifier", "CheckResult"),
    "DeterministicVerifier": ("bacmap.core.verify.deterministic_verifier", "DeterministicVerifier"),
    "VerificationResult": ("bacmap.core.verify.deterministic_verifier", "VerificationResult"),
    "extract_facts": ("bacmap.core.verify.nli_reflector", "extract_facts"),
    "reflect": ("bacmap.core.verify.nli_reflector", "reflect"),
    "AtomicClaim": ("bacmap.core.verify.nli_types", "AtomicClaim"),
    "ClaimType": ("bacmap.core.verify.nli_types", "ClaimType"),
    "ClaimVerdict": ("bacmap.core.verify.nli_types", "ClaimVerdict"),
    "ReflectionResult": ("bacmap.core.verify.nli_types", "ReflectionResult"),
    "StrainFacts": ("bacmap.core.verify.nli_types", "StrainFacts"),
    "Verdict": ("bacmap.core.verify.nli_types", "Verdict"),
}


def __getattr__(name: str):
    import importlib

    if name in _VERIFY_LAZY:
        module, attr = _VERIFY_LAZY[name]
        return getattr(importlib.import_module(module), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
