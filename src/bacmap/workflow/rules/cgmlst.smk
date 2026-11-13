import sys

# cgMLST per-sample typing (EnteroBase schemes via gmlst)
# Mirrors typing_mlst in typing_amr.smk but uses cgMLST schemes:
#   Salmonella          -> senterica_2          (3002 loci)
#   E.coli / Shigella   -> ecoli_2              (2513 loci)
#   V.parahaemolyticus  -> vparahaemolyticus_3  (2254 loci)
# cgMLST schemes come from TOOL_SELECTION.effective_gmlst (registry default
# plus the user's tool_selection.yaml overlay).  Classical-MLST schemes in
# typing_amr.smk are a different mode (mlst vs cgmlst/wgmlst).
# cgMLST cohort rules are added in todo 11 (gated by config.cgmlst.run_cgmlst_cohort).

from bacmap.core.pathogen_registry import get_workflow_tables, resolve_species  # noqa: E402

_TABLES = get_workflow_tables()

GMLST_BIN = "gmlst"


def _cgmlst_scheme(sample):
    """用户覆盖后的 cgMLST/wgMLST 方案；未选 → 空串（写 N/A，不猜方案）。"""
    code = resolve_species(SAMPLES_DF.loc[sample, "species"])
    plan = TOOL_SELECTION.effective_gmlst(code, sample=sample)
    if "cgmlst" in plan.modes:
        return plan.schemes.get("cgmlst", "")
    if "wgmlst" in plan.modes:
        return plan.schemes.get("wgmlst", "")
    return ""

# ─────────────────────────────────────────────────────────────────
# Batched invocation (2026-11 benchmark, senterica_2 / 3002 loci):
# every `gmlst typing cgmlst` command pays a fixed setup cost
# (~3.5-4 min: parsing the merged allele DB + loading the exact-hash
# cache) before any alignment, while the per-sample alignment itself is
# ~20-30 s and barely thread-sensitive (4m12s @ 1 thread vs 3m48s @ 16).
# Per-sample candidate temp copies reach ~14 GB uncapped, so parallel
# samples must not host them in a small tmpfs (/tmp) and typically need
# GMLST_CGMLST_CANDIDATE_MAX_ALLELES to stay inside btrfs qgroup quotas.
# Therefore: one batched gmlst invocation per scheme (setup amortized,
# samples parallelized via --max-workers with 1 alignment thread each),
# then a cheap split rule restores the per-sample cgmlst.tsv interface.
# ─────────────────────────────────────────────────────────────────
import os as _os

_CGMLST_SAMPLE_SCHEME: dict[str, str] = {
    _sample: _cgmlst_scheme(_sample) for _sample in SAMPLES
}
_CGMLST_SCHEME_SAMPLES: dict[str, list[str]] = {}
for _sample, _scheme in _CGMLST_SAMPLE_SCHEME.items():
    if _scheme:
        _CGMLST_SCHEME_SAMPLES.setdefault(_scheme, []).append(_sample)

_CGMLST_CFG = config.get("cgmlst", {})
_CGMLST_MAX_WORKERS = int(_CGMLST_CFG.get("batch_max_workers", 8))
# 0 = uncapped (max sensitivity, ~14 GB temp per sample for senterica_2);
# e.g. 100 shrinks the per-sample temp to ~0.2 GB at minimal sensitivity
# cost (candidates are ranked by the representative prefilter).
_CGMLST_CANDIDATE_CAP = int(_CGMLST_CFG.get("candidate_max_alleles", 100))

_CGMLST_BATCH_TMP = str(WORKDIR) + "/cgmlst/.tmp"


rule typing_cgmlst_batch:
    """Run gmlst once for every sample sharing a cgMLST/wgMLST scheme."""
    input:
        contigs=lambda wc: [
            str(WORKDIR) + f"/{_s}/assembly/{_s}.fasta"
            for _s in _CGMLST_SCHEME_SAMPLES.get(wc.scheme, [])
        ]
    output:
        combined=str(WORKDIR) + "/cgmlst/.batch/{scheme}/cgmlst_combined.tsv",
    params:
        sample_list=lambda wc: " ".join(
            _CGMLST_SCHEME_SAMPLES.get(wc.scheme, [])
        ),
        candidate_cap=_CGMLST_CANDIDATE_CAP,
    threads: _CGMLST_MAX_WORKERS
    wildcard_constraints:
        scheme="[^/]+"
    shell:
        "mkdir -p $(dirname {output.combined}) " + _CGMLST_BATCH_TMP + " && "
        "GMLST_TMPDIR=" + _CGMLST_BATCH_TMP + " "
        + (
            "GMLST_CGMLST_CANDIDATE_MAX_ALLELES={params.candidate_cap} "
            if _CGMLST_CANDIDATE_CAP > 0
            else ""
        )
        + "{GMLST_BIN} typing cgmlst -s {wildcards.scheme} --format tsv "
        "-t 1 --max-workers {threads} "
        "-o {output.combined} {input.contigs} || "
        "(printf 'File\\tScheme\\tST\\n'; "
        "for _s in {params.sample_list}; do "
        "printf '%s\\t{wildcards.scheme}\\tN/A\\n' \"$_s\"; done) "
        "> {output.combined}"


def _cgmlst_combined_input(wc):
    _scheme = _CGMLST_SAMPLE_SCHEME.get(wc.sample, "")
    if not _scheme:
        return []
    return [str(WORKDIR) + f"/cgmlst/.batch/{_scheme}/cgmlst_combined.tsv"]


rule typing_cgmlst:
    """Slice the batched cgMLST TSV back into per-sample files.

    Keeps the historical per-sample interface (WORKDIR/<sample>/typing/
    cgmlst.tsv) so downstream rules are unchanged. Samples without a
    scheme get the same File/Scheme/ST N/A row the old per-sample rule
    emitted.
    """
    input:
        _cgmlst_combined_input
    output:
        str(WORKDIR) + "/{sample}/typing/cgmlst.tsv"
    wildcard_constraints:
        sample="[^/]+"
    run:
        _scheme = _CGMLST_SAMPLE_SCHEME.get(str(wildcards.sample), "")
        _os.makedirs(_os.path.dirname(str(output)), exist_ok=True)
        if not _scheme:
            with open(str(output), "w") as _fh:
                _fh.write(f"File\tScheme\tST\n{wildcards.sample}\t-\tN/A\n")
        else:
            _lines = [_ln.rstrip("\n") for _ln in open(str(input[0])) if _ln.strip()]
            _rows = [
                _ln
                for _ln in _lines[1:]
                if _ln.split("\t", 1)[0] == str(wildcards.sample)
            ]
            with open(str(output), "w") as _fh:
                if _rows:
                    _fh.write(_lines[0] + "\n" + "\n".join(_rows) + "\n")
                else:
                    _fh.write(
                        f"File\tScheme\tST\n{wildcards.sample}\t{_scheme}\tN/A\n"
                    )


# ─────────────────────────────────────────────────────────────────
# Cohort rules (todo 11) — opt-in via config.cgmlst.run_cgmlst_cohort.
# Mirrors the snp.smk cohort structure (per-species-group profiles -> matrix
# -> tree -> summary) but for cgMLST allele distances. Outputs land under
# results/cgmlst/{group}/. The SNP cohort (snp.smk) is untouched; groups
# derive from pathogens.yaml (same source as snp.smk, no cross-import).
# ─────────────────────────────────────────────────────────────────
import os as _cgmlst_os

# Species grouping keyed on the cgMLST scheme rather than a reference
# genome; scheme from the registry's cgmlst_species_groups().
_CGMLST_SPECIES_GROUPS = _TABLES.cgmlst_species_groups

# Derive per-group sample lists. A group needs >=2 samples to justify joint
# analysis — mirrors the snp.smk:32-39 _GROUP_SAMPLES guard (single-sample
# groups are silently skipped).
def _group_effective_scheme(samples: list[str]) -> str:
    """All samples in a cohort must use the same cgMLST/wgMLST scheme."""
    schemes: set[str] = set()
    for _sample in samples:
        _plan = TOOL_SELECTION.effective_gmlst(
            resolve_species(SAMPLES_DF.loc[_sample, "species"]), sample=_sample
        )
        schemes.add(_plan.schemes.get("cgmlst") or _plan.schemes.get("wgmlst") or "")
    return schemes.pop() if len(schemes) == 1 else ""


_CGMLST_GROUP_SAMPLES: dict[str, list[str]] = {}
_CGMLST_GROUP_SCHEMES: dict[str, str] = {}
for _grp, _info in _CGMLST_SPECIES_GROUPS.items():
    _samps = [
        s for s in SAMPLES if resolve_species(SAMPLES_DF.loc[s, "species"]) in _info["species"]
    ]
    if len(_samps) < 2:
        continue
    _scheme = _group_effective_scheme(_samps)
    if not _scheme:
        # Mixed schemes or no scheme selected: skip the cohort rather than
        # joining incompatible allele columns.
        continue
    _CGMLST_GROUP_SAMPLES[_grp] = _samps
    _CGMLST_GROUP_SCHEMES[_grp] = _scheme

# Cohort is opt-in. With the flag off (default) _CGMLST_ACTIVE_GROUPS is empty
# AND the rule definitions below are skipped, so cohort targets are absent
# from the DAG entirely (snakemake --rule cgmlst_summary reports the rule as
# unknown). When the flag is on, active groups feed rule all (see Snakefile).
_RUN_CGMLST_COHORT = bool(
    config.get("cgmlst", {}).get("run_cgmlst_cohort", False)
)
_CGMLST_ACTIVE_GROUPS = (
    list(_CGMLST_GROUP_SAMPLES.keys()) if _RUN_CGMLST_COHORT else []
)


if _RUN_CGMLST_COHORT:

    # ───────────────────────────────────────────────────────────
    # Per-group merged allele profiles (cat per-sample cgmlst.tsv into one
    # multi-sample TSV). Same scheme across all samples in a group, so the
    # locus columns line up; gmlst fallback rows (File/Scheme/ST only) are
    # padded with "-" (missing) so the merged TSV stays rectangular.
    # ───────────────────────────────────────────────────────────
    rule cgmlst_cohort_profiles:
        input:
            lambda wc: expand(
                str(WORKDIR) + "/{sample}/typing/cgmlst.tsv",
                sample=_CGMLST_GROUP_SAMPLES.get(wc.group, []),
            )
        output:
            str(WORKDIR) + "/cgmlst/{group}/cgmlst_profiles.tsv"
        params:
            samples=lambda wc: _CGMLST_GROUP_SAMPLES.get(wc.group, []),
            scheme=lambda wc: _CGMLST_GROUP_SCHEMES[wc.group],
            group="{group}"
        run:
            _cgmlst_os.makedirs(
                _cgmlst_os.path.dirname(str(output)), exist_ok=True
            )
            header: list[str] | None = None
            rows: list[list[str]] = []
            for _sample, _path in zip(params.samples, input):
                with open(str(_path)) as _fh:
                    _lines = [ln.rstrip("\n") for ln in _fh if ln.strip()]
                if not _lines:
                    continue
                if header is None:
                    header = _lines[0].split("\t")
                for _row in _lines[1:]:
                    _cols = _row.split("\t")
                    # Pad short rows so every row matches the header width;
                    # gmlst fallback rows (File/Scheme/ST only) pad with "-"
                    # (missing), which the parser treats as a missing call.
                    if len(_cols) < len(header):
                        _cols = _cols + ["-"] * (len(header) - len(_cols))
                    rows.append(_cols)
            if header is None:
                # No usable input rows — emit a header-only TSV so downstream
                # rules see a well-formed (if empty) file rather than crashing.
                header = ["File", "Scheme", "ST"]
            with open(str(output), "w") as _fh:
                _fh.write("\t".join(header) + "\n")
                for _r in rows:
                    _fh.write("\t".join(_r) + "\n")

    # ───────────────────────────────────────────────────────────
    # Per-group Hamming distance matrix (JSON)
    # ───────────────────────────────────────────────────────────
    rule cgmlst_distance_matrix:
        input:
            profiles=str(WORKDIR) + "/cgmlst/{group}/cgmlst_profiles.tsv"
        output:
            matrix=str(WORKDIR) + "/cgmlst/{group}/distance_matrix.json"
        shell:
            "mkdir -p $(dirname {output.matrix}) && "
            "gmlst visual matrix --input {input.profiles} "
            "--output {output.matrix} --format json"

    # ───────────────────────────────────────────────────────────
    # Per-group tree (Newick) from the distance matrix. Default method is
    # "mst" (GrapeTree-style minimum spanning tree via scipy); "nj" available
    # via the --method param if a neighbour-joining layout is preferred.
    # ───────────────────────────────────────────────────────────
    rule cgmlst_mst:
        input:
            profiles=str(WORKDIR) + "/cgmlst/{group}/cgmlst_profiles.tsv"
        output:
            tree=str(WORKDIR) + "/cgmlst/{group}/core.treefile",
            payload=str(WORKDIR) + "/cgmlst/{group}/mst_payload.json"
        params:
            newick_script=str(
                PROJECT_ROOT
                / "workflows/bacmap/scripts/mst_to_newick.py"
            ),
            python=sys.executable
        shell:
            "mkdir -p $(dirname {output.tree}) && "
            "gmlst visual mst --input {input.profiles} "
            "--output {output.payload} --format json && "
            "{params.python} {params.newick_script} {output.payload} {output.tree}"

    # ───────────────────────────────────────────────────────────
    # Per-group cgMLST summary JSON (mirrors snp.smk snp_summary rule).
    # Bundles tree + allele distances + scheme/loci stats + the group's
    # configured thresholds into the single artifact consumed by the cohort
    # ingest (todo 13) and the cohort report (todo 14).
    # ───────────────────────────────────────────────────────────
    rule cgmlst_summary:
        input:
            tree=str(WORKDIR) + "/cgmlst/{group}/core.treefile",
            matrix=str(WORKDIR) + "/cgmlst/{group}/distance_matrix.json",
            profiles=str(WORKDIR) + "/cgmlst/{group}/cgmlst_profiles.tsv"
        output:
            summary=str(WORKDIR) + "/cgmlst/{group}/cgmlst_summary.json"
        params:
            script=str(
                PROJECT_ROOT
                / "workflows/bacmap/scripts/generate_cgmlst_summary.py"
            ),
            python=sys.executable,
            group="{group}",
            organism=lambda wc: _CGMLST_SPECIES_GROUPS[wc.group]["organism"],
            scheme=lambda wc: _CGMLST_GROUP_SCHEMES[wc.group],
            config_file=str(
                PROJECT_ROOT / "workflows/bacmap/config/config.yaml"
            )
        shell:
            "{params.python} {params.script} "
            "{input.tree} {input.matrix} {input.profiles} {output.summary} "
            "--group {params.group} --organism \"{params.organism}\" "
            "--scheme {params.scheme} --config-file {params.config_file}"
