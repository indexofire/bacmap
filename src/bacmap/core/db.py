from __future__ import annotations

from pathlib import Path

from bacmap.config import REF_DIR as REF

SPECIES_MARKERS = REF / "species" / "markers.fasta"

AMR_CARD = REF / "amr" / "card.fasta"
AMR_VFDB = REF / "amr" / "vfdb.fasta"

PLASMIDFINDER = REF / "plasmid" / "plasmidfinder.fasta"

SEROTYPE_ECOH = REF / "serotype" / "ecoh.fasta"
SEROTYPE_SHIGELLA = REF / "serotype" / "shigella.fasta"

VIRULENCE_TDH = REF / "virulence" / "tdh.fasta"
VIRULENCE_TRH = REF / "virulence" / "trh.fasta"
VIRULENCE_VPARA_TARGETS = REF / "virulence" / "vpara_targets.fasta"

GENOME_SALMONELLA_LT2 = REF / "genomes" / "salmonella_LT2.fasta"
GENOME_ECOLI_K12 = REF / "genomes" / "ecoli_k12.fasta"
GENOME_VPARA_RIMD = REF / "genomes" / "vpara_rimd.fasta"

ANNOTATION_PROKKA_SPROT = REF / "annotation" / "prokka_sprot.fasta"
ANNOTATION_PROKKA_IS = REF / "annotation" / "prokka_is.fasta"
ANNOTATION_PROKKA_AMR = REF / "annotation" / "prokka_amr.fasta"

VPA_SEROTYPE_DIR = REF / "vpa_serotype"

DB_NAME_TO_SOURCE: dict[str, Path] = {
    "species_markers": SPECIES_MARKERS,
    "card": AMR_CARD,
    "vfdb": AMR_VFDB,
    "plasmidfinder": PLASMIDFINDER,
    "ecoh": SEROTYPE_ECOH,
    "ecoh_sequences": SEROTYPE_ECOH,
    "shigella_ref": SEROTYPE_SHIGELLA,
    "shigella": SEROTYPE_SHIGELLA,
    "tdh": VIRULENCE_TDH,
    "trh": VIRULENCE_TRH,
    "vpara_targets": VIRULENCE_VPARA_TARGETS,
    "prokka_sprot": ANNOTATION_PROKKA_SPROT,
    "prokka_is": ANNOTATION_PROKKA_IS,
    "prokka_amr": ANNOTATION_PROKKA_AMR,
}

SNP_REFERENCES: dict[str, Path] = {
    "salmonella": GENOME_SALMONELLA_LT2,
    "ecoli": GENOME_ECOLI_K12,
    "vpara": GENOME_VPARA_RIMD,
}


def resolve_source(db_name: str) -> Path | None:
    return DB_NAME_TO_SOURCE.get(db_name)
