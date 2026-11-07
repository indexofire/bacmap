"""Phylogenetic planning: alignment profile, typed plan, IQ-TREE command, BEAST2 XML."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bacmap.research import phylo


@pytest.fixture
def alignment(tmp_path: Path) -> Path:
    path = tmp_path / "aln.fasta"
    path.write_text(
        ">t1\nACGTACGTACGT\n"
        ">t2\nACGTACGTACGA\n"
        ">t3\nACGTTCGTACGT\n"
        ">t4\nACGTACGTTCGT\n",
        encoding="utf-8",
    )
    return path


def test_profile_counts(alignment: Path):
    profile = phylo.profile_alignment(alignment)
    assert profile.n_taxa == 4
    assert profile.n_sites == 12
    assert profile.variable_sites == 3
    assert profile.informative_sites == 0
    assert profile.missing_pct == 0.0
    assert profile.alignment_sha256
    assert any("fewer than 100 sites" in warning for warning in profile.warnings)


def test_profile_rejects_non_rectangular(tmp_path: Path):
    path = tmp_path / "bad.fasta"
    path.write_text(">t1\nACGT\n>t2\nACG\n", encoding="utf-8")
    with pytest.raises(phylo.PhyloError, match="not rectangular"):
        phylo.profile_alignment(path)


def test_profile_dates(alignment: Path, tmp_path: Path):
    dates = tmp_path / "dates.tsv"
    dates.write_text("t1\t2020-01-01\nt2\t2021-01-01\n", encoding="utf-8")
    profile = phylo.profile_alignment(alignment, dates=dates)
    assert profile.has_dates
    assert profile.date_min == "2020-01-01"
    assert profile.date_max == "2021-01-01"


def test_recommend_ml_plan(alignment: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "ml")
    assert plan.tool == "iqtree"
    assert plan.substitution_model == "MFP"
    assert plan.bootstrap == 1000
    assert plan.profile_sha256 == profile.sha256()
    assert phylo.validate_plan(plan, profile) == []


def test_recommend_bayesian_plan(alignment: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "bayesian")
    assert plan.tool == "beast2"
    assert plan.clock_model == "strict"
    assert plan.tree_prior == "coalescent"
    assert plan.chain_length >= 1_000_000
    assert plan.burn_in < plan.chain_length
    assert plan.sampling_every > 0


def test_validate_plan_catches_bad_chain_and_outgroup(alignment: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "bayesian")
    bad = plan.model_copy(update={"chain_length": 1000, "outgroup": "nope"})
    issues = phylo.validate_plan(bad, profile)
    assert any("chain_length" in issue for issue in issues)
    assert any("outgroup" in issue for issue in issues)


def test_iqtree_command(alignment: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "ml").model_copy(update={"outgroup": "t1"})
    cmd = phylo.render_iqtree_command(plan, alignment, "run")
    assert cmd[0] == "iqtree2"
    assert "-m" in cmd and "MFP" in cmd
    assert "-o" in cmd and "t1" in cmd


def test_beast2_xml_is_well_formed_and_complete(alignment: Path, tmp_path: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "bayesian")
    out = tmp_path / "beast.xml"
    result = phylo.render_beast2_xml(plan, profile, out)
    assert result["template"] == "beast2-strict-coalescent-v1"
    assert len(result["xml_sha256"]) == 64
    root = ET.parse(out).getroot()  # noqa: S314 — parsing our own generated XML
    assert root.tag == "beast"
    assert len(root.findall(".//sequence")) == 4
    run = root.find(".//run")
    assert run is not None
    assert run.attrib["chainLength"] == str(plan.chain_length)
    assert root.find(".//branchRateModel") is not None
    assert root.find(".//substModel") is not None
    assert root.find(".//distribution[@spec='Coalescent']") is not None


def test_beast2_xml_rejects_unsupported_template(alignment: Path, tmp_path: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "bayesian").model_copy(
        update={"clock_model": "relaxed_lognormal"}
    )
    with pytest.raises(phylo.UnsupportedPlanError, match="strict clock"):
        phylo.render_beast2_xml(plan, profile, tmp_path / "x.xml")


def test_beast2_xml_detects_alignment_change(alignment: Path, tmp_path: Path):
    profile = phylo.profile_alignment(alignment)
    plan = phylo.recommend_plan(profile, "bayesian")
    alignment.write_text(">t1\nAAAA\n>t2\nAAAA\n>t3\nAAAA\n>t4\nAAAA\n", encoding="utf-8")
    with pytest.raises(phylo.PhyloError, match="hash"):
        phylo.render_beast2_xml(plan, profile, tmp_path / "x.xml")


def test_phylo_cli_roundtrip(tmp_path: Path, alignment: Path, monkeypatch, capsys):
    from bacmap.interfaces.cli.main import main

    profile_path = tmp_path / "profile.json"
    plan_path = tmp_path / "plan.json"
    xml_path = tmp_path / "beast.xml"

    def run(argv: list[str]) -> dict:
        code = 0
        try:
            main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        out = capsys.readouterr().out
        assert code == 0, out
        return json.loads(out)

    profile = run(["research", "phylo", "profile", "--alignment", str(alignment), "--json"])
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    plan = run(
        ["research", "phylo", "plan", "--profile", str(profile_path), "--json"]
    )
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    valid = run(
        [
            "research",
            "phylo",
            "validate",
            "--profile",
            str(profile_path),
            "--plan",
            str(plan_path),
            "--json",
        ]
    )
    assert valid["ok"] is True
    result = run(
        [
            "research",
            "phylo",
            "xml",
            "--profile",
            str(profile_path),
            "--plan",
            str(plan_path),
            "--alignment",
            str(alignment),
            "-o",
            str(xml_path),
            "--json",
        ]
    )
    assert Path(result["xml"]).is_file()
