"""参考基因组供给（NCBI）：拼接、跳过、失败不中断、manifest 登记。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_fetch_refs", _SCRIPTS / "fetch_reference_genomes.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "reference_accessions.yaml"
    path.write_text(
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
                        "version": "NC_004603.1+NC_004605.1",
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def _run(mod, tmp_path: Path, argv: list[str]) -> int:
    sys.argv = ["fetch_reference_genomes.py", *argv]
    return mod.main()


class TestFetch:
    def test_multi_accession_concatenated(self, tmp_path, monkeypatch):
        mod = _load()
        calls: list[str] = []

        def fake(accession, *, email=None, timeout=120):
            calls.append(accession)
            return f">{accession}\nACGT\n"

        monkeypatch.setattr(mod, "_fetch_fasta", fake)
        out_dir = tmp_path / "genomes"
        rc = _run(
            mod,
            tmp_path,
            ["--manifest", str(_manifest(tmp_path)), "--out-dir", str(out_dir)],
        )
        assert rc == 0
        vpara = (out_dir / "vpara_rimd.fasta").read_text()
        assert vpara.count(">") == 2
        assert ">NC_004603.1" in vpara and ">NC_004605.1" in vpara

    def test_existing_file_skipped(self, tmp_path, monkeypatch):
        mod = _load()
        out_dir = tmp_path / "genomes"
        out_dir.mkdir()
        (out_dir / "salmonella_LT2.fasta").write_text(">old\nAAAA\n")
        monkeypatch.setattr(
            mod, "_fetch_fasta", lambda *a, **k: pytest.fail("should not fetch when present")
        )
        rc = _run(
            mod,
            tmp_path,
            [
                "--manifest",
                str(_manifest(tmp_path)),
                "--out-dir",
                str(out_dir),
                "--only",
                "salmonella",
            ],
        )
        assert rc == 0
        assert (out_dir / "salmonella_LT2.fasta").read_text() == ">old\nAAAA\n"

    def test_failure_does_not_abort_others(self, tmp_path, monkeypatch):
        mod = _load()

        def fake(accession, *, email=None, timeout=120):
            if accession.startswith("NC_0046"):
                raise OSError("network down")
            return f">{accession}\nACGT\n"

        monkeypatch.setattr(mod, "_fetch_fasta", fake)
        out_dir = tmp_path / "genomes"
        rc = _run(
            mod,
            tmp_path,
            ["--manifest", str(_manifest(tmp_path)), "--out-dir", str(out_dir)],
        )
        assert rc == 0  # 非 strict：失败不中断
        assert (out_dir / "salmonella_LT2.fasta").is_file()
        assert not (out_dir / "vpara_rimd.fasta").exists()

    def test_strict_returns_nonzero_on_failure(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(
            mod, "_fetch_fasta", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
        )
        rc = _run(
            mod,
            tmp_path,
            ["--manifest", str(_manifest(tmp_path)), "--out-dir", str(tmp_path / "g"), "--strict"],
        )
        assert rc == 1

    def test_registers_manifest_and_preserves_existing(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(
            mod, "_fetch_fasta", lambda acc, *, email=None, timeout=120: ">x\nACGT\n"
        )
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "manifest.json").write_text(
            json.dumps({"databases": [{"name": "gapit:card", "version": "1", "checksum": "c"}]})
        )
        out_dir = tmp_path / "genomes"
        rc = _run(
            mod,
            tmp_path,
            [
                "--manifest",
                str(_manifest(tmp_path)),
                "--out-dir",
                str(out_dir),
                "--refs-dir",
                str(refs),
            ],
        )
        assert rc == 0
        db = json.loads((refs / "manifest.json").read_text())["databases"]
        names = {d["name"] for d in db}
        assert names == {"gapit:card", "ref:salmonella", "ref:vpara"}
        ref_entry = next(d for d in db if d["name"] == "ref:salmonella")
        assert ref_entry["version"] == "NC_003197.2"
        assert len(ref_entry["checksum"]) == 64
