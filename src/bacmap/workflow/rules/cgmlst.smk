import sys

# cgMLST per-sample typing (EnteroBase schemes via gmlst)
# Mirrors typing_mlst in typing_amr.smk but uses cgMLST schemes:
#   Salmonella          -> senterica_2          (3002 loci)
#   E.coli / Shigella   -> ecoli_2              (2513 loci)
#   V.parahaemolyticus  -> vparahaemolyticus_3  (2254 loci)
# NOTE: _CGMLST_SCHEMES is DIFFERENT from _GMLST_SCHEMES in typing_amr.smk
#       (those are classical-MLST schemes: salmonella_2/ecoli_1/vparahaemolyticus_1).
# Both mappings derive from pathogens.yaml (single source of truth).
# cgMLST cohort rules are added in todo 11 (gated by config.cgmlst.run_cgmlst_cohort).

from bacmap.core.pathogen_registry import get_workflow_tables, resolve_species  # noqa: E402

_TABLES = get_workflow_tables()

_CGMLST_SCHEMES = _TABLES.cgmlst_schemes
GMLST_BIN = "gmlst"


def _cgmlst_scheme(sample):
    """samples.tsv species 值（码/标签/显示名）→ cgMLST 方案。"""
    return _CGMLST_SCHEMES.get(resolve_species(SAMPLES_DF.loc[sample, "species"]) or "", "ecoli_2")

rule typing_cgmlst:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        str(WORKDIR) + "/{sample}/typing/cgmlst.tsv"
    params:
        scheme = lambda wc: _cgmlst_scheme(wc.sample)
    threads: 4
    shell:
        "mkdir -p $(dirname {output}) && "
        "{GMLST_BIN} typing cgmlst -s {params.scheme} --format tsv "
        "-o {output} {input.contigs} || "
        "echo -e 'File\\tScheme\\tST\\n{wildcards.sample}\\t{params.scheme}\\tN/A' > {output}"


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
_CGMLST_GROUP_SAMPLES: dict[str, list[str]] = {}
for _grp, _info in _CGMLST_SPECIES_GROUPS.items():
    _samps = [
        s for s in SAMPLES if resolve_species(SAMPLES_DF.loc[s, "species"]) in _info["species"]
    ]
    if len(_samps) >= 2:
        _CGMLST_GROUP_SAMPLES[_grp] = _samps

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
            scheme=lambda wc: _CGMLST_SPECIES_GROUPS[wc.group]["scheme"],
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
            scheme=lambda wc: _CGMLST_SPECIES_GROUPS[wc.group]["scheme"],
            config_file=str(
                PROJECT_ROOT / "workflows/bacmap/config/config.yaml"
            )
        shell:
            "{params.python} {params.script} "
            "{input.tree} {input.matrix} {input.profiles} {output.summary} "
            "--group {params.group} --organism \"{params.organism}\" "
            "--scheme {params.scheme} --config-file {params.config_file}"
