"""Gene scanner — Python implementation of abricate-like functionality.

Scans assembled contigs against a BLAST database and returns structured JSON
with gene hits, coverage, identity, and database-specific metadata.

Designed as a drop-in replacement for abricate (Perl) with AI-agent friendly
JSON output. Supports any BLAST nucleotide database with abricate-style
headers: >db_name~~~gene~~~accession~~~ product/description

Usage:
    # CLI
    python -m bacmap.core.analysis.gene_scanner contigs.fasta --db card
    python -m bacmap.core.analysis.gene_scanner contigs.fasta --db ecoh --json

    # Python API
    from bacmap.core.analysis.gene_scanner import scan
    result = scan("contigs.fasta", db_name="card")
    genes = result.genes

Database format (FASTA headers, abricate-compatible):
    >db~~~GENE~~~ACCESSION~~~ PRODUCT_OR_DESCRIPTION
    ATGGC...

Custom databases can be added to data/reference/ with:
    gene_scanner.setup_db("mydb", "data/reference/mydb.fasta")
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bacmap.config import REF_DIR as _REF_DIR
from bacmap.core.utils import parse_db_header

_DEFAULT_MIN_IDENTITY = 80.0
_DEFAULT_MIN_COVERAGE = 80.0
_EVALUE = 1e-10
_WORD_SIZE = 28


def normalize_synonyms(raw: dict[str, Any]) -> dict[str, list[str]]:
    """Normalize gene synonym mappings from two input formats.

    Format 1 (canonical → aliases): {"stx1": ["stx1a", "stxA1"]}
    Format 2 (alias → canonical): {"stx1a": "stx1", "stxA1": "stx1"}

    Returns unified Format 1 with lowercase keys.
    """
    if not raw:
        return {}

    result: dict[str, list[str]] = {}
    for key, value in raw.items():
        k = key.strip().lower()
        if isinstance(value, list):
            result[k] = [v.strip().lower() for v in value]
        elif isinstance(value, str):
            canonical = value.strip().lower()
            result.setdefault(canonical, []).append(k)
        else:
            result[k] = []

    return result


def resolve_gene_name(raw_name: str, synonyms: dict[str, list[str]] | None = None) -> str:
    """Resolve a gene name to its canonical form using synonym mapping."""
    if not synonyms:
        return raw_name

    name_lower = raw_name.lower()
    for canonical, aliases in synonyms.items():
        if name_lower == canonical or name_lower in aliases:
            return canonical

    return raw_name


@dataclass
class GeneHit:
    gene: str
    identity: float
    coverage: float
    contig: str
    start: int
    end: int
    strand: str
    accession: str = ""
    product: str = ""
    database: str = ""

    @property
    def hit_length(self) -> int:
        return abs(self.end - self.start) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "gene": self.gene,
            "identity": self.identity,
            "coverage": self.coverage,
            "contig": self.contig,
            "start": self.start,
            "end": self.end,
            "strand": self.strand,
            "accession": self.accession,
            "product": self.product[:200] if self.product else "",
            "hit_length": self.hit_length,
        }


@dataclass
class ScanResult:
    database: str
    input_file: str
    min_identity: float
    min_coverage: float
    genes: list[GeneHit] = field(default_factory=list)
    total_hits: int = 0
    unique_genes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "input_file": self.input_file,
            "thresholds": {
                "min_identity": self.min_identity,
                "min_coverage": self.min_coverage,
            },
            "total_hits": self.total_hits,
            "unique_gene_count": len(self.unique_genes),
            "unique_genes": self.unique_genes,
            "genes": [g.to_dict() for g in self.genes],
            "summary": self.summary,
        }

    def build_summary(self) -> dict[str, Any]:
        gene_set = sorted({g.gene for g in self.genes})
        self.unique_genes = gene_set
        self.summary = {
            "total_hits": len(self.genes),
            "unique_genes": len(gene_set),
        }
        return self.summary


_DB_SEARCH_PATHS = [
    _REF_DIR,
    Path(__file__).resolve().parents[3] / ".pixi/envs/default/db",
    Path.home() / ".pixi/envs/default/db",
]


def _find_db(db_name: str) -> Path:
    for base in _DB_SEARCH_PATHS:
        for pattern in [f"{db_name}_blastdb", db_name, f"{db_name}/sequences"]:
            p = base / pattern
            if (base / f"{pattern}.ndb").exists() or (base / f"{pattern}.nhr").exists():
                return p
            if (base / f"{pattern}.phr").exists():
                return p
    # B3 复发路径关闭：索引缺失时按源 FASTA 懒重建，而非直接抛错
    # （fresh clone 首跑 species_identify/ecoh/shigella 不再 FileNotFoundError）
    try:
        return setup_db(db_name)
    except (FileNotFoundError, RuntimeError, OSError):
        raise FileNotFoundError(
            f"Database '{db_name}' not found (no BLAST index and auto-rebuild failed). "
            f"Searched: {[str(p) for p in _DB_SEARCH_PATHS]}. "
            f"Run gene_scanner.setup_db('{db_name}') to create it."
        ) from None


def _parse_db_header(sseqid: str) -> tuple[str, str, str, str]:
    return parse_db_header(sseqid)


def scan(
    query: str | Path,
    db_name: str = "card",
    *,
    reads_r2: str | Path | None = None,
    min_identity: float = _DEFAULT_MIN_IDENTITY,
    min_coverage: float = _DEFAULT_MIN_COVERAGE,
    threads: int = 4,
) -> ScanResult:
    """Scan contigs or reads against a gene database.

    Assembly input (FASTA): uses BLAST or minimap2 backend.
    Reads input (FASTQ): uses KMA backend.
    """
    query = Path(query)
    if not query.exists():
        raise FileNotFoundError(f"Query not found: {query}")

    name_lower = query.name.lower()
    is_fastq = name_lower.endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz"))

    if is_fastq:
        return _scan_reads(query, reads_r2, db_name, min_identity, min_coverage, threads)
    return _scan_assembly(query, db_name, min_identity, min_coverage, threads)


def _scan_assembly(
    contigs: Path,
    db_name: str,
    min_identity: float,
    min_coverage: float,
    threads: int,
) -> ScanResult:
    db_path = _find_db(db_name)

    from bacmap.core.engine import SequenceMatcher

    hits = SequenceMatcher.match(
        query=str(contigs),
        db_prefix=str(db_path),
        mode="blastn",
        min_identity=0.0,
        min_coverage=0.0,
        evalue=_EVALUE,
        word_size=_WORD_SIZE,
        num_threads=threads,
    )

    result = ScanResult(
        database=db_name,
        input_file=str(contigs),
        min_identity=min_identity,
        min_coverage=min_coverage,
    )

    for hit in hits:
        gene, accession, product, _ = _parse_db_header(hit.subject_id)

        if hit.identity < min_identity or hit.subject_coverage < min_coverage:
            continue

        gene_hit = GeneHit(
            gene=gene,
            identity=round(hit.identity, 2),
            coverage=round(hit.subject_coverage, 1),
            contig=hit.query_id,
            start=min(hit.query_start, hit.query_end),
            end=max(hit.query_start, hit.query_end),
            strand=hit.strand,
            accession=accession,
            product=product,
            database=db_name,
        )
        result.genes.append(gene_hit)

    result.genes.sort(key=lambda h: (-h.identity, h.gene))
    result.total_hits = len(result.genes)
    result.build_summary()

    return result


def _scan_reads(
    reads_r1: Path,
    reads_r2: str | Path | None,
    db_name: str,
    min_identity: float,
    min_coverage: float,
    threads: int,
) -> ScanResult:
    kma_index = _find_kma_index(db_name)
    if not kma_index:
        raise FileNotFoundError(
            f"KMA index for '{db_name}' not found. "
            f"Run gene_scanner.setup_db('{db_name}', build_kma=True) to create it."
        )

    from bacmap.core.engine.backends.kma import KmaBackend

    backend = KmaBackend(threads=threads)
    hits = backend.find(
        reads_r1=reads_r1,
        reads_r2=Path(reads_r2) if reads_r2 else None,
        index_prefix=kma_index,
        min_coverage=min_coverage,
        min_identity=min_identity,
    )

    result = ScanResult(
        database=db_name,
        input_file=str(reads_r1),
        min_identity=min_identity,
        min_coverage=min_coverage,
    )
    gene_map: dict[str, int] = {}

    for hit in hits:
        gene, accession, product, _ = _parse_db_header(hit.subject_id)
        if not gene:
            continue

        # KMA maps raw reads — no contig coordinates available.
        gene_hit = GeneHit(
            gene=gene,
            identity=round(hit.identity, 2),
            coverage=round(hit.subject_coverage, 1),
            contig=hit.query_id,
            start=0,
            end=0,
            strand="+",
            accession=accession,
            product=product[:200] if product else "",
            database=db_name,
        )

        if gene in gene_map:
            idx = gene_map[gene]
            if gene_hit.identity > result.genes[idx].identity:
                result.genes[idx] = gene_hit
        else:
            gene_map[gene] = len(result.genes)
            result.genes.append(gene_hit)

    result.genes.sort(key=lambda h: (-h.identity, h.gene))
    result.total_hits = len(result.genes)
    result.build_summary()
    return result


def _find_kma_index(db_name: str) -> Path | None:
    for base in _DB_SEARCH_PATHS:
        candidate = base / f"{db_name}_kma"
        if (candidate / "name").exists():
            return candidate
    return None


def scan_multi(
    contigs_fasta: str | Path,
    db_names: list[str],
    *,
    min_identity: float = _DEFAULT_MIN_IDENTITY,
    min_coverage: float = _DEFAULT_MIN_COVERAGE,
    threads: int = 4,
) -> dict[str, ScanResult]:
    """Scan contigs against multiple databases.

    Args:
        contigs_fasta: Path to assembled contigs.
        db_names: List of database names.
        min_identity, min_coverage, threads: See scan().

    Returns:
        Dict mapping db_name → ScanResult.
    """
    results = {}
    for db in db_names:
        results[db] = scan(
            contigs_fasta,
            db_name=db,
            min_identity=min_identity,
            min_coverage=min_coverage,
            threads=threads,
        )
    return results


def setup_db(
    db_name: str, fasta_source: Path | str | None = None, output_dir: Path | None = None
) -> Path:
    """Build a BLAST database from a FASTA file.

    Args:
        db_name: Name for the database.
        fasta_source: Source FASTA file. If None, tries to find from abricate.
        output_dir: Output directory. Defaults to data/reference/.

    Returns:
        Path to the BLAST DB prefix.
    """
    if output_dir is None:
        output_dir = _REF_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    if fasta_source is None:
        from bacmap.core.db import DB_NAME_TO_SOURCE

        src = DB_NAME_TO_SOURCE.get(db_name)
        if src and src.exists():
            fasta_source = src
        else:
            for base in _DB_SEARCH_PATHS:
                candidate = base / db_name / "sequences"
                if candidate.exists():
                    fasta_source = candidate
                    break
        if fasta_source is None:
            raise FileNotFoundError(f"Source FASTA for '{db_name}' not found")

    fasta_source = Path(fasta_source)
    db_prefix = output_dir / f"{db_name}_blastdb"
    local_fasta = output_dir / f"{db_name}_sequences.fasta"

    import shutil

    shutil.copy2(fasta_source, local_fasta)

    from bacmap.core.engine.backends.blast import BlastBackend

    backend = BlastBackend(tool="blastn")
    backend.make_db(local_fasta, db_prefix, db_type="nucl")

    print(f"✓ BLAST DB '{db_name}' created at {db_prefix}")
    return db_prefix


def setup_kma_index(
    db_name: str, fasta_source: Path | str | None = None, output_dir: Path | None = None
) -> Path:
    if output_dir is None:
        output_dir = _REF_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if fasta_source is None:
        from bacmap.core.db import DB_NAME_TO_SOURCE

        src = DB_NAME_TO_SOURCE.get(db_name)
        if src and src.exists():
            fasta_source = src
        else:
            raise FileNotFoundError(f"Source FASTA for '{db_name}' not found")

    kma_index_dir = output_dir / f"{db_name}_kma"

    try:
        from bacmap.core.engine.backends.kma import KmaBackend

        backend = KmaBackend()
        backend.make_index(Path(fasta_source), kma_index_dir)
        print(f"✓ KMA index '{db_name}' created at {kma_index_dir}")
    except RuntimeError as e:
        print(f"  ⚠ KMA not available, skipping: {e}")

    return kma_index_dir


def setup_all_databases(output_dir: Path | None = None) -> list[str]:
    """Build BLAST databases for all abricate databases found.

    Returns:
        List of created database names.
    """
    abricate_db_dir = Path.home() / ".pixi/envs/default/db"
    if not abricate_db_dir.exists():
        raise FileNotFoundError("abricate db directory not found")

    created = []
    for db_dir in sorted(abricate_db_dir.iterdir()):
        if not db_dir.is_dir():
            continue
        seq_file = db_dir / "sequences"
        if not seq_file.exists():
            continue
        try:
            setup_db(db_dir.name, seq_file, output_dir)
            created.append(db_dir.name)
        except Exception as e:
            print(f"  ✗ {db_dir.name}: {e}")

    return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gene scanner — abricate-like gene detection with JSON output"
    )
    parser.add_argument("contigs", help="Assembled contigs FASTA")
    parser.add_argument(
        "--db", default="card", help="Database name (card/vfdb/ecoh/plasmidfinder/...)"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON (default: TSV)")
    parser.add_argument("--multi", help="Comma-separated db names for multi-db scan")
    parser.add_argument("--min-id", type=float, default=_DEFAULT_MIN_IDENTITY)
    parser.add_argument("--min-cov", type=float, default=_DEFAULT_MIN_COVERAGE)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--setup", help="Setup a DB from FASTA: --setup name[,fasta_path]")
    parser.add_argument("--setup-all", action="store_true", help="Setup all abricate databases")
    args = parser.parse_args()

    if args.setup:
        parts = args.setup.split(",")
        db_name = parts[0]
        fasta = parts[1] if len(parts) > 1 else None
        setup_db(db_name, fasta)
        return

    if args.setup_all:
        created = setup_all_databases()
        print(f"Created {len(created)} databases: {', '.join(created)}")
        return

    if args.multi:
        db_names = [d.strip() for d in args.multi.split(",")]
        results = scan_multi(
            args.contigs,
            db_names,
            min_identity=args.min_id,
            min_coverage=args.min_cov,
            threads=args.threads,
        )
        if args.json:
            output = {name: r.to_dict() for name, r in results.items()}
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            for name, r in results.items():
                print(f"=== {name}: {r.total_hits} hits, {len(r.unique_genes)} unique genes ===")
                for g in r.genes[:5]:
                    print(f"  {g.gene}\t{g.identity}%\t{g.coverage}%")
        return

    result = scan(
        args.contigs,
        db_name=args.db,
        min_identity=args.min_id,
        min_coverage=args.min_cov,
        threads=args.threads,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"# Database: {result.database}")
        print(f"# Total hits: {result.total_hits}, Unique genes: {len(result.unique_genes)}")
        print("GENE\t%IDENTITY\t%COVERAGE\tCONTIG\tSTART\tEND\tACCESSION")
        for g in result.genes:
            print(
                f"{g.gene}\t{g.identity}\t{g.coverage}\t{g.contig}"
                f"\t{g.start}\t{g.end}\t{g.accession}"
            )


if __name__ == "__main__":
    main()
