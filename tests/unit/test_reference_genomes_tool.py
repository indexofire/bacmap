"""bio_list_reference_genomes：清单/供给状态/登记状态/取回命令。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from bacmap.tools import services as tools_services


def _setup(tmp_path: Path, monkeypatch) -> dict:
    wf = tmp_path / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "reference_accessions.yaml").write_text(
        yaml.safe_dump(
            {
                "genomes": {
                    "salmonella": {
                        "out": "salmonella_LT2.fasta",
                        "organism": "Salmonella LT2",
                        "accessions": ["NC_003197.2"],
                        "version": "NC_003197.2",
                    },
                    "vpara": {
                        "out": "vpara_rimd.fasta",
                        "organism": "Vibrio parahaemolyticus",
                        "accessions": ["NC_004603.1", "NC_004605.1"],
                        "version": "a+b",
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    genomes = tmp_path / "data" / "reference" / "genomes"
    genomes.mkdir(parents=True)
    (genomes / "salmonella_LT2.fasta").write_text(">x\nACGT\n", encoding="utf-8")
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "manifest.json").write_text(
        json.dumps(
            {
                "databases": [
                    {"name": "ref:salmonella", "version": "NC_003197.2", "checksum": "a" * 64}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools_services, "_DEPLOYED_WORKFLOWS_DIR", wf)
    monkeypatch.setattr(tools_services, "_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(tools_services, "_REFS_DIR", refs)
    return {"wf": wf}


class TestListReferenceGenomes:
    def test_reports_present_registered_and_missing(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        out = json.loads(tools_services.list_reference_genomes({}))
        assert out["n_total"] == 2
        assert out["n_present"] == 1
        by = {g["group"]: g for g in out["genomes"]}
        assert by["salmonella"]["present"] is True
        assert by["salmonella"]["registered"] is True
        assert by["salmonella"]["registered_checksum"] == "a" * 64
        assert by["vpara"]["present"] is False
        assert by["vpara"]["accessions"] == ["NC_004603.1", "NC_004605.1"]
        assert "fetch_reference_genomes.py" in out["fetch_command"]

    def test_group_filter(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        out = json.loads(tools_services.list_reference_genomes({"group": "vpara"}))
        assert out["n_total"] == 1
        assert out["genomes"][0]["group"] == "vpara"

    def test_missing_manifest_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            tools_services, "_reference_manifest_path", lambda: tmp_path / "none.yaml"
        )
        out = json.loads(tools_services.list_reference_genomes({}))
        assert "error" in out

    def test_falls_back_to_packaged_manifest(self, tmp_path, monkeypatch):
        """部署副本缺失时回退包内模板（智能体始终能看到清单）。"""
        monkeypatch.setattr(tools_services, "_DEPLOYED_WORKFLOWS_DIR", tmp_path / "nope")
        monkeypatch.setattr(tools_services, "_DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(tools_services, "_REFS_DIR", tmp_path / "refs")
        out = json.loads(tools_services.list_reference_genomes({}))
        assert out["n_total"] == 3  # salmonella / ecoli / vpara（包内模板）
        assert {g["group"] for g in out["genomes"]} == {"salmonella", "ecoli", "vpara"}
