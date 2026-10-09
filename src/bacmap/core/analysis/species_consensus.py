"""Cross-method species identification consensus and arbitration.

Aggregates every ``species_identification`` ANALYSIS object attached to a
strain and derives one verdict with an agreement status. Layer priorities
follow the species-id plan (docs/plans/species-id/README.md):

    gtdbtk(3) > {skani_gtdb, panel, sourmash, mash_refseq, kraken2}(2) > marker(1)

A higher layer overrides lower layers (recorded, not fatal); disagreement
*within* one layer raises ``needs_review`` for human adjudication.
Shigella/EIEC vs E. coli label differences are biologically expected
(same species by ANI) and do not trigger review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bacmap.store.genome_object_service import GenomeObject, GenomeObjectService

_LAYER_BY_METHOD = {
    "gtdbtk": 3,
    "skani_gtdb": 2,
    "panel": 2,
    "sourmash": 2,
    "mash_refseq": 2,
    "kraken2": 2,
    "marker": 1,
}

_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

# Label aliases folded to one canonical label before comparison. The
# Shigella/EIEC and DEC labels are marker-era names for E. coli; ANI/GTDB
# methods report the species under its Linnaean name.
_LABEL_ALIASES = {
    "DEC": "E.coli",
    "Shigella/EIEC": "E.coli",
    "Shigella": "E.coli",
    "Escherichia coli": "E.coli",
    "V_parahaemolyticus": "V.parahaemolyticus",
    "Vibrio parahaemolyticus": "V.parahaemolyticus",
}


def _canonical(label: str) -> str:
    return _LABEL_ALIASES.get(label.strip(), label.strip())


@dataclass(frozen=True)
class MethodCall:
    method: str
    species: str
    confidence: str
    object_id: str
    layer: int = 0

    @property
    def canonical(self) -> str:
        return _canonical(self.species)


@dataclass(frozen=True)
class SpeciesConsensus:
    strain_id: str
    methods: list[MethodCall] = field(default_factory=list)
    resolved_species: str | None = None
    agreement: str = "empty"
    basis: str = ""
    needs_review: bool = False
    disagreeing_methods: list[str] = field(default_factory=list)


def _winner(calls: list[MethodCall]) -> MethodCall:
    return max(
        calls,
        key=lambda c: (c.layer, _CONFIDENCE_RANK.get(c.confidence, 0)),
    )


def compare(strain_id: str, service: GenomeObjectService) -> SpeciesConsensus:
    objects: list[GenomeObject] = service.list_species_identifications(strain_id)
    calls = [
        MethodCall(
            method=o.payload["method"],
            species=str(o.payload["result"]["species"]),
            confidence=str(o.payload["result"].get("confidence", "")),
            object_id=o.object_id,
            layer=_LAYER_BY_METHOD.get(o.payload["method"], 0),
        )
        for o in objects
    ]

    if not calls:
        return SpeciesConsensus(strain_id=strain_id)

    if len(calls) == 1:
        return SpeciesConsensus(
            strain_id=strain_id,
            methods=calls,
            resolved_species=calls[0].species,
            agreement="single",
            basis=calls[0].method,
        )

    winner = _winner(calls)
    raw_labels = {c.species for c in calls}
    canonical_labels = {c.canonical for c in calls}
    disagreeing = [c.method for c in calls if c.canonical != winner.canonical]

    if len(raw_labels) == 1:
        agreement = "match"
    elif len(canonical_labels) == 1:
        agreement = "expected_divergence"
    else:
        agreement = "conflict"

    needs_review = bool(disagreeing) and any(
        c.method in {d for d in disagreeing} and c.layer == winner.layer for c in calls
    )

    return SpeciesConsensus(
        strain_id=strain_id,
        methods=calls,
        resolved_species=winner.species,
        agreement=agreement,
        basis=winner.method,
        needs_review=needs_review,
        disagreeing_methods=disagreeing,
    )
