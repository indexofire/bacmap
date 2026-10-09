"""Python-only sequence tool handlers.

Covers bio_seq_stats, bio_seq_ops, bio_fastq_qc, bio_seq_convert. These use
Biopython and degrade gracefully if Biopython is not installed (lazy install).
All handlers return JSON strings. Errors are {"error": "..."}.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from ._common import (
    _detect_format,
    _ensure_biopython,
    _resolve_path,
    logger,
    tool_handler,
)


@tool_handler
def seq_stats(args: dict[str, Any], **kwargs: Any) -> str:
    path = _resolve_path(args.get("file", ""))
    if not os.path.isfile(path):
        return json.dumps({"error": f"File not found: {path}"})
    fmt = args.get("format", "auto")
    fmt = _detect_format(path, fmt)
    bins = args.get("histogram_bins", 20)

    if not _ensure_biopython():
        return json.dumps({"error": "Biopython is required. Run: pip install biopython"})

    try:
        from Bio import SeqIO

        records = list(SeqIO.parse(path, fmt))  # type: ignore[no-untyped-call]
    except Exception as e:
        logger.exception("seq_stats failed to parse %s file", fmt)
        return json.dumps({"error": f"Failed to parse {fmt} file: {e}"})

    if not records:
        return json.dumps({"error": f"No records found in {fmt} file"})

    lengths = [len(r) for r in records]
    gc_total = 0
    total_bases = sum(lengths)
    for r in records:
        s = str(r.seq).upper()
        gc_total += s.count("G") + s.count("C")

    n50 = _calc_n50(lengths)

    result = {
        "file": path,
        "format": fmt,
        "record_count": len(records),
        "total_bases": total_bases,
        "length": {
            "min": min(lengths),
            "max": max(lengths),
            "mean": round(total_bases / len(lengths), 2),
            "median": _median(lengths),
            "n50": n50,
        },
        "gc_content": round(gc_total / total_bases * 100, 3) if total_bases else 0,
        "length_histogram": _histogram(lengths, bins),
    }

    # FASTQ-specific: quality
    if fmt == "fastq":
        try:
            phred_scores = []
            quals_per_pos: list[list[float]] = []
            for r in records[:5000]:  # sample for speed
                if r.letter_annotations.get("phred_quality"):
                    q = r.letter_annotations["phred_quality"]
                    phred_scores.extend(q)
                    for i, v in enumerate(q):
                        while len(quals_per_pos) <= i:
                            quals_per_pos.append([])
                        quals_per_pos[i].append(v)
            if phred_scores:
                result["quality"] = {
                    "mean_q": round(sum(phred_scores) / len(phred_scores), 2),
                    "q20_fraction": round(
                        sum(1 for q in phred_scores if q >= 20) / len(phred_scores), 4
                    ),
                    "q30_fraction": round(
                        sum(1 for q in phred_scores if q >= 30) / len(phred_scores), 4
                    ),
                    "per_position_mean_q": [round(sum(p) / len(p), 2) for p in quals_per_pos[:200]],
                }
        except Exception as e:
            result["quality_error"] = str(e)

    # Top 10 longest records
    by_len = sorted([(r.id, len(r)) for r in records], key=lambda x: -x[1])[:10]
    result["top_records_by_length"] = [{"id": rid, "length": rl} for rid, rl in by_len]

    return json.dumps(result, indent=2)


def _calc_n50(lengths: list[int]) -> int:
    sorted_lens = sorted(lengths, reverse=True)
    cumsum = 0
    half = sum(sorted_lens) / 2
    for length in sorted_lens:
        cumsum += length
        if cumsum >= half:
            return length
    return 0


def _median(values: Sequence[int | float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    if n % 2 == 0:
        return round((s[n // 2 - 1] + s[n // 2]) / 2, 2)
    return s[n // 2]


def _histogram(values: list[int], bins: int = 20) -> list[dict[str, Any]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"bin": f"{lo}", "count": len(values)}]
    width = (hi - lo) / bins
    buckets = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        buckets[idx] += 1
    return [
        {"bin": f"{round(lo + i * width)}-{round(lo + (i + 1) * width)}", "count": b}
        for i, b in enumerate(buckets)
    ]


# ---------------------------------------------------------------------------
# bio_seq_ops
# ---------------------------------------------------------------------------

_COMPLEMENT = str.maketrans("ACGTUNacgtun", "TGCAANtgcaan")
_IUPAC = {
    "A": "A",
    "C": "C",
    "G": "G",
    "T": "T",
    "U": "U",
    "R": "[AG]",
    "Y": "[CT]",
    "S": "[GC]",
    "W": "[AT]",
    "K": "[GT]",
    "M": "[AC]",
    "B": "[CGT]",
    "D": "[AGT]",
    "H": "[ACT]",
    "V": "[ACG]",
    "N": "[ACGTN]",
}


def _get_sequence(args: dict[str, Any]) -> tuple[str, str]:
    """Get sequence from args, return (sequence, error_or_empty)."""
    seq = args.get("sequence")
    if seq:
        return seq.upper(), ""
    filepath = args.get("file")
    if not filepath:
        return "", "Provide 'sequence' or 'file'."
    path = _resolve_path(filepath)
    if not os.path.isfile(path):
        return "", f"File not found: {path}"
    if not _ensure_biopython():
        return "", "Biopython required for file input."
    from Bio import SeqIO

    rid = args.get("record_id")
    for rec in SeqIO.parse(path, _detect_format(path)):  # type: ignore[no-untyped-call]
        if rid is None or rec.id == rid:
            return str(rec.seq).upper(), ""
    return "", f"Record '{rid}' not found in {path}."


@tool_handler
def seq_ops(args: dict[str, Any], **kwargs: Any) -> str:
    op = args.get("operation", "")
    if not op:
        return json.dumps({"error": "Specify 'operation'."})

    if op == "reverse_complement":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        rc = seq.translate(_COMPLEMENT)[::-1]
        return json.dumps({"input_length": len(seq), "reverse_complement": rc})

    if op == "translate":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        if not _ensure_biopython():
            return json.dumps({"error": "Biopython required for translation."})
        from Bio.Seq import Seq

        frame = args.get("frame", 0)
        protein = str(Seq(seq[frame:]).translate())  # type: ignore[no-untyped-call]
        return json.dumps(
            {
                "input_length": len(seq),
                "frame": frame,
                "protein": protein,
                "protein_length": len(protein),
            }
        )

    if op == "gc_content":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        gc = seq.count("G") + seq.count("C")
        return json.dumps(
            {
                "length": len(seq),
                "gc_count": gc,
                "gc_content": round(gc / len(seq) * 100, 3) if seq else 0,
            }
        )

    if op == "gc_skew":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        window = args.get("window", 1000)
        skew_vals = []
        for i in range(0, len(seq), window):
            chunk = seq[i : i + window]
            g = chunk.count("G")
            c = chunk.count("C")
            skew = (g - c) / (g + c) if (g + c) else 0
            skew_vals.append({"pos": i, "skew": round(skew, 4)})
        return json.dumps({"window_size": window, "skew_profile": skew_vals})

    if op == "motif_search":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        motif = args.get("motif", "").upper()
        if not motif:
            return json.dumps({"error": "Provide 'motif' (IUPAC pattern)."})
        regex = "".join(_IUPAC.get(c, c) for c in motif)
        matches = [(m.start(), m.end()) for m in re.finditer(regex, seq)]
        return json.dumps(
            {
                "motif": motif,
                "match_count": len(matches),
                "positions": matches[:200],
            }
        )

    if op == "find_orfs":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        min_len = args.get("min_orf_len", 30)
        orfs = _find_orfs(seq, min_len)
        return json.dumps(
            {
                "min_orf_length": min_len,
                "orf_count": len(orfs),
                "orfs": orfs[:100],
            }
        )

    if op == "restriction_sites":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        # Common restriction enzymes
        enzymes = {
            "EcoRI": "GAATTC",
            "BamHI": "GGATCC",
            "HindIII": "AAGCTT",
            "XhoI": "CTCGAG",
            "NotI": "GCGGCCGC",
            "NheI": "GCTAGC",
            "SacI": "GAGCTC",
            "KpnI": "GGTACC",
            "PstI": "CTGCAG",
            "SmaI": "CCCGGG",
            "SalI": "GTCGAC",
        }
        sites = {}
        for name, site in enzymes.items():
            pos = [m.start() for m in re.finditer(site, seq)]
            if pos:
                sites[name] = {"sequence": site, "positions": pos[:50], "count": len(pos)}
        return json.dumps({"restriction_sites": sites})

    if op == "kmer_count":
        seq, err = _get_sequence(args)
        if err:
            return json.dumps({"error": err})
        k = args.get("k", 3)
        top = args.get("top", 20)
        kmers = Counter(seq[i : i + k] for i in range(len(seq) - k + 1))
        top_kmers = [
            {"kmer": km, "count": cnt, "frequency": round(cnt / len(seq), 5)}
            for km, cnt in kmers.most_common(top)
        ]
        out_file = args.get("output_file")
        if out_file:
            with open(out_file, "w") as f:
                for km, cnt in kmers.most_common():
                    f.write(f"{km}\t{cnt}\n")
        return json.dumps({"k": k, "unique_kmers": len(kmers), "top": top_kmers})

    return json.dumps({"error": f"Unknown operation: {op}"})


def _find_orfs(seq: str, min_codons: int = 30) -> list[dict[str, Any]]:
    """Find ORFs in all 6 frames."""
    comp = seq.translate(_COMPLEMENT)[::-1]
    targets = [(seq, "+", f) for f in range(3)] + [(comp, "-", f) for f in range(3)]
    orfs: list[dict[str, Any]] = []
    codon_re = re.compile(r"(ATG(?:\w{3})*?(?:TAA|TAG|TGA))")
    for target, strand, frame in targets:
        sub = target[frame:]
        for m in codon_re.finditer(sub):
            orf_seq = m.group(1)
            if len(orf_seq) // 3 >= min_codons:
                orfs.append(
                    {
                        "start": m.start() + frame,
                        "end": m.end() + frame,
                        "strand": strand,
                        "frame": frame,
                        "length_codons": len(orf_seq) // 3,
                        "protein": orf_seq[:120] + ("..." if len(orf_seq) > 120 else ""),
                    }
                )
    orfs.sort(key=lambda x: -x["length_codons"])
    return orfs


# ---------------------------------------------------------------------------
# bio_fastq_qc
# ---------------------------------------------------------------------------


@tool_handler
def fastq_qc(args: dict[str, Any], **kwargs: Any) -> str:
    files = args.get("files", [])
    if not files:
        return json.dumps({"error": "Provide at least one FASTQ 'files' path."})
    if not _ensure_biopython():
        return json.dumps({"error": "Biopython required. Run: pip install biopython"})

    sample_reads = args.get("sample_reads", 100000)
    report: dict[str, Any] = {"files": [], "summary": {}}
    all_lens: list[int] = []
    all_q: list[float] = []

    for fp in files:
        path = _resolve_path(fp)
        if not os.path.isfile(path):
            report["files"].append({"file": fp, "error": "not found"})
            continue
        try:
            from Bio import SeqIO

            lengths = []
            quals_per_pos: dict[int, list[float]] = {}
            ids = []
            n = 0
            for rec in SeqIO.parse(path, "fastq"):  # type: ignore[no-untyped-call]
                if sample_reads and n >= sample_reads:
                    break
                lengths.append(len(rec))
                ids.append(rec.id)
                for i, q in enumerate(rec.letter_annotations.get("phred_quality", [])):
                    quals_per_pos.setdefault(i, []).append(q)
                n += 1

            file_report = {
                "file": fp,
                "reads_sampled": n,
                "length_min": min(lengths) if lengths else 0,
                "length_max": max(lengths) if lengths else 0,
                "length_mean": round(sum(lengths) / len(lengths), 2) if lengths else 0,
                "per_position_mean_q": [
                    round(sum(v) / len(v), 2) for _, v in sorted(quals_per_pos.items())[:200]
                ],
            }
            all_lens.extend(lengths)
            all_q.extend(q for v in quals_per_pos.values() for q in v)

            # Duplication estimate
            if ids:
                unique = len(set(ids))
                file_report["duplication_rate"] = round(1 - unique / len(ids), 4)

            report["files"].append(file_report)
        except Exception as e:
            report["files"].append({"file": fp, "error": str(e)})

    # Adapter check
    adapter_file = args.get("adapter_file")
    if adapter_file and os.path.isfile(adapter_file) and all_lens:
        try:
            report["adapter_contamination"] = _check_adapters(files[0], adapter_file)
        except Exception as e:
            report["adapter_error"] = str(e)

    if all_q:
        report["summary"]["overall_mean_q"] = round(sum(all_q) / len(all_q), 2)
        report["summary"]["q30_fraction"] = round(sum(1 for q in all_q if q >= 30) / len(all_q), 4)
        report["summary"]["q20_fraction"] = round(sum(1 for q in all_q if q >= 20) / len(all_q), 4)
    if all_lens:
        report["summary"]["total_reads_sampled"] = len(all_lens)
        report["summary"]["length_distribution"] = _histogram(all_lens, 20)

    md_path = args.get("report_file")
    if md_path:
        _write_fastq_md(md_path, report)

    return json.dumps(report, indent=2)


def _check_adapters(fastq_path: str, adapter_fasta: str) -> dict[str, Any]:
    from Bio import SeqIO

    adapters = [str(r.seq) for r in SeqIO.parse(adapter_fasta, "fasta")]  # type: ignore[no-untyped-call]
    counts = {a[:20]: 0 for a in adapters}
    total = 0
    for rec in SeqIO.parse(fastq_path, "fastq"):  # type: ignore[no-untyped-call]
        if total >= 50000:
            break
        seq = str(rec.seq)
        for a in adapters:
            if a[:20] in seq:
                counts[a[:20]] += 1
        total += 1
    return {
        "total_checked": total,
        "adapters": counts,
        "contamination_rate": {k: round(v / total, 4) for k, v in counts.items()} if total else {},
    }


def _write_fastq_md(path: str, report: dict[str, Any]) -> None:
    with open(path, "w") as f:
        f.write("# FASTQ Quality Control Report\n\n")
        s = report.get("summary", {})
        f.write(f"**Reads sampled:** {s.get('total_reads_sampled', 'N/A')}\n\n")
        if "overall_mean_q" in s:
            f.write(f"**Mean quality:** Q{s['overall_mean_q']}\n\n")
            f.write(f"**Q30 fraction:** {s.get('q30_fraction', 'N/A')}\n\n")
        for fr in report.get("files", []):
            f.write(f"## {fr.get('file', '?')}\n\n")
            if "error" in fr:
                f.write(f"Error: {fr['error']}\n\n")
                continue
            f.write(f"- Reads sampled: {fr.get('reads_sampled')}\n")
            f.write(
                f"- Length: {fr.get('length_min')}-{fr.get('length_max')} "
                f"(mean {fr.get('length_mean')})\n"
            )
            if "duplication_rate" in fr:
                f.write(f"- Duplication rate: {fr['duplication_rate']:.1%}\n")
            f.write("\n")


# ---------------------------------------------------------------------------
# bio_seq_convert
# ---------------------------------------------------------------------------

# Mapping our format names to Biopython SeqIO format keys
_BIO_FORMAT_MAP = {
    "fasta": "fasta",
    "fastq": "fastq",
    "genbank": "genbank",
    "embl": "embl",
    "nexus": "nexus",
    "phylip": "phylip",
    "stockholm": "stockholm",
    "clustal": "clustal",
}


@tool_handler
def seq_convert(args: dict[str, Any], **kwargs: Any) -> str:
    inp = _resolve_path(args.get("input_file", ""))
    out_arg = args.get("output_file", "")
    out_fmt = args.get("output_format", "fasta")

    if not os.path.isfile(inp):
        return json.dumps({"error": f"Input not found: {inp}"})
    if not out_arg:
        return json.dumps({"error": "Provide 'output_file'."})
    outp = _resolve_path(out_arg)
    if not _ensure_biopython():
        return json.dumps({"error": "Biopython required. Run: pip install biopython"})

    in_fmt = _detect_format(inp)
    bio_out = _BIO_FORMAT_MAP.get(out_fmt, out_fmt)

    try:
        from Bio import SeqIO

        records = list(SeqIO.parse(inp, in_fmt))  # type: ignore[no-untyped-call]
        if not records:
            return json.dumps({"error": f"No records in {inp} ({in_fmt})"})
        # GenBank/EMBL require molecule_type annotation — add a default if missing
        if bio_out in ("genbank", "embl"):
            for rec in records:
                if "molecule_type" not in rec.annotations:
                    rec.annotations["molecule_type"] = "DNA"
        count = SeqIO.write(records, outp, bio_out)
        return json.dumps(
            {
                "input_file": inp,
                "input_format": in_fmt,
                "output_file": outp,
                "output_format": bio_out,
                "records_converted": count,
            }
        )
    except Exception as e:
        logger.exception("seq_convert failed")
        return json.dumps({"error": f"Conversion failed: {e}"})
