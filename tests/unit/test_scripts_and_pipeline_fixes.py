"""工具/脚本层审计修复的回归测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(_SRC / "bacmap" / "tools" / "_scripts"))


def _summary(sample: str, steps: dict) -> dict:
    return {"sample": sample, "steps": steps}


def _write(results: Path, sample: str, steps: dict) -> None:
    d = results / sample / "report"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sample}_summary.json").write_text(json.dumps(_summary(sample, steps)))


@pytest.fixture
def results(tmp_path, monkeypatch):
    from bacmap.tools import pipeline as tools_pipeline

    r = tmp_path / "results"
    r.mkdir()
    monkeypatch.setattr(tools_pipeline, "_RESULTS_DIR", r)
    monkeypatch.setattr(tools_pipeline, "_run_project_script", lambda *a, **k: "ok")
    return r


class TestGetResultSpeciesKeys:
    def test_real_summary_species_key(self, results):
        from bacmap.tools.pipeline import get_result

        # 真实 summary 用 steps.species.species（非 verdict）
        _write(results, "S1", {"species": {"species": "Salmonella"}})
        out = json.loads(get_result({"sample_id": "S1"}))
        assert out["species_verdict"] == "Salmonella"
        assert out["species_type"] == "Salmonella"

    def test_common_pathogen_species_type(self, results):
        from bacmap.tools.pipeline import get_result

        _write(results, "K1", {"species": {"species": "Klebsiella_pneumoniae"}})
        out = json.loads(get_result({"sample_id": "K1"}))
        assert out["species_type"] == "Klebsiella pneumoniae"

    def test_non_dict_plasmid_tolerated(self, results):
        from bacmap.tools.pipeline import get_result

        _write(results, "P1", {"species": {"species": "Salmonella"}, "plasmid": "N/A"})
        out = json.loads(get_result({"sample_id": "P1"}))
        assert out["plasmid_count"] == 0


class TestReportValidationAndErrors:
    def test_generate_report_rejects_traversal(self, results):
        from bacmap.tools.pipeline import generate_report

        out = json.loads(generate_report({"sample_id": "../../etc/passwd"}))
        assert "invalid sample_id" in out["error"]

    def test_pipeline_surfaces_script_error(self, results, monkeypatch):
        from bacmap.tools import pipeline as p

        monkeypatch.setattr(
            p, "_run_project_script", lambda *a, **k: json.dumps({"error": "boom", "stderr": "x"})
        )
        out = json.loads(p.analyze_pathogen({"sample_id": "S1"}))
        assert out["error"] == "Pipeline failed" and "boom" in out["detail"]


class TestWorkflowDirBase:
    def test_scripts_common_uses_config_dir(self):
        import _common as scripts_common  # noqa: N812

        from bacmap import config

        assert scripts_common.WORKFLOW_DIR == config.DEPLOYED_WORKFLOWS_DIR


class TestRunAnalysisCli:
    def _load(self):
        path = _SRC / "bacmap" / "tools" / "_scripts" / "run_analysis.py"
        spec = importlib.util.spec_from_file_location("run_analysis", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod

    def test_status_with_sample_parses(self, tmp_path, monkeypatch, capsys):
        mod = self._load()
        wf = tmp_path / "wf"
        (wf / "config").mkdir(parents=True)
        (wf / "config" / "samples.tsv").write_text("sample\tspecies\nS1\tSalmonella\n")
        monkeypatch.setattr(mod, "WORKFLOW_DIR", wf)
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(sys, "argv", ["run_analysis.py", "--status", "--sample", "S1"])
        assert mod.main() == 0
        assert "分析状态" in capsys.readouterr().out

    def test_no_action_errors(self, tmp_path, monkeypatch):
        mod = self._load()
        monkeypatch.setattr(sys, "argv", ["run_analysis.py"])
        with pytest.raises(SystemExit):
            mod.main()


class TestCohortTargets:
    """分组目标由 registry 派生 + resolve 双接受（码/名称），并含重组目标。"""

    def _mod(self):
        path = _SRC / "bacmap" / "tools" / "_scripts" / "run_analysis.py"
        spec = importlib.util.spec_from_file_location("run_analysis_targets", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod

    def _samples(self, tmp_path, rows: list[tuple[str, str]]):
        wf = tmp_path / "wf"
        (wf / "config").mkdir(parents=True)
        tsv = wf / "config" / "samples.tsv"
        body = "sample\tspecies\n" + "".join(f"{s}\t{sp}\n" for s, sp in rows)
        tsv.write_text(body)
        return tsv

    def test_codes_accepted(self, tmp_path, monkeypatch):
        mod = self._mod()
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path / "results")
        tsv = self._samples(tmp_path, [("S1", "SAL"), ("S2", "SAL"), ("S3", "ECO")])
        snp = mod._cohort_targets(tsv, "snp")
        assert any(p.endswith("/snp/salmonella/snp_summary.json") for p in snp)
        # ecoli 组只有 1 株（<2）→ 不产目标
        assert not any("/snp/ecoli/" in p for p in snp)
        # salmonella plan.recombination=true → 附带重组目标
        assert any(p.endswith("/snp/salmonella/recombination.json") for p in snp)

    def test_names_dual_accepted(self, tmp_path, monkeypatch):
        mod = self._mod()
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path / "results")
        tsv = self._samples(
            tmp_path, [("S1", "E.coli"), ("S2", "Shigella")]
        )
        cg = mod._cohort_targets(tsv, "cgmlst")
        assert any(p.endswith("/cgmlst/ecoli/cgmlst_summary.json") for p in cg)

    def test_snp_no_longer_points_at_stale_root(self, tmp_path, monkeypatch):
        mod = self._mod()
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path / "results")
        tsv = self._samples(tmp_path, [("S1", "SAL"), ("S2", "SAL")])
        snp = mod._cohort_targets(tsv, "snp")
        assert all("/snp/" in p and p.count("/snp/") == 1 for p in snp)
        assert not any(p.endswith("/snp/snp_summary.json") for p in snp)
