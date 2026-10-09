from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Hit:
    """Unified alignment result (BLAST tabular + minimap2 PAF)."""

    query_id: str = ""
    subject_id: str = ""
    identity: float = 0.0
    query_coverage: float = 0.0
    subject_coverage: float = 0.0
    evalue: float = 0.0
    bit_score: float = 0.0
    query_start: int = 0
    query_end: int = 0
    subject_start: int = 0
    subject_end: int = 0
    strand: str = "+"
    alignment_length: int = 0
    mismatches: int = 0
    mapq: int = 0
    backend: str = ""

    @classmethod
    def from_blast_line(cls, line: str) -> Hit:
        """Parse BLAST outfmt '6 qseqid sseqid pident length mismatch gapopen
        qstart qend sstart send evalue bitscore qlen slen'."""
        f = line.strip().split("\t")
        if len(f) < 14:
            raise ValueError(f"BLAST line has {len(f)} fields, need >=14 for coverage: {line[:80]}")

        qlen = int(f[12]) if len(f) > 12 else 0
        slen = int(f[13]) if len(f) > 13 else 0
        aln_len = int(f[3])
        qcov = (aln_len / qlen * 100.0) if qlen > 0 else 0.0
        scov = (aln_len / slen * 100.0) if slen > 0 else 0.0

        return cls(
            query_id=f[0],
            subject_id=f[1],
            identity=float(f[2]),
            alignment_length=aln_len,
            mismatches=int(f[4]),
            query_start=int(f[6]),
            query_end=int(f[7]),
            subject_start=int(f[8]),
            subject_end=int(f[9]),
            evalue=float(f[10]),
            bit_score=float(f[11]),
            query_coverage=qcov,
            subject_coverage=scov,
            strand="+" if int(f[8]) <= int(f[9]) else "-",
            backend="blast",
        )

    @classmethod
    def from_paf_line(cls, line: str) -> Hit:
        """Parse minimap2 PAF line (>=12 columns + optional tags)."""
        line = line.strip()
        if not line or line.startswith("#"):
            raise ValueError("Empty/comment PAF line")
        f = line.split("\t")
        if len(f) < 12:
            raise ValueError(f"Invalid PAF line: {line}")

        qlen = int(f[1])
        qstart = int(f[2])
        qend = int(f[3])
        strand = f[4]
        tname = f[5]
        tlen = int(f[6])
        tstart = int(f[7])
        tend = int(f[8])
        nmatch = int(f[9])
        aln_len = int(f[10])
        mapq = int(f[11])

        identity = (nmatch / aln_len * 100.0) if aln_len > 0 else 0.0
        qcov = ((qend - qstart) / qlen * 100.0) if qlen > 0 else 0.0
        scov = ((tend - tstart) / tlen * 100.0) if tlen > 0 else 0.0

        mismatches = 0
        for tag in f[12:]:
            parts = tag.split(":", 2)
            if len(parts) == 3 and parts[0] == "NM" and parts[1] == "i":
                try:
                    mismatches = int(parts[2])
                except ValueError:
                    pass

        return cls(
            query_id=f[0],
            subject_id=tname,
            identity=identity,
            alignment_length=aln_len,
            mismatches=mismatches,
            query_start=qstart,
            query_end=qend,
            subject_start=tstart,
            subject_end=tend,
            strand=strand,
            mapq=mapq,
            query_coverage=qcov,
            subject_coverage=scov,
            backend="minimap2",
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)
