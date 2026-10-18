"""工作流脚本审计修复的回归测试（gmlst 外壳 / pathotype / SNP 过滤 / 阈值映射）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_wf_{name}", _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestMstToNewickEnvelope:
    def test_wrapped_gmlst_payload(self):
        mod = _load("mst_to_newick")
        payload = {
            "schema_version": "gmlst-visual-mst-v1",
            "data": {
                "nodes": [{"id": 0, "label": "A"}, {"id": 1, "label": "B"}],
                "edges": [{"source": 0, "target": 1, "weight": 3}],
            },
        }
        newick = mod.to_newick(payload)
        assert newick.endswith(";")
        assert "A" in newick and "B" in newick and ":3" in newick

    def test_flat_payload_still_works(self):
        mod = _load("mst_to_newick")
        payload = {
            "nodes": [{"id": 0, "label": "A"}, {"id": 1, "label": "B"}],
            "edges": [{"source": 0, "target": 1, "weight": 1}],
        }
        assert "A" in mod.to_newick(payload)


class TestGenerateCgmlstSummary:
    def _inputs(self, tmp_path: Path, matrix_payload: dict):
        tree = tmp_path / "core.treefile"
        tree.write_text("(A:1,B:1);")
        matrix = tmp_path / "distance_matrix.json"
        matrix.write_text(json.dumps(matrix_payload))
        profiles = tmp_path / "profiles.tsv"
        profiles.write_text("File\tScheme\tST\tL1\tL2\nA\ts1\t-\t1\t1\nB\ts1\t-\t1\t2\n")
        return tree, matrix, profiles

    def _run(self, tmp_path, monkeypatch, group="salmonella", config_file=None):
        mod = _load("generate_cgmlst_summary")
        matrix_payload = {
            "schema_version": "gmlst-visual-matrix-v1",
            "data": {
                "labels": ["A", "B"],
                "matrix": [[0, 4], [4, 0]],
            },
        }
        tree, matrix, profiles = self._inputs(tmp_path, matrix_payload)
        out = tmp_path / "cgmlst_summary.json"
        argv = [
            "generate_cgmlst_summary.py",
            str(tree),
            str(matrix),
            str(profiles),
            str(out),
            "--group",
            group,
        ]
        if config_file:
            argv += ["--config-file", str(config_file)]
        monkeypatch.setattr("sys.argv", argv)
        assert mod.main() == 0
        return json.loads(out.read_text())

    def test_wrapped_matrix_produces_samples_and_distances(self, tmp_path, monkeypatch):
        summary = self._run(tmp_path, monkeypatch)
        assert summary["samples"] == ["A", "B"]
        assert summary["n_samples"] == 2
        assert summary["allele_distances"]["A|B"] == 4

    def test_vpara_group_uses_code_threshold_key(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "cgmlst:\n  thresholds:\n    VPA:\n"
            "      outbreak_allele_dist: null\n      related_allele_dist: null\n"
        )
        summary = self._run(tmp_path, monkeypatch, group="vpara", config_file=cfg)
        assert summary["thresholds_applied"] == {
            "outbreak_allele_dist": None,
            "related_allele_dist": None,
        }


class TestGenerateSnpMatrix:
    def _vcf(self, tmp_path: Path, quals: list[str]) -> Path:
        lines = [
            "##fileformat=VCFv4.2",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1",
        ]
        for i, q in enumerate(quals, start=1):
            lines.append(f"chr\t{i}\t.\tA\tT\t{q}\t.\t.\tGT\t1")
        vcf = tmp_path / "in.vcf"
        vcf.write_text("\n".join(lines) + "\n")
        return vcf

    def test_min_qual_filters_variants(self, tmp_path):
        mod = _load("generate_snp_matrix")
        vcf = self._vcf(tmp_path, ["10", "50"])
        _, variants_low = mod.read_vcf(str(vcf), 5.0)
        _, variants_high = mod.read_vcf(str(vcf), 30.0)
        assert len(variants_low) == 2
        assert len(variants_high) == 1
