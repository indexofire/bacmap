"""Skani engine backend and ANI species identification (species-id plan A)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

SKANI_SEARCH_OUTPUT = (
    "ref_filename\tquery_filename\tEstimated_aligned_cross-coverage\t"
    "Estimated_query_aligned_fraction\tEstimated_ref_aligned_fraction\tANI\n"
    "GCF_000006945.2.fna\tctgs.fasta\t0.9231\t0.9210\t0.9250\t98.71\n"
    "GCF_000195995.1.fna\tctgs.fasta\t0.8810\t0.8790\t0.8830\t97.02\n"
)


@pytest.fixture
def skani_run(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd

        class R:
            returncode = 0
            stdout = SKANI_SEARCH_OUTPUT

        return R()

    from bacmap.core.engine.backends import skani as skani_mod

    monkeypatch.setattr(skani_mod, "which", lambda name: "/usr/bin/skani")
    monkeypatch.setattr(skani_mod.subprocess, "run", fake_run)
    return captured


class TestSkaniBackend:
    def test_registered_in_engine(self):
        from bacmap.core.engine.backends import available

        assert "skani" in available()

    def test_search_parses_ani_and_af(self, skani_run):
        from bacmap.core.engine.backends.skani import SkaniBackend

        hits = SkaniBackend().search(Path("ctgs.fasta"), Path("db"))
        assert len(hits) == 2
        assert hits[0].ref == "GCF_000006945.2.fna"
        assert hits[0].ani == pytest.approx(98.71)
        assert hits[0].aligned_fraction == pytest.approx(0.9210)
        assert hits[0].backend == "skani"

    def test_search_command_shape(self, skani_run):
        from bacmap.core.engine.backends.skani import SkaniBackend

        SkaniBackend().search(Path("ctgs.fasta"), Path("db"))
        cmd = skani_run["cmd"]
        assert "search" in cmd and "ctgs.fasta" in cmd and "db" in cmd


def _panel_db(tmp_path):
    db = tmp_path / "refseq_panel"
    db.mkdir()
    (db / "metadata.tsv").write_text(
        "accession\tspecies\nGCF_000006945.2.fna\tSalmonella enterica\n"
        "GCF_000195995.1.fna\tSalmonella bongori\n",
        encoding="utf-8",
    )
    return db


class TestIdentifyByAni:
    def test_high_confidence_above_95(self, tmp_path, monkeypatch):
        from bacmap.core.analysis import ani_identifier

        monkeypatch.setattr(
            ani_identifier,
            "_skani_search",
            lambda q, db: ani_identifier._hits_from_rows([("GCF_000006945.2.fna", 98.71, 0.921)]),
        )
        res = ani_identifier.identify_by_ani("ctgs.fasta", "panel", _panel_db(tmp_path))
        assert res.result["species"] == "Salmonella enterica"
        assert res.result["confidence"] == "high"
        assert res.method == "panel"

    def test_boundary_zone_93_to_95_is_medium(self, tmp_path, monkeypatch):
        from bacmap.core.analysis import ani_identifier

        monkeypatch.setattr(
            ani_identifier,
            "_skani_search",
            lambda q, db: ani_identifier._hits_from_rows([("GCF_000006945.2.fna", 94.2, 0.90)]),
        )
        res = ani_identifier.identify_by_ani("ctgs.fasta", "panel", _panel_db(tmp_path))
        assert res.result["confidence"] == "medium"
        assert res.result["species"] == "Salmonella enterica"

    def test_below_93_unknown_keeps_top_hits(self, tmp_path, monkeypatch):
        from bacmap.core.analysis import ani_identifier

        monkeypatch.setattr(
            ani_identifier,
            "_skani_search",
            lambda q, db: ani_identifier._hits_from_rows([("GCF_000006945.2.fna", 88.0, 0.70)]),
        )
        res = ani_identifier.identify_by_ani("ctgs.fasta", "panel", _panel_db(tmp_path))
        assert res.result["species"] == "Unknown"
        assert res.result["confidence"] == "low"
        assert res.result["top_hits"][0]["ani"] == 88.0

    def test_low_aligned_fraction_demotes(self, tmp_path, monkeypatch):
        from bacmap.core.analysis import ani_identifier

        monkeypatch.setattr(
            ani_identifier,
            "_skani_search",
            lambda q, db: ani_identifier._hits_from_rows([("GCF_000006945.2.fna", 98.7, 0.40)]),
        )
        res = ani_identifier.identify_by_ani("ctgs.fasta", "panel", _panel_db(tmp_path))
        assert res.result["confidence"] == "low"

    def test_mash_mode_uses_identity_threshold(self, tmp_path, monkeypatch):
        from bacmap.core.analysis import ani_identifier

        monkeypatch.setattr(ani_identifier, "_mash_dist", lambda q, msh: [("ref1", 0.985)])
        monkeypatch.setattr(ani_identifier, "_mash_species", lambda ref: "Salmonella enterica")
        res = ani_identifier.identify_by_ani("ctgs.fasta", "mash_refseq", tmp_path)
        assert res.method == "mash_refseq"
        assert res.result["species"] == "Salmonella enterica"

    def test_database_version_from_manifest(self, tmp_path, monkeypatch):
        import json

        (tmp_path / "manifests").mkdir()
        (tmp_path / "manifests" / "refseq_panel.json").write_text(
            json.dumps({"checksum": "abcdef1234567890"}), encoding="utf-8"
        )
        from bacmap.core.analysis import ani_identifier

        monkeypatch.setattr(
            ani_identifier,
            "_skani_search",
            lambda q, db: ani_identifier._hits_from_rows([("GCF_000006945.2.fna", 98.7, 0.92)]),
        )
        res = ani_identifier.identify_by_ani("ctgs.fasta", "panel", _panel_db(tmp_path))
        assert res.database == {
            "name": "refseq_panel",
            "version": "abcdef12",
        }
