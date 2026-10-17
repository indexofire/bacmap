"""External-CLI tool handlers.

Covers bio_blast, bio_align, bio_samtools, bio_variant. These detect the
binary at call time and return a clear error JSON if missing — never raise.
All handlers return JSON strings. Errors are {"error": "..."}.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any

from ._common import (
    _ensure_biopython,
    _resolve_path,
    _run_cmd,
    _which_or_error,
    logger,
    tool_handler,
)


@tool_handler
def blast(args: dict[str, Any], **kwargs: Any) -> str:
    mode = args.get("mode", "remote")
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "Provide 'query'."})

    program = args.get("program", "blastn")
    evalue = args.get("expect", 10)
    max_hits = args.get("max_hits", 10)
    out_file = args.get("output_file")

    if mode == "remote":
        return _blast_remote(
            query,
            args.get("query_is_file", False),
            program,
            args.get("database", "nt"),
            evalue,
            max_hits,
            out_file,
        )
    elif mode == "local":
        return _blast_local(
            query,
            args.get("query_is_file", False),
            program,
            args.get("database", ""),
            evalue,
            max_hits,
            out_file,
        )
    return json.dumps({"error": f"Unknown mode: {mode}"})


def _blast_remote(
    query: str,
    is_file: bool,
    program: str,
    db: str,
    evalue: float,
    max_hits: int,
    out_file: str | None,
) -> str:
    if not _ensure_biopython():
        return json.dumps({"error": "Biopython required. Run: pip install biopython"})
    try:
        from Bio.Blast import NCBIWWW, NCBIXML
    except Exception as e:
        logger.exception("blast_remote import failed")
        return json.dumps({"error": f"Blast module import failed: {e}"})

    query_str = query
    if is_file:
        with open(query) as f:
            query_str = f.read()

    try:
        result_handle = NCBIWWW.qblast(
            program,
            db,
            query_str,
            expect=evalue,
            hitlist_size=max_hits,
        )
        blast_records = list(NCBIXML.parse(result_handle))
    except Exception as e:
        logger.exception("blast_remote failed")
        return json.dumps({"error": f"NCBI BLAST failed: {e}"})

    hits = []
    for rec in blast_records:
        for alignment in rec.alignments:
            for hsp in alignment.hsps:
                hits.append(
                    {
                        "title": alignment.title,
                        "length": alignment.length,
                        "e_value": hsp.expect,
                        "bit_score": hsp.bits,
                        "identity": hsp.identities,
                        "align_length": hsp.align_length,
                        "query_start": hsp.query_start,
                        "identity_pct": round(hsp.identities / hsp.align_length * 100, 2)
                        if hsp.align_length
                        else 0,
                    }
                )

    hits = hits[:max_hits]
    if out_file:
        with open(out_file, "w") as f:
            f.write("query\tsubject\tevalue\tbitscore\tidentity%\n")
            for h in hits:
                f.write(
                    f"{query[:50]}\t{h['title']}\t{h['e_value']}\t"
                    f"{h['bit_score']}\t{h['identity_pct']}\n"
                )

    return json.dumps(
        {
            "mode": "remote",
            "program": program,
            "database": db,
            "hit_count": len(hits),
            "hits": hits[:50],
        },
        indent=2,
    )


def _blast_local(
    query: str,
    is_file: bool,
    program: str,
    subject: str,
    evalue: float,
    max_hits: int,
    out_file: str | None,
) -> str:
    if not subject:
        return json.dumps({"error": "Local BLAST needs 'database' (subject FASTA)."})
    blast_bin = _which_or_error(program)
    if not blast_bin:
        return json.dumps(
            {"error": f"{program} not found. Install blast+ (e.g. apt install ncbi-blast+)."}
        )
    makedb = _which_or_error("makeblastdb")
    if not makedb:
        return json.dumps({"error": "makeblastdb not found. Install blast+."})

    subj_path = _resolve_path(subject)
    db_prefix = subj_path + ".blastdb"

    # Build DB if not present
    if not os.path.exists(db_prefix + ".ndb" if makedb else db_prefix + ".nsq"):
        r = _run_cmd(
            [
                "makeblastdb",
                "-in",
                subj_path,
                "-dbtype",
                "nucl" if program in ("blastn", "tblastn", "tblastx") else "prot",
                "-out",
                db_prefix,
            ]
        )
        if r["returncode"] != 0:
            return json.dumps({"error": "makeblastdb failed", "stderr": r["stderr"]})

    query_path = query if is_file else None
    tmp_query = None
    if not query_path:
        tmp_query = tempfile.NamedTemporaryFile(mode="w", suffix=".fa", delete=False)
        tmp_query.write(f">query\n{query}\n")
        tmp_query.close()
        query_path = tmp_query.name

    cmd = [
        program,
        "-query",
        query_path,
        "-db",
        db_prefix,
        "-evalue",
        str(evalue),
        "-max_target_seqs",
        str(max_hits),
        "-outfmt",
        "6",
    ]
    r = _run_cmd(cmd)
    if tmp_query:
        os.unlink(tmp_query.name)

    if r["returncode"] != 0:
        return json.dumps({"error": f"{program} failed", "stderr": r["stderr"]})

    # Parse tabular output
    hits = []
    for line in r["stdout"].strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 12:
            hits.append(
                {
                    "query": parts[0],
                    "subject": parts[1],
                    "identity_pct": float(parts[2]),
                    "align_length": int(parts[3]),
                    "e_value": float(parts[10]),
                    "bit_score": float(parts[11]),
                }
            )

    if out_file:
        with open(out_file, "w") as f:
            f.write(r["stdout"])

    return json.dumps(
        {
            "mode": "local",
            "program": program,
            "subject": subject,
            "hit_count": len(hits),
            "hits": hits[:50],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# bio_align — BWA / minimap2 / STAR wrapper
# ---------------------------------------------------------------------------


@tool_handler
def align(args: dict[str, Any], **kwargs: Any) -> str:
    aligner = args.get("aligner", "")
    ref = args.get("reference", "")
    reads = args.get("reads", [])
    out_bam = args.get("output_bam", "")
    extra = args.get("extra_args", "")

    if not ref or not reads:
        return json.dumps({"error": "Need 'reference' and 'reads'."})
    ref_path = _resolve_path(ref)
    if not os.path.isfile(ref_path):
        return json.dumps({"error": f"Reference not found: {ref_path}"})
    if not out_bam:
        return json.dumps({"error": "Need 'output_bam'."})

    if aligner == "star":
        return json.dumps(
            {
                "error": "STAR alignment is complex (requires a genome index directory). "
                "Use the terminal tool to run STAR directly with appropriate --genomeDir.",
                "reference": ref_path,
                "reads": reads,
            }
        )

    read_args = [_resolve_path(r) for r in reads]
    for r in read_args:
        if not os.path.isfile(r):
            return json.dumps({"error": f"Read file not found: {r}"})

    mode = aligner if aligner in ("bwa-mem", "bwa", "minimap2") else "auto"
    mapper_kwargs = {}
    if extra:
        mapper_kwargs["extra_args"] = extra
    if aligner == "minimap2" and args.get("preset"):
        mapper_kwargs["preset"] = args["preset"]
    if args.get("read_type"):
        mapper_kwargs["read_type"] = args["read_type"]

    try:
        from bacmap.core.engine import ReadMapper

        result = ReadMapper.map(
            reads=read_args,
            reference=ref_path,
            out_bam=out_bam,
            mode=mode,
            **mapper_kwargs,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("align failed")
        return json.dumps({"error": f"Alignment failed: {e}"})


# ---------------------------------------------------------------------------
# bio_samtools — wrapper for common samtools operations
# ---------------------------------------------------------------------------


@tool_handler
def samtools_op(args: dict[str, Any], **kwargs: Any) -> str:
    op = args.get("operation", "")
    inp = args.get("input", "")
    if not op or not inp:
        return json.dumps({"error": "Need 'operation' and 'input'."})

    samtools = _which_or_error("samtools")
    if not samtools:
        return json.dumps(
            {"error": "samtools not found. Install: conda install -c bioconda samtools"}
        )

    inp_path = _resolve_path(inp)
    if not os.path.isfile(inp_path):
        return json.dumps({"error": f"Input not found: {inp_path}"})

    output = args.get("output")
    output_path = _resolve_path(output) if output else None
    region = args.get("region", "")
    flags = args.get("flags", "")
    extra = args.get("extra_args", "")

    cmd: list[str] = ["samtools"]

    if op == "sort":
        if not output_path:
            return json.dumps({"error": "sort needs 'output'."})
        cmd += ["sort", "-@", str(os.cpu_count() or 4)]
        if extra:
            cmd += extra.split()
        cmd += ["-o", output_path, inp_path]
    elif op == "index":
        cmd += ["index", inp_path]
    elif op == "view":
        cmd += ["view"]
        if flags:
            cmd += flags.split()
        if extra:
            cmd += extra.split()
        if output_path:
            cmd += ["-o", output_path]
        cmd += [inp_path]
        if region:
            cmd.append(region)
    elif op == "depth":
        cmd += ["depth"]
        if region:
            cmd += ["-r", region]
        cmd += [inp_path]
    elif op == "flagstat":
        cmd += ["flagstat", inp_path]
    elif op == "idxstats":
        cmd += ["idxstats", inp_path]
    elif op == "mpileup":
        if not output_path:
            return json.dumps({"error": "mpileup needs 'output'."})
        cmd += ["mpileup", "-f", args.get("reference", ""), "-o", output_path, inp_path]
        if not args.get("reference"):
            return json.dumps({"error": "mpileup needs 'reference' FASTA."})
    elif op == "faidx" or op == "fasta_index":
        cmd += ["faidx", inp_path]
    else:
        return json.dumps({"error": f"Unknown operation: {op}"})

    r = _run_cmd(cmd)
    if r["returncode"] != 0:
        return json.dumps({"error": f"samtools {op} failed", "stderr": r["stderr"]})

    result: dict[str, Any] = {
        "operation": op,
        "input": inp,
        "output": output,
        "returncode": r["returncode"],
    }
    if r["stdout"].strip():
        # Truncate large stdout
        lines = r["stdout"].strip().split("\n")
        result["stdout"] = "\n".join(lines[:100])
        result["stdout_lines"] = len(lines)
    if r["stderr"].strip():
        result["stderr_tail"] = r["stderr"].strip().split("\n")[-3:]
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# bio_variant — variant calling / manipulation
# ---------------------------------------------------------------------------


@tool_handler
def variant(args: dict[str, Any], **kwargs: Any) -> str:
    op = args.get("operation", "")
    inp = args.get("input", "")
    if not op:
        return json.dumps({"error": "Need 'operation'."})

    if op == "mpileup_call":
        return _var_mpileup_call(inp, args)
    elif op == "filter":
        return _var_filter(inp, args)
    elif op == "query":
        return _var_query(inp, args)
    elif op == "annotate":
        return _var_annotate(inp, args)
    elif op == "consensus":
        return _var_consensus(inp, args)
    return json.dumps({"error": f"Unknown operation: {op}"})


def _var_mpileup_call(inp: str, args: dict[str, Any]) -> str:
    bcftools = _which_or_error("bcftools")
    if not bcftools:
        return json.dumps(
            {"error": "bcftools not found. Install: conda install -c bioconda bcftools"}
        )
    samtools = _which_or_error("samtools")
    if not samtools:
        return json.dumps({"error": "samtools not found."})

    inp_path = _resolve_path(inp)
    ref = args.get("reference", "")
    if not ref:
        return json.dumps({"error": "mpileup_call needs 'reference' FASTA."})
    ref_path = _resolve_path(ref)
    output = args.get("output")
    if not output:
        return json.dumps({"error": "Need 'output' VCF path."})
    out_path = _resolve_path(output)
    extra = args.get("extra_args", "")

    # Index reference if needed
    if not os.path.exists(ref_path + ".fai"):
        subprocess.run(["samtools", "faidx", ref_path], capture_output=True, timeout=120)

    # Index BAM if needed
    if not os.path.exists(inp_path + ".bai"):
        subprocess.run(["samtools", "index", inp_path], capture_output=True, timeout=120)

    mpileup_cmd = [
        "bcftools",
        "mpileup",
        "-f",
        ref_path,
        inp_path,
    ]
    if extra:
        mpileup_cmd += extra.split()
    call_cmd = ["bcftools", "call", "-mv", "-Ov"]

    # 管道：mpileup | call > output
    # 注意：p1 的 stderr 必须落到临时文件（不是 PIPE）——否则 stderr 写满会阻塞 mpileup、
    # 进而 p2 读不到 stdout 而死锁；且 p2 超时必须 kill p1，避免遗留进程。
    import tempfile

    with tempfile.TemporaryFile() as mpileup_err:
        p1 = subprocess.Popen(mpileup_cmd, stdout=subprocess.PIPE, stderr=mpileup_err)
        assert p1.stdout is not None
        try:
            with open(out_path, "wb") as f:
                p2 = subprocess.run(
                    call_cmd,
                    stdin=p1.stdout,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=600,
                )
        except subprocess.TimeoutExpired:
            p1.kill()
            p1.wait()
            return json.dumps({"error": "bcftools call timed out (600s)"})
        finally:
            p1.stdout.close()
        rc1 = p1.wait()
        mpileup_err.seek(0)
        err = mpileup_err.read().decode(errors="replace") + p2.stderr.decode(errors="replace")

    if rc1 != 0 or p2.returncode != 0:
        return json.dumps({"error": "bcftools mpileup/call failed", "stderr": err[-2000:]})

    return json.dumps(
        {
            "operation": "mpileup_call",
            "input_bam": inp,
            "reference": ref,
            "output_vcf": out_path,
            "variant_count": _count_vcf_records(out_path),
        }
    )


def _var_filter(inp: str, args: dict[str, Any]) -> str:
    bcftools = _which_or_error("bcftools")
    if not bcftools:
        return json.dumps({"error": "bcftools not found."})
    inp_path = _resolve_path(inp)
    if not os.path.isfile(inp_path):
        return json.dumps({"error": f"VCF not found: {inp_path}"})
    output = args.get("output", inp_path + ".filtered.vcf")
    out_path = _resolve_path(output)
    expr = args.get("filter_expr", "")
    if not expr:
        return json.dumps({"error": "Need 'filter_expr' (e.g. 'QUAL>30 && DP>10')"})
    extra = args.get("extra_args", "")

    cmd = ["bcftools", "filter", "-i", expr, "-o", out_path, inp_path]
    if extra:
        cmd += extra.split()
    r = _run_cmd(cmd)
    if r["returncode"] != 0:
        return json.dumps({"error": "bcftools filter failed", "stderr": r["stderr"]})

    return json.dumps(
        {
            "operation": "filter",
            "input": inp,
            "output": out_path,
            "filter_expr": expr,
            "input_variants": _count_vcf_records(inp_path),
            "filtered_variants": _count_vcf_records(out_path),
        }
    )


def _var_query(inp: str, args: dict[str, Any]) -> str:
    bcftools = _which_or_error("bcftools")
    if not bcftools:
        return json.dumps({"error": "bcftools not found."})
    inp_path = _resolve_path(inp)
    if not os.path.isfile(inp_path):
        return json.dumps({"error": f"VCF not found: {inp_path}"})
    qfmt = args.get("query", "%CHROM\\t%POS\\t%REF\\t%ALT\\t%QUAL\\n")
    extra = args.get("extra_args", "")

    cmd = ["bcftools", "query", "-f", qfmt, inp_path]
    if extra:
        cmd += extra.split()
    r = _run_cmd(cmd)
    if r["returncode"] != 0:
        return json.dumps({"error": "bcftools query failed", "stderr": r["stderr"]})

    lines = r["stdout"].strip().split("\n") if r["stdout"].strip() else []
    return json.dumps(
        {
            "operation": "query",
            "input": inp,
            "format": qfmt,
            "record_count": len(lines),
            "results": lines[:200],
        }
    )


def _var_annotate(inp: str, args: dict[str, Any]) -> str:
    bcftools = _which_or_error("bcftools")
    if not bcftools:
        return json.dumps({"error": "bcftools not found."})
    inp_path = _resolve_path(inp)
    if not os.path.isfile(inp_path):
        return json.dumps({"error": f"VCF not found: {inp_path}"})
    output = args.get("output", inp_path + ".annotated.vcf")
    out_path = _resolve_path(output)
    extra = args.get("extra_args", "")

    cmd = ["bcftools", "annotate", "-o", out_path, inp_path]
    if extra:
        cmd += extra.split()
    r = _run_cmd(cmd)
    if r["returncode"] != 0:
        return json.dumps({"error": "bcftools annotate failed", "stderr": r["stderr"]})

    return json.dumps(
        {
            "operation": "annotate",
            "input": inp,
            "output": out_path,
        }
    )


def _var_consensus(inp: str, args: dict[str, Any]) -> str:
    bcftools = _which_or_error("bcftools")
    if not bcftools:
        return json.dumps({"error": "bcftools not found."})
    inp_path = _resolve_path(inp)
    ref = args.get("reference", "")
    if not ref:
        return json.dumps({"error": "consensus needs 'reference' FASTA."})
    ref_path = _resolve_path(ref)
    output = args.get("output")
    if not output:
        return json.dumps({"error": "Need 'output' FASTA path."})
    out_path = _resolve_path(output)
    extra = args.get("extra_args", "")

    # Index reference if needed
    if not os.path.exists(ref_path + ".fai"):
        subprocess.run(["samtools", "faidx", ref_path], capture_output=True, timeout=120)

    cmd = ["bcftools", "consensus", "-f", ref_path, inp_path]
    if extra:
        cmd += extra.split()
    with open(out_path, "w") as f:
        proc = subprocess.run(cmd, stdout=f, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        return json.dumps({"error": "bcftools consensus failed", "stderr": proc.stderr})

    return json.dumps(
        {
            "operation": "consensus",
            "input_vcf": inp,
            "reference": ref,
            "output_fasta": out_path,
        }
    )


def _count_vcf_records(path: str) -> int:
    """Count non-header, non-empty lines in a VCF."""
    if not os.path.isfile(path):
        return 0
    count = 0
    with open(path) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                count += 1
    return count
