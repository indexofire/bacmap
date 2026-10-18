"""vpara_virulence → gapit 换装测试（ADR-20）。

覆盖：gapit 报告归一化、自定义库构建幂等、refs/manifest 登记、部署期构建接线，
以及一个真实 gapit 冒烟（建库 + 筛查，缺 gapit 时跳过）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import bacmap.workflow.runner as wf_runner
from bacmap.workflow.scripts import build_gapit_db as bgd
from bacmap.workflow.scripts import vpara_virulence as vv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REF_FASTA = _REPO_ROOT / "src" / "bacmap" / "workflow" / "refs" / "vpara_virulence.fasta"

_GAPIT_REPORT = {
    "schema": "gapit.report/1",
    "tool": {"name": "gapit", "version": "0.5.4"},
    "params": {"db": "vpara_virulence", "minid": 80.0, "mincov": 80.0},
    "files": [
        {
            "file": "contigs.fasta",
            "hits": [
                {"gene": "tdh", "sequence": "tdh", "coverage_pct": 100.0, "identity_pct": 99.0},
                {"gene": "tlh", "sequence": "tlh", "coverage_pct": 98.0, "identity_pct": 95.0},
            ],
        }
    ],
}


class TestNormalize:
    def test_targets_from_hits(self):
        out = vv.normalize(_GAPIT_REPORT)
        assert out["tool"] == "gapit"
        assert out["tool_version"] == "0.5.4"
        assert out["database"] == "vpara_virulence"
        assert out["tdh"] is True and out["tlh"] is True and out["trh"] is False
        assert out["n_hits"] == 2 and len(out["hits"]) == 2

    def test_empty_report_all_false(self):
        out = vv.normalize({"schema": "gapit.report/1", "files": []})
        assert out["tdh"] is False and out["trh"] is False and out["tlh"] is False
        assert out["n_hits"] == 0

    def test_gene_case_insensitive(self):
        rep = {"files": [{"hits": [{"gene": "TDH"}]}]}
        assert vv.normalize(rep)["tdh"] is True


class TestBuildDb:
    def test_db_built_flag(self, tmp_path):
        assert bgd.db_built(tmp_path, "vpara_virulence") is False
        d = tmp_path / "vpara_virulence"
        d.mkdir()
        (d / "gapit-manifest.json").write_text("{}")
        assert bgd.db_built(tmp_path, "vpara_virulence") is True

    def test_register_manifest_new_and_upsert(self, tmp_path):
        mp = tmp_path / "refs" / "manifest.json"
        bgd.register_manifest(mp, "vpara_virulence", "0.5.4", "abc")
        data = json.loads(mp.read_text())
        assert data["databases"] == [
            {"name": "gapit:vpara_virulence", "version": "0.5.4", "checksum": "abc"}
        ]
        # 再登记同名 → 更新而非重复
        bgd.register_manifest(mp, "vpara_virulence", "0.5.5", "def")
        data = json.loads(mp.read_text())
        assert len(data["databases"]) == 1
        assert data["databases"][0]["version"] == "0.5.5"

    def test_main_idempotent_skips_when_present(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(bgd.subprocess, "run", lambda *a, **k: calls.append(a) or _P(0))
        d = tmp_path / "gapit" / "vpara_virulence"
        d.mkdir(parents=True)
        (d / "gapit-manifest.json").write_text(
            json.dumps({"sha256": "s", "tool": {"version": "0.5.4"}})
        )
        rc = bgd.main(["--fasta", str(_REF_FASTA), "--datadir", str(tmp_path / "gapit")])
        assert rc == 0
        assert calls == []  # 已存在 → 不调用 gapit

    def test_main_builds_and_registers(self, tmp_path, monkeypatch):
        def fake_run(cmd, **kwargs):
            # 模拟 gapit 建库产出 manifest
            name = cmd[3]
            datadir = Path(cmd[cmd.index("-D") + 1])
            d = datadir / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "gapit-manifest.json").write_text(
                json.dumps({"sha256": "deadbeef", "tool": {"version": "0.5.4"}})
            )
            return _P(0, stdout='{"records":3}')

        monkeypatch.setattr(bgd.subprocess, "run", fake_run)
        mp = tmp_path / "refs" / "manifest.json"
        rc = bgd.main(
            [
                "--fasta",
                str(_REF_FASTA),
                "--datadir",
                str(tmp_path / "gapit"),
                "--manifest",
                str(mp),
            ]
        )
        assert rc == 0
        entry = json.loads(mp.read_text())["databases"][0]
        assert entry["name"] == "gapit:vpara_virulence"
        assert entry["checksum"] == "deadbeef"

    def test_main_build_failure_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bgd.subprocess, "run", lambda *a, **k: _P(1, stderr="boom"))
        assert bgd.main(["--fasta", str(_REF_FASTA), "--datadir", str(tmp_path / "g")]) == 1


class _P:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


class TestDeployEnsuresDb:
    def test_noop_without_packaged_fasta(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(wf_runner.subprocess, "run", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path / "home")
        wf_runner._ensure_gapit_vpara_db(tmp_path / "deployed")
        assert calls == []

    def test_builds_when_fasta_present(self, tmp_path, monkeypatch):
        deployed = tmp_path / "deployed"
        (deployed / "refs").mkdir(parents=True)
        (deployed / "refs" / "vpara_virulence.fasta").write_text(">tdh\nACGT\n")
        (deployed / "scripts").mkdir()
        (deployed / "scripts" / "build_gapit_db.py").write_text("")
        calls = []
        monkeypatch.setattr(
            wf_runner.subprocess, "run", lambda *a, **k: calls.append(a[0]) or _P(0, stdout="ok")
        )
        monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path / "home")
        wf_runner._ensure_gapit_vpara_db(deployed)
        assert len(calls) == 1
        assert "build_gapit_db.py" in " ".join(calls[0])


@pytest.mark.skipif(shutil.which("gapit") is None, reason="gapit not installed")
class TestLiveGapitSmoke:
    def test_build_db_and_screen(self, tmp_path):
        datadir = tmp_path / "gapit"
        mp = tmp_path / "refs" / "manifest.json"
        rc = bgd.main(
            ["--fasta", str(_REF_FASTA), "--datadir", str(datadir), "--manifest", str(mp)]
        )
        assert rc == 0
        assert bgd.db_built(datadir, "vpara_virulence")

        # 以库序列自身作 contigs：三条标记均应检出
        report = vv.run_screen(str(_REF_FASTA), "vpara_virulence", str(datadir))
        out = vv.normalize(report)
        assert out["tdh"] is True and out["trh"] is True and out["tlh"] is True
        assert out["n_hits"] >= 3
        entry = json.loads(mp.read_text())["databases"][0]
        assert entry["name"] == "gapit:vpara_virulence" and entry["checksum"]
