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
        combined=str(WORKDIR) + "/cgmlst/.batch/{scheme}/cgmlst_combined.json",
    params:
        sample_list=lambda wc: " ".join(
            _CGMLST_SCHEME_SAMPLES.get(wc.scheme, [])
        ),
        candidate_cap=_CGMLST_CANDIDATE_CAP,
    threads: _CGMLST_MAX_WORKERS
    wildcard_constraints:
        scheme="[^/]+"
    run:
        # v1.10.26：结果统一为 JSON（gmlst-typing-v1 envelope）；失败时写同构
        # 占位 JSON（status=FAILED），由拆分规则还原为逐样本文件。
        import json as _json
        import os as _os
        import subprocess as _subprocess

        _os.makedirs(_os.path.dirname(str(output.combined)), exist_ok=True)
        _os.makedirs(_CGMLST_BATCH_TMP, exist_ok=True)
        _env = dict(_os.environ)
        _env["GMLST_TMPDIR"] = _CGMLST_BATCH_TMP
        if params.candidate_cap > 0:
            _env["GMLST_CGMLST_CANDIDATE_MAX_ALLELES"] = str(params.candidate_cap)
        _samples = list(params.sample_list.split())
        _cmd = [
            GMLST_BIN, "typing", "cgmlst", "-s", str(wildcards.scheme),
            "--format", "json", "-t", "1", "--max-workers", str(threads),
            "-o", str(output.combined),
        ] + [str(_p) for _p in input]
        try:
            _ok = (
                _subprocess.run(
                    _cmd, env=_env, check=False,
                    stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
                ).returncode
                == 0
            )
        except OSError:
            _ok = False
        if not _ok:
            _data = [
                {
                    "sample_id": _s,
                    "scheme": str(wildcards.scheme),
                    "st": None,
                    "status": "FAILED",
                }
                for _s in _samples
            ]
            output.combined.write_text(
                _json.dumps(
                    {"schema_version": "gmlst-typing-v1", "data": _data}
                ),
                encoding="utf-8",
            )


def _cgmlst_combined_input(wc):
    _scheme = _CGMLST_SAMPLE_SCHEME.get(wc.sample, "")
    if not _scheme:
        return []
    return [str(WORKDIR) + f"/cgmlst/.batch/{_scheme}/cgmlst_combined.json"]


rule typing_cgmlst:
    """Slice the batched cgMLST JSON back into per-sample files.

    Keeps the per-sample interface (WORKDIR/<sample>/typing/cgmlst.json,
    gmlst-typing-v1) so downstream rules are unchanged. Samples without a
    scheme get a NO_SCHEME stub with no allele calls.
    """
    input:
        _cgmlst_combined_input
    output:
        str(WORKDIR) + "/{sample}/typing/cgmlst.json"
    wildcard_constraints:
        sample="[^/]+"
    run:
        import json as _json
        import os as _os

        _scheme = _CGMLST_SAMPLE_SCHEME.get(str(wildcards.sample), "")
        _os.makedirs(_os.path.dirname(str(output)), exist_ok=True)

        def _stub(status: str, scheme: str) -> dict:
            return {
                "schema_version": "gmlst-typing-v1",
                "data": [
                    {
                        "sample_id": str(wildcards.sample),
                        "scheme": scheme,
                        "st": None,
                        "status": status,
                    }
                ],
            }

        if not _scheme:
            payload = _stub("NO_SCHEME", "-")
        else:
            try:
                combined = _json.loads(open(str(input[0]), encoding="utf-8").read())
            except (OSError, ValueError):
                combined = {}
            _rows = [
                _row
                for _row in (combined.get("data") or [])
                if isinstance(_row, dict)
                and str(_row.get("sample_id")) == str(wildcards.sample)
            ]
            payload = (
                {
                    "schema_version": combined.get(
                        "schema_version", "gmlst-typing-v1"
                    ),
                    "data": _rows,
                }
                if _rows
                else _stub("FAILED", _scheme)
            )
        with open(str(output), "w", encoding="utf-8") as _fh:
            _json.dump(payload, _fh, ensure_ascii=False)


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
    # Per-group merged allele profiles (derived intermediate).
    # Authoritative per-sample results are JSON (typing/cgmlst.json);
    # `gmlst visual matrix/mst` still take a profile TSV, so this rule
    # derives a merged TSV for the external visualizer. Non-exact calls
    # are written as "-" (missing) — they carry no distance information.
    # ───────────────────────────────────────────────────────────
    rule cgmlst_cohort_profiles:
        input:
            lambda wc: expand(
                str(WORKDIR) + "/{sample}/typing/cgmlst.json",
                sample=_CGMLST_GROUP_SAMPLES.get(wc.group, []),
            )
        output:
            str(WORKDIR) + "/cgmlst/{group}/cgmlst_profiles.tsv"
        params:
            samples=lambda wc: _CGMLST_GROUP_SAMPLES.get(wc.group, []),
            scheme=lambda wc: _CGMLST_GROUP_SCHEMES[wc.group],
            group="{group}"
        run:
            from bacmap.core.utils import parse_cgmlst_profiles

            _cgmlst_os.makedirs(
                _cgmlst_os.path.dirname(str(output)), exist_ok=True
            )
            profiles = []
            for _path in input:
                try:
                    profiles.extend(
                        parse_cgmlst_profiles(open(str(_path)).read())
                    )
                except (OSError, ValueError):
                    continue
            loci = list(profiles[0].alleles) if profiles else []
            with open(str(output), "w") as _fh:
                _fh.write("\t".join(["File", "Scheme", "ST", *loci]) + "\n")
                for _p in profiles:
                    _cells = [
                        str(_p.alleles.get(_locus))
                        if isinstance(_p.alleles.get(_locus), int)
                        else "-"
                        for _locus in loci
                    ]
                    _fh.write(
                        "\t".join(
                            [
                                _p.sample_id or "",
                                _p.scheme,
                                _p.st_raw or "-",
                                *_cells,
                            ]
                        )
                        + "\n"
                    )

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
