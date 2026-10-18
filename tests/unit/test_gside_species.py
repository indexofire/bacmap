"""gside 物种鉴定适配器：升级阶梯 + 库未就绪守卫 + 契约不变。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_gside_species", _SCRIPTS / "gside_species.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _raw(species: str | None, version: str = "0.1.1") -> dict:
    return {
        "version": version,
        "verdict": {"species": species, "confidence": "high", "basis": ["marker"]},
        "methods": {
            "marker": {"interpretation": f"Identified as {species}", "detected_markers": []}
        },
    }


class TestLadder:
    def test_no_escalation_single_mode(self):
        mod = _load()
        assert mod._ladder("simple", False, "all") == ["marker"]
        assert mod._ladder("panel", False, "all") == ["panel"]

    def test_escalation_full_ladder(self):
        mod = _load()
        assert mod._ladder("simple", True, "all") == [
            "marker",
            "panel",
            "mash_refseq",
            "sourmash",
            "all",
        ]

    def test_escalation_capped_at_max(self):
        mod = _load()
        assert mod._ladder("panel", True, "mash_refseq") == ["panel", "mash_refseq"]

    def test_max_below_start_is_clamped(self):
        mod = _load()
        assert mod._ladder("panel", True, "simple") == ["panel"]


class TestRunEscalation:
    def _run(self, mod, tmp_path: Path, argv: list[str]) -> dict:
        out = tmp_path / "species_id.json"
        sys.argv = ["gside_species.py", "--contigs", "c.fasta", "--out", str(out), *argv]
        assert mod.main() == 0
        return json.loads(out.read_text())

    def test_escalates_until_identified(self, tmp_path, monkeypatch):
        mod = _load()
        table = {"marker": _raw("Unknown"), "panel": _raw("Salmonella")}

        def fake(contigs, mode):
            return table.get(mode), None

        monkeypatch.setattr(mod, "_call_gside", fake)
        out = self._run(mod, tmp_path, ["--mode", "simple", "--escalation", "--mode-max", "all"])
        assert out["species"] == "Salmonella"
        assert out["escalated"] is True
        assert out["gside_mode"] == "panel"
        assert [a["mode"] for a in out["attempts"]] == ["marker", "panel"]

    def test_all_tiers_fail_keeps_unknown_with_attempts(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "_call_gside", lambda c, m: (None, f"{m}: db not provisioned"))
        out = self._run(mod, tmp_path, ["--mode", "simple", "--escalation"])
        assert out["species"] == "Unknown"
        assert out["escalated"] is True
        assert len(out["attempts"]) == 5
        assert "db not provisioned" in out["error"]

    def test_no_escalation_single_attempt(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "_call_gside", lambda c, m: (_raw("Klebsiella_pneumoniae"), None))
        out = self._run(mod, tmp_path, ["--mode", "simple"])
        assert out["escalated"] is False
        assert len(out["attempts"]) == 1
        assert out["species"] == "Klebsiella_pneumoniae"


class TestIsIdentified:
    @pytest.mark.parametrize(
        ("species", "expected"),
        [
            ("Salmonella", True),
            ("Klebsiella_pneumoniae", True),
            ("Unknown", False),
            ("N/A", False),
            ("", False),
            (None, False),
        ],
    )
    def test_identity_check(self, species, expected):
        mod = _load()
        assert mod._is_identified(species) is expected
