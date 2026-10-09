"""Genome annotator — Python port of Prokka's annotation pipeline.

Replaces Prokka (Perl) with:
  - pyrodigal for CDS prediction (same algorithm as Prodigal CLI)
  - blastp against Prokka protein DBs (sprot → IS → AMR, first match wins)
  - JSON output optimized for AI/Hermes consumption

Usage:
    from bacmap.core.analysis.genome_annotator import annotate
    result = annotate("results/SAM-TYP-001/assembly/contigs.fasta")
    result.save("results/SAM-TYP-001/annotation/annotation.json")
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyrodigal

from bacmap.config import REF_DIR as _REF_DIR

_MIN_CONTIG_LEN = 200
_SINGLE_MODE_THRESHOLD = 100_000
_BLASTP_TIMEOUT = 300

_PROKKA_DBS: list[tuple[str, float, float]] = [
    ("prokka_sprot", 1e-6, 80.0),
    ("prokka_is", 1e-30, 90.0),
    ("prokka_amr", 1e-300, 90.0),
]


@dataclass
class Feature:
    locus_tag: str
    ftype: str
    contig: str
    start: int
    end: int
    strand: int
    length_bp: int
    gene: str = ""
    product: str = ""
    ec_number: str = ""
    cog: str = ""
    source: str = ""
    identity: float = 0.0
    coverage: float = 0.0
    protein_seq: str = ""
    na_seq: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class AnnotationResult:
    sample_id: str
    contigs: list[dict[str, Any]] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        cds = [f for f in self.features if f.ftype == "CDS"]
        annotated = [
            f for f in cds if f.gene or (f.product and "hypothetical" not in f.product.lower())
        ]
        hypothetical = [f for f in cds if f not in annotated]
        return {
            "total_contigs": len(self.contigs),
            "total_length_bp": sum(c["length"] for c in self.contigs),
            "total_CDS": len(cds),
            "annotated_CDS": len(annotated),
            "hypothetical_CDS": len(hypothetical),
            "annotation_rate": round(len(annotated) / len(cds), 3) if cds else 0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "contigs": self.contigs,
            "features": [f.to_dict() for f in self.features],
            "summary": self.summary,
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))


def _read_contigs(path: Path) -> list[tuple[str, str]]:
    contigs: list[tuple[str, str]] = []
    name = None
    chunks: list[str] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    contigs.append((name, "".join(chunks)))
                name = line[1:].split()[0]
                chunks = []
            else:
                chunks.append(line.upper())
    if name is not None:
        contigs.append((name, "".join(chunks)))
    return contigs


def _predict_cds(contigs: list[tuple[str, str]]) -> list[tuple[str, int, int, int, str, str]]:
    total_bp = sum(len(seq) for _, seq in contigs)
    use_single = total_bp >= _SINGLE_MODE_THRESHOLD

    if use_single:
        orf_finder = pyrodigal.GeneFinder(closed=True, mask=True)
        training_seq = b"".join(seq.encode() for _, seq in contigs[:10])
        orf_finder.train(training_seq)
    else:
        orf_finder = pyrodigal.GeneFinder(meta=True, closed=True, mask=True)

    predictions: list[tuple[str, int, int, int, str, str]] = []
    for contig_name, seq in contigs:
        if len(seq) < _MIN_CONTIG_LEN:
            continue
        genes = orf_finder.find_genes(seq.encode())
        for gene in genes:
            na_seq = gene.sequence()
            prot_seq = gene.translate(translation_table=11).rstrip("*")
            predictions.append(
                (
                    contig_name,
                    gene.begin,
                    gene.end,
                    gene.strand,
                    na_seq,
                    prot_seq,
                )
            )

    return predictions


def _run_blastp(
    proteins_faa: Path,
    db_prefix: str,
    evalue: float,
    min_coverage: float,
) -> dict[str, dict[str, Any]]:
    from bacmap.core.engine import SequenceMatcher

    db_path = str(_REF_DIR / db_prefix)

    raw_hits = SequenceMatcher.match(
        query=str(proteins_faa),
        db_prefix=db_path,
        mode="blastp",
        query_type="prot",
        min_identity=0.0,
        min_coverage=0.0,
        evalue=evalue,
        max_targets=1,
        qcov_hsp_perc=min_coverage,
        seg="no",
    )

    seen: set[str] = set()
    hits: dict[str, dict[str, Any]] = {}
    for hit in raw_hits:
        if hit.query_id in seen:
            continue
        seen.add(hit.query_id)

        gene, product = _parse_prokka_header(hit.subject_id)
        hits[hit.query_id] = {
            "gene": gene,
            "product": product,
            "identity": hit.identity,
            "coverage": hit.subject_coverage,
            "evalue": hit.evalue,
        }

    return hits


def _parse_prokka_header(sseqid: str) -> tuple[str, str]:
    parts = sseqid.split("~~~")
    if len(parts) >= 4:
        return parts[1].strip(), parts[3].strip()
    if len(parts) == 3:
        return parts[1].strip(), parts[2].strip()
    if len(parts) == 2:
        return parts[1].strip(), ""
    return sseqid.strip(), "hypothetical protein"


def _make_locus_tag(sample_id: str, index: int) -> str:
    import hashlib

    base = sample_id.upper().replace("-", "").replace("_", "") or "SAMPLE"
    suffix = hashlib.md5(sample_id.encode()).hexdigest()[:4].upper()
    return f"{base[:8]}_{suffix}_{index:05d}"


def annotate(contigs_path: str | Path, sample_id: str = "") -> AnnotationResult:
    contigs_file = Path(contigs_path)
    if not contigs_file.exists():
        raise FileNotFoundError(f"Contigs not found: {contigs_path}")

    if not sample_id:
        sample_id = contigs_file.parent.parent.name

    result = AnnotationResult(sample_id=sample_id)

    contigs = _read_contigs(contigs_file)
    for name, seq in contigs:
        gc = (seq.count("G") + seq.count("C")) / len(seq) if seq else 0
        result.contigs.append(
            {
                "id": name,
                "length": len(seq),
                "gc_content": round(gc, 4),
            }
        )

    predictions = _predict_cds(contigs)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".faa", delete=False) as tmp:
        proteins_faa = Path(tmp.name)
        for i, (contig_name, begin, end, strand, na_seq, prot_seq) in enumerate(predictions, 1):
            locus_tag = _make_locus_tag(sample_id, i)
            tmp.write(f">{locus_tag}\n{prot_seq}\n")

    try:
        annotations: dict[str, dict[str, Any]] = {}
        sources: dict[str, str] = {}

        for db_name, evalue, min_cov in _PROKKA_DBS:
            db_prefix = str(_REF_DIR / db_name)
            if not Path(f"{db_prefix}.phr").exists():
                continue
            hits = _run_blastp(proteins_faa, db_name, evalue, min_cov)
            for query_id, hit_data in hits.items():
                if query_id not in annotations:
                    annotations[query_id] = hit_data
                    sources[query_id] = db_name.replace("prokka_", "")
    finally:
        proteins_faa.unlink(missing_ok=True)

    for i, (contig_name, begin, end, strand, na_seq, prot_seq) in enumerate(predictions, 1):
        locus_tag = _make_locus_tag(sample_id, i)
        feat = Feature(
            locus_tag=locus_tag,
            ftype="CDS",
            contig=contig_name,
            start=begin,
            end=end,
            strand=strand,
            length_bp=abs(end - begin) + 1,
            protein_seq=prot_seq,
            na_seq=na_seq,
        )

        if locus_tag in annotations:
            ann = annotations[locus_tag]
            feat.gene = ann["gene"]
            feat.product = ann["product"]
            feat.identity = ann["identity"]
            feat.coverage = ann["coverage"]
            feat.source = sources.get(locus_tag, "")
        else:
            feat.product = "hypothetical protein"

        result.features.append(feat)

    return result
