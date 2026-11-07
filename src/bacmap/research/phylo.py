"""Phylogenetic analysis planning and deterministic BEAST2 XML rendering.

The AI proposes a typed ``PhyloPlan`` from a deterministic ``AlignmentProfile``;
bacmap validates the plan, renders a BEAST2 XML template and (optionally) runs
``beast -validate``.  The AI never writes free-form XML into a run.

Supported BEAST2 template (v1): HKY or GTR, optional +G/+I, strict clock, constant
coalescent.  Other combinations are rejected with a clear message and belong to the
``mine`` open path (custom XML with hashes + human sign-off) until a template exists.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
from html import escape
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROFILE_SCHEMA: Literal["bacmap.phylo_profile/1"] = "bacmap.phylo_profile/1"
PLAN_SCHEMA: Literal["bacmap.phylo_plan/1"] = "bacmap.phylo_plan/1"
XML_SCHEMA: Literal["bacmap.phylo_xml/1"] = "bacmap.phylo_xml/1"

Goal = Literal["ml", "bayesian"]
ClockModel = Literal["strict", "relaxed_lognormal", "random_local", ""]
TreePrior = Literal["coalescent", "birth_death", "yule", ""]
SubstitutionModel = Literal["HKY", "GTR", "MFP"]


class PhyloError(Exception):
    """Raised when a profile/plan/XML cannot be produced safely."""


class UnsupportedPlanError(PhyloError):
    """The plan is valid in principle but no deterministic template exists yet."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _parse_fasta_lines(lines: Any, source: Path) -> dict[str, str]:
    records: dict[str, list[str]] = {}
    name = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            name = line[1:].split()[0]
            if not name:
                raise PhyloError("empty FASTA header")
            if name in records:
                raise PhyloError(f"duplicate FASTA taxon: {name}")
            records[name] = []
        elif name:
            records[name].append(line.upper())
        else:
            raise PhyloError("sequence data before the first FASTA header")
    if not records:
        raise PhyloError(f"empty alignment: {source}")
    return {taxon: "".join(parts) for taxon, parts in records.items()}


def _read_fasta(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise PhyloError(f"alignment not found: {path}")
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return _parse_fasta_lines(handle, path)
    with path.open("rt", encoding="utf-8") as handle:
        return _parse_fasta_lines(handle, path)


def _read_dates(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise PhyloError(f"dates file not found: {path}")
    dates: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 2:
            raise PhyloError(f"dates line needs taxon and date: {line!r}")
        dates[parts[0].strip()] = parts[1].strip()
    return dates


class AlignmentProfile(BaseModel):
    """Deterministic facts about an alignment; the input to AI parameter planning."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["bacmap.phylo_profile/1"] = Field(
        default=PROFILE_SCHEMA, alias="schema"
    )
    alignment: str
    alignment_sha256: str
    taxa: list[str]
    n_taxa: int
    n_sites: int
    gap_pct: float
    ambiguous_pct: float
    missing_pct: float
    variable_sites: int
    informative_sites: int
    has_dates: bool = False
    date_min: str = ""
    date_max: str = ""
    partitions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def sha256(self) -> str:
        return _sha256_text(_canonical(self.model_dump(mode="json", by_alias=True)))


def profile_alignment(
    alignment: str | Path,
    *,
    dates: str | Path | None = None,
    partitions: list[str] | None = None,
) -> AlignmentProfile:
    """Read a FASTA alignment and compute conservative summary statistics."""
    path = Path(alignment).expanduser().resolve()
    records = _read_fasta(path)
    taxa = sorted(records)
    lengths = {taxon: len(records[taxon]) for taxon in taxa}
    if len(set(lengths.values())) != 1:
        detail = ", ".join(f"{taxon}={lengths[taxon]}" for taxon in taxa[:8])
        raise PhyloError(f"alignment is not rectangular: {detail}")
    n_taxa = len(taxa)
    n_sites = next(iter(lengths.values()))
    if n_sites == 0:
        raise PhyloError("alignment has zero sites")

    gap = 0
    ambiguous = 0
    variable = 0
    informative = 0
    for site in range(n_sites):
        states: dict[str, int] = {}
        for taxon in taxa:
            char = records[taxon][site]
            if char in {"-", "."}:
                gap += 1
                continue
            if char not in {"A", "C", "G", "T", "U"}:
                ambiguous += 1
                continue
            states[char] = states.get(char, 0) + 1
        if len(states) > 1:
            variable += 1
            if sum(1 for count in states.values() if count >= 2) >= 2:
                informative += 1

    total = n_taxa * n_sites
    gap_pct = 100.0 * gap / total
    ambiguous_pct = 100.0 * ambiguous / total
    missing_pct = gap_pct + ambiguous_pct

    date_map = _read_dates(Path(dates) if dates is not None else None)
    unknown = sorted(set(date_map) - set(taxa))
    if unknown:
        raise PhyloError(f"dates reference unknown taxa: {', '.join(unknown)}")
    warnings: list[str] = []
    if n_taxa < 4:
        warnings.append("fewer than 4 taxa: tree inference is underpowered")
    if n_sites < 100:
        warnings.append("fewer than 100 sites: model selection is unstable")
    if missing_pct > 50.0:
        warnings.append("more than 50% missing/ambiguous data")
    if variable == 0:
        warnings.append("no variable sites: no phylogenetic signal")

    return AlignmentProfile(
        alignment=str(path),
        alignment_sha256=_sha256_file(path),
        taxa=taxa,
        n_taxa=n_taxa,
        n_sites=n_sites,
        gap_pct=round(gap_pct, 4),
        ambiguous_pct=round(ambiguous_pct, 4),
        missing_pct=round(missing_pct, 4),
        variable_sites=variable,
        informative_sites=informative,
        has_dates=bool(date_map),
        date_min=min(date_map.values()) if date_map else "",
        date_max=max(date_map.values()) if date_map else "",
        partitions=list(partitions or []),
        warnings=warnings,
    )


class PhyloPlan(BaseModel):
    """Structured parameter proposal; AI supplies it, bacmap validates and renders."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["bacmap.phylo_plan/1"] = Field(
        default=PLAN_SCHEMA, alias="schema"
    )
    plan_id: str
    analysis: Goal
    tool: Literal["iqtree", "beast2"]
    substitution_model: SubstitutionModel
    rate_heterogeneity: list[Literal["+G", "+I"]] = Field(default_factory=list)
    clock_model: ClockModel = ""
    tree_prior: TreePrior = ""
    bootstrap: int = 0
    chain_length: int = 0
    burn_in: int = 0
    sampling_every: int = 0
    seed: int = 42
    partitions: str = "none"
    outgroup: str = ""
    rationale: str = ""
    constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    profile_sha256: str

    @field_validator("seed")
    @classmethod
    def _seed_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("seed must be non-negative")
        return value

    def sha256(self) -> str:
        return _sha256_text(_canonical(self.model_dump(mode="json", by_alias=True)))


def _plan_id(profile: AlignmentProfile, goal: str) -> str:
    return "pp-" + _sha256_text(f"{profile.sha256()}:{goal}")[:12]


def recommend_plan(profile: AlignmentProfile, goal: Goal = "bayesian") -> PhyloPlan:
    """Deterministic starting plan; the AI may revise fields before validation."""
    if goal == "ml":
        plan = PhyloPlan(
            plan_id=_plan_id(profile, goal),
            analysis="ml",
            tool="iqtree",
            substitution_model="MFP",
            rate_heterogeneity=["+G"],
            bootstrap=1000,
            seed=42,
            partitions="none",
            rationale=(
                "IQ-TREE with ModelFinder (MFP), 1000 ultrafast bootstrap replicates "
                "and gamma rate heterogeneity; no clock model for ML."
            ),
            constraints=["model selection: ModelFinder", "bootstrap: 1000 UFBoot"],
            warnings=list(profile.warnings),
            profile_sha256=profile.sha256(),
        )
        return plan

    chain = max(10_000_000, min(500_000_000, profile.n_taxa * profile.n_sites * 1000))
    chain = max(10_000_000, (chain // 1_000_000) * 1_000_000)
    plan = PhyloPlan(
        plan_id=_plan_id(profile, goal),
        analysis="bayesian",
        tool="beast2",
        substitution_model="HKY",
        rate_heterogeneity=["+G"] if profile.variable_sites else [],
        clock_model="strict",
        tree_prior="coalescent",
        chain_length=chain,
        burn_in=chain // 10,
        sampling_every=max(1000, chain // 10_000),
        seed=42,
        partitions="none",
        rationale=(
            "BEAST2 strict clock with a constant-size coalescent prior and HKY"
            + ("+G" if profile.variable_sites else "")
            + "; chain length scaled from taxa × sites. Validate the XML before running."
        ),
        constraints=[
            "template: strict clock + constant coalescent",
            "validate with `beast -validate` before execution",
            "use a custom XML via the mine path for relaxed clocks or birth-death priors",
        ],
        warnings=list(profile.warnings),
        profile_sha256=profile.sha256(),
    )
    return plan


def validate_plan(plan: PhyloPlan, profile: AlignmentProfile) -> list[str]:
    """Return human-readable issues; an empty list means the plan is structurally valid."""
    issues: list[str] = []
    if plan.profile_sha256 != profile.sha256():
        issues.append("plan was built from a different alignment profile")
    if plan.analysis == "ml":
        if plan.tool != "iqtree":
            issues.append("ML analysis must use iqtree")
        if plan.bootstrap < 0 or plan.bootstrap > 100_000:
            issues.append("bootstrap must be between 0 and 100000")
    else:
        if plan.tool != "beast2":
            issues.append("Bayesian analysis must use beast2")
        if plan.chain_length < 1_000_000:
            issues.append("BEAST2 chain_length must be >= 1000000")
        if plan.burn_in < 0 or plan.burn_in >= plan.chain_length:
            issues.append("burn_in must be >= 0 and < chain_length")
        if plan.sampling_every <= 0:
            issues.append("sampling_every must be > 0")
        if not plan.clock_model:
            issues.append("Bayesian analysis requires a clock model")
        if not plan.tree_prior:
            issues.append("Bayesian analysis requires a tree prior")
    if plan.outgroup and plan.outgroup not in profile.taxa:
        issues.append(f"outgroup {plan.outgroup!r} is not in the alignment")
    if plan.partitions not in {"none", "by_gene", "by_codon"}:
        issues.append("partitions must be none, by_gene or by_codon")
    return issues


def render_iqtree_command(plan: PhyloPlan, alignment: str | Path, prefix: str) -> list[str]:
    if plan.tool != "iqtree":
        raise PhyloError("render_iqtree_command requires an iqtree plan")
    cmd = [
        "iqtree2",
        "-s",
        str(Path(alignment).expanduser().resolve()),
        "-m",
        plan.substitution_model,
        "-B",
        str(plan.bootstrap),
        "-T",
        "AUTO",
        "--seed",
        str(plan.seed),
        "--prefix",
        prefix,
    ]
    if plan.outgroup:
        cmd += ["-o", plan.outgroup]
    return cmd


def _beast_sequences(records: dict[str, str]) -> str:
    lines: list[str] = []
    for taxon in sorted(records):
        value = "".join(
            "?" if char not in {"A", "C", "G", "T"} else char
            for char in records[taxon].replace("U", "T")
        )
        lines.append(
            f'    <sequence id="seq_{escape(taxon)}" taxon="{escape(taxon)}" '
            f'totalcount="4" value="{value}"/>'
        )
    return "\n".join(lines)


def _subst_model(plan: PhyloPlan) -> tuple[str, str, str, str, str]:
    """Return (parameter, model, prior, operator, log) XML fragments."""
    if plan.substitution_model == "HKY":
        parameter = (
            '      <parameter id="kappa.s:alignment" lower="0.0" name="stateNode">2.0</parameter>'
        )
        model = (
            '          <substModel id="hky.s:alignment" spec="HKY">\n'
            '            <parameter idref="kappa.s:alignment"/>\n'
            '            <frequencies id="estimatedFreqs.s:alignment" spec="Frequencies">\n'
            '              <frequencyModel id="freqs.s:alignment" spec="FrequencyModel">\n'
            '                <data idref="alignment"/>\n'
            '                <parameter id="freqs.s:alignment" estimate="false" name="freqs">'
            "0.25 0.25 0.25 0.25</parameter>\n"
            "              </frequencyModel>\n"
            "            </frequencies>\n"
            "          </substModel>"
        )
        prior = (
            '        <prior id="KappaPrior.s:alignment" name="distribution" '
            'x="@kappa.s:alignment">\n'
            '          <LogNormal id="LogNormalDistributionModel.0" name="distr" '
            'M="1.0" S="1.25"/>\n'
            "        </prior>"
        )
        operator = (
            '    <operator id="KappaScaler.s:alignment" spec="ScaleOperator" '
            'parameter="@kappa.s:alignment" scaleFactor="0.5" weight="0.1"/>'
        )
        log = '      <log idref="kappa.s:alignment"/>'
        return parameter, model, prior, operator, log
    if plan.substitution_model == "GTR":
        parameter = (
            '      <parameter id="rates.s:alignment" dimension="6" lower="0.0" '
            'name="stateNode">1.0 1.0 1.0 1.0 1.0 1.0</parameter>'
        )
        model = (
            '          <substModel id="gtr.s:alignment" spec="GTR">\n'
            '            <parameter idref="rates.s:alignment"/>\n'
            '            <frequencies id="estimatedFreqs.s:alignment" spec="Frequencies">\n'
            '              <frequencyModel id="freqs.s:alignment" spec="FrequencyModel">\n'
            '                <data idref="alignment"/>\n'
            '                <parameter id="freqs.s:alignment" estimate="false" name="freqs">'
            "0.25 0.25 0.25 0.25</parameter>\n"
            "              </frequencyModel>\n"
            "            </frequencies>\n"
            "          </substModel>"
        )
        prior = (
            '        <prior id="RatesPrior.s:alignment" name="distribution" '
            'x="@rates.s:alignment">\n'
            '          <Exponential id="Exponential.0" name="distr">\n'
            '            <parameter id="Exponential.0.mean" estimate="false" '
            'name="mean">1.0</parameter>\n'
            "          </Exponential>\n"
            "        </prior>"
        )
        operator = (
            '    <operator id="RateScaler.s:alignment" spec="ScaleOperator" '
            'parameter="@rates.s:alignment" scaleFactor="0.5" weight="0.1"/>'
        )
        log = '      <log idref="rates.s:alignment"/>'
        return parameter, model, prior, operator, log
    raise UnsupportedPlanError(
        f"BEAST2 template does not support substitution model {plan.substitution_model!r}"
    )


def render_beast2_xml(
    plan: PhyloPlan,
    profile: AlignmentProfile,
    output: str | Path,
    *,
    validate: bool = False,
) -> dict[str, Any]:
    """Render a v1 BEAST2 XML template (strict clock, constant coalescent)."""
    if plan.tool != "beast2":
        raise PhyloError("render_beast2_xml requires a beast2 plan")
    if plan.clock_model != "strict":
        raise UnsupportedPlanError(
            "BEAST2 template v1 supports only the strict clock; use the mine path for "
            "relaxed clocks"
        )
    if plan.tree_prior != "coalescent":
        raise UnsupportedPlanError(
            "BEAST2 template v1 supports only the constant coalescent prior; use the mine "
            "path for birth-death or Yule priors"
        )
    if plan.partitions != "none":
        raise UnsupportedPlanError("BEAST2 template v1 supports only unpartitioned alignments")
    if plan.rate_heterogeneity not in ([], ["+G"]):
        raise UnsupportedPlanError(
            "BEAST2 template v1 supports no rate heterogeneity or +G only"
        )
    issues = validate_plan(plan, profile)
    if issues:
        raise PhyloError("invalid plan: " + "; ".join(issues))

    alignment_path = Path(profile.alignment).expanduser().resolve()
    records = _read_fasta(alignment_path)
    if sorted(records) != profile.taxa:
        raise PhyloError("alignment changed since the profile was computed")
    if _sha256_file(alignment_path) != profile.alignment_sha256:
        raise PhyloError("alignment hash does not match the profile")

    subst_parameter, subst_model, subst_prior, subst_operator, subst_log = _subst_model(plan)
    gamma = "+G" in plan.rate_heterogeneity
    gamma_category = "4" if gamma else "1"
    gamma_shape = (
        '            <parameter id="gammaShape.s:alignment" name="stateNode">1.0</parameter>'
        if gamma
        else '            <parameter id="gammaShape.s:alignment" estimate="false" '
        'name="shape">1.0</parameter>'
    )
    gamma_prior = (
        '        <prior id="GammaShapePrior.s:alignment" name="distribution" '
        'x="@gammaShape.s:alignment">\n'
        '          <Exponential id="Exponential.1" name="distr">\n'
        '            <parameter id="Exponential.1.mean" estimate="false" '
        'name="mean">1.0</parameter>\n'
        "          </Exponential>\n"
        "        </prior>"
        if gamma
        else ""
    )
    gamma_operator = (
        '    <operator id="GammaShapeScaler.s:alignment" spec="ScaleOperator" '
        'parameter="@gammaShape.s:alignment" scaleFactor="0.5" weight="0.1"/>'
        if gamma
        else ""
    )
    gamma_log = '      <log idref="gammaShape.s:alignment"/>' if gamma else ""
    priors = "\n".join(part for part in (subst_prior, gamma_prior) if part)
    operators = "\n".join(
        part
        for part in (
            subst_operator,
            gamma_operator,
            '    <operator id="ClockRateScaler.c:alignment" spec="ScaleOperator" '
            'parameter="@clockRate.c:alignment" scaleFactor="0.5" weight="0.1"/>',
            '    <operator id="PopSizeScaler.t:alignment" spec="ScaleOperator" '
            'parameter="@popSize.t:alignment" scaleFactor="0.5" weight="0.1"/>',
            '    <operator id="TreeScaler.t:alignment" spec="ScaleOperator" '
            'scaleFactor="0.5" tree="@Tree.t:alignment" weight="3.0"/>',
            '    <operator id="TreeRootScaler.t:alignment" spec="ScaleOperator" '
            'rootOnly="true" scaleFactor="0.5" tree="@Tree.t:alignment" weight="3.0"/>',
            '    <operator id="UniformOperator.t:alignment" spec="Uniform" '
            'tree="@Tree.t:alignment" weight="30.0"/>',
            '    <operator id="SubtreeSlide.t:alignment" spec="SubtreeSlide" '
            'tree="@Tree.t:alignment" weight="15.0"/>',
            '    <operator id="narrow.t:alignment" spec="Exchange" '
            'tree="@Tree.t:alignment" weight="15.0"/>',
            '    <operator id="wide.t:alignment" spec="Exchange" isNarrow="false" '
            'tree="@Tree.t:alignment" weight="3.0"/>',
            '    <operator id="WilsonBalding.t:alignment" spec="WilsonBalding" '
            'tree="@Tree.t:alignment" weight="3.0"/>',
        )
        if part
    )
    logs = "\n".join(
        part
        for part in (
            subst_log,
            gamma_log,
            '      <log idref="clockRate.c:alignment"/>',
            '      <log idref="popSize.t:alignment"/>',
        )
        if part
    )

    namespace = (
        "beast.core:beast.evolution.alignment:beast.evolution.tree.coalescent:"
        "beast.core.util:beast.evolution.nuc:beast.evolution.operators:"
        "beast.evolution.sitemodel:beast.evolution.substitutionmodel:"
        "beast.evolution.likelihood:beast.evolution.tree:"
        "beast.math.distributions:beast.evolution.speciation"
    )
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<beast version="2.7" namespace="{namespace}">
  <data id="alignment" name="alignment">
{_beast_sequences(records)}
  </data>
  <map name="Uniform">beast.math.distributions.Uniform</map>
  <map name="Exponential">beast.math.distributions.Exponential</map>
  <map name="LogNormal">beast.math.distributions.LogNormal</map>
  <map name="prior">beast.math.distributions.Prior</map>
  <run id="mcmc" spec="MCMC" chainLength="{plan.chain_length}" storeEvery="{plan.sampling_every}">
    <state id="state" storeEvery="{plan.sampling_every}">
      <tree id="Tree.t:alignment" name="stateNode">
        <taxonset id="TaxonSet.alignment" spec="TaxonSet">
          <alignment idref="alignment"/>
        </taxonset>
      </tree>
      <parameter id="clockRate.c:alignment" name="stateNode">1.0</parameter>
{subst_parameter}
      <parameter id="popSize.t:alignment" name="stateNode">1.0</parameter>
    </state>
    <distribution id="posterior" spec="CompoundDistribution">
      <distribution id="prior" spec="CompoundDistribution">
        <distribution id="CoalescentConstant.t:alignment" spec="Coalescent">
          <populationModel id="ConstantPopulation.t:alignment" spec="ConstantPopulation">
            <parameter idref="popSize.t:alignment"/>
          </populationModel>
          <treeIntervals id="TreeIntervals.t:alignment" spec="TreeIntervals">
            <tree idref="Tree.t:alignment"/>
          </treeIntervals>
        </distribution>
        <prior id="ClockPrior.c:alignment" name="distribution" x="@clockRate.c:alignment">
          <Uniform id="Uniform.0" name="distr" upper="Infinity"/>
        </prior>
{priors}
        <prior id="PopSizePrior.t:alignment" name="distribution" x="@popSize.t:alignment">
          <OneOnX id="OneOnX.0" name="distr"/>
        </prior>
      </distribution>
      <distribution id="likelihood" spec="CompoundDistribution">
        <distribution id="treeLikelihood.alignment" spec="TreeLikelihood">
          <data idref="alignment"/>
          <tree idref="Tree.t:alignment"/>
          <siteModel id="SiteModel.s:alignment" spec="SiteModel"
                    gammaCategoryCount="{gamma_category}">
            <parameter id="mutationRate.s:alignment" estimate="false"
                       name="mutationRate">1.0</parameter>
{gamma_shape}
            <parameter id="proportionInvariant.s:alignment" estimate="false" lower="0.0"
                       name="proportionInvariant" upper="1.0">0.0</parameter>
{subst_model}
          </siteModel>
          <branchRateModel id="StrictClock.c:alignment"
                           spec="beast.evolution.branchratemodel.StrictClockModel">
            <parameter idref="clockRate.c:alignment"/>
          </branchRateModel>
        </distribution>
      </distribution>
    </distribution>
{operators}
    <logger id="tracelog" fileName="$(filebase).log" logEvery="{plan.sampling_every}">
      <log idref="posterior"/>
      <log idref="likelihood"/>
      <log idref="prior"/>
      <log idref="treeLikelihood.alignment"/>
{logs}
    </logger>
    <logger id="treelog.t:alignment" fileName="$(filebase).trees"
            logEvery="{plan.sampling_every}" mode="tree">
      <log id="TreeWithMetaDataLogger.t:alignment"
           spec="beast.evolution.tree.TreeWithMetaDataLogger" tree="@Tree.t:alignment"/>
    </logger>
  </run>
</beast>
'''
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(xml, encoding="utf-8")

    validation: dict[str, Any] = {"requested": validate, "ok": False, "output": ""}
    if validate:
        beast = shutil.which("beast") or shutil.which("beast2")
        if not beast:
            validation["output"] = "beast/beast2 not found in PATH"
        else:
            proc = subprocess.run(
                [beast, "-validate", str(target)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            validation = {
                "requested": True,
                "ok": proc.returncode == 0,
                "output": (proc.stdout + proc.stderr)[-2000:],
            }
    return {
        "schema": XML_SCHEMA,
        "xml": str(target),
        "xml_sha256": _sha256_file(target),
        "plan_sha256": plan.sha256(),
        "alignment_sha256": profile.alignment_sha256,
        "template": "beast2-strict-coalescent-v1",
        "validation": validation,
    }
