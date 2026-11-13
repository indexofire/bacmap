"""collect_summary.py（Snakemake 脚本）关键字段测试——以桩 snakemake 全局 exec。

回归：gside 标记名小写（"ipah"），旧实现按 "ipaH" 精确比较 → ipaH 恒为 negative。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

_SCRIPT = Path(__file__).resolve().parents[2] / "src/bacmap/workflow/scripts/collect_summary.py"


def _run(
    tmp_path: Path,
    species_id: dict,
    omit: set[str] | None = None,
    gspec_typing: dict | None = None,
    annotation: dict | None = None,
    vfdb_genes: list[str] | None = None,
) -> dict:
    rep = tmp_path / "results" / "S1" / "report"
    rep.mkdir(parents=True, exist_ok=True)
    sid = tmp_path / "species.json"
    sid.write_text(json.dumps(species_id))
    out = rep / "S1_summary.json"
    missing = str(tmp_path / "missing")
    ann_path = tmp_path / "annotation.json"
    if annotation is not None:
        ann_path.write_text(json.dumps(annotation))
    else:
        ann_path = Path(missing)

    # gspec_typing 是常驻输入：缺省给真实形状的空结果（无库命中）。
    if gspec_typing is None:
        gspec_typing = {"status": "empty", "databases": {}}
    gspec_path = str(tmp_path / "gspec_typing.json")
    Path(gspec_path).write_text(json.dumps(gspec_typing), encoding="utf-8")
    vfdb_path = missing
    if vfdb_genes is not None:
        vfdb_path = str(tmp_path / "vfdb.json")
        Path(vfdb_path).write_text(
            json.dumps(
                {
                    "schema": "gspec.screen/1",
                    "files": [
                        {
                            "file": str(tmp_path / "S1.fasta"),
                            "hits": [
                                {"gene": g, "database": "vfdb", "product": f"{g}"}
                                for g in vfdb_genes
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    attrs = {
        "qc_json": missing,
        "assembly_stats": missing,
        "quast": missing,
        "mlst": missing,
        "sistr": missing,
        "vfdb": vfdb_path,
        "card": missing,
        "amrfinderplus": missing,
        "plasmidfinder": missing,
        "pathotype": missing,
        "gspec_typing": gspec_path,
        "annotation": str(ann_path),
        "species_id": str(sid),
    }
    for key in omit or ():
        attrs.pop(key, None)
    nope = SimpleNamespace(**attrs)
    snakemake = SimpleNamespace(
        wildcards=SimpleNamespace(sample="S1"),
        input=nope,
        output=SimpleNamespace(summary=str(out)),
    )
    src = _SCRIPT.read_text()
    exec(  # noqa: S102 — 按运行时契约装载 snakemake 脚本源（测试替身）
        compile(src, str(_SCRIPT), "exec"),
        {"snakemake": snakemake, "__name__": "collect_summary"},
    )
    return json.loads(out.read_text())


def test_lowercase_ipah_marker_is_positive(tmp_path):
    summary = _run(tmp_path, {"verdict": "DEC", "detected_markers": [{"gene": "ipah"}]})
    assert summary["steps"]["dec"]["ipaH"] == "ipaH_positive"


def test_no_marker_is_negative(tmp_path):
    summary = _run(tmp_path, {"verdict": "Salmonella", "detected_markers": []})
    assert summary["steps"]["dec"]["ipaH"] == "ipaH_negative"


def test_string_markers_do_not_crash(tmp_path):
    summary = _run(tmp_path, {"verdict": "DEC", "detected_markers": ["ipah", "uida"]})
    assert summary["steps"]["dec"]["ipaH"] == "ipaH_positive"


def test_non_salmonella_marks_sistr_not_applicable(tmp_path):
    """SISTR 只属沙门菌：ECO 的 report 依赖里没有 sistr 输入。"""
    summary = _run(
        tmp_path,
        {"verdict": "DEC", "detected_markers": [{"gene": "ipah"}]},
        omit={"sistr", "pathotype"},
        # ECO 的 gspec 库清单默认含 ecoh（无 typing scheme → 如实 no_scheme）
        gspec_typing={
            "status": "ran",
            "databases": {
                "ecoh": {
                    "kind": "gene",
                    "status": "no_scheme",
                    "error": "database 'ecoh' carries no typing scheme",
                }
            },
        },
    )
    # v1.10.24：SAL 已迁移到 gspec——不再因无 SISTR 报 not_applicable
    assert "sistr_status" not in summary["steps"]["serotype"] or summary["steps"]["serotype"].get("sistr_status") != "not_applicable"
    assert "vpa_serotype" not in summary["steps"]
    assert "vpa_virulence" not in summary["steps"]
    # DEC 段适用（ecoh 库已跑）；桩未提供 pathotype 文件 → 该子步骤不适用
    assert summary["steps"]["dec"]["ecoh_serotype"] == "N/A"
    assert summary["steps"]["dec"]["pathotype_status"] == "not_applicable"


def test_vpa_ok_populates_serotype_from_gspec(tmp_path):
    summary = _run(
        tmp_path,
        {"verdict": "V_parahaemolyticus"},
        gspec_typing={
            "status": "ran",
            "databases": {
                "vpa_ok": {
                    "kind": "cluster",
                    "status": "ran",
                    "phenotype": "O3:K6",
                    "phenotypes": {
                        "o_group": {"phenotype": "O3", "confidence": "high"},
                        "k_group": {"phenotype": "K6", "confidence": "high"},
                    },
                }
            },
        },
    )
    assert summary["steps"]["vpa_serotype"]["predicted_serotype"] == "O3:K6"
    assert summary["steps"]["vpa_serotype"]["o_locus"] == "O3"
    assert summary["steps"]["vpa_serotype"]["k_locus"] == "K6"
    assert summary["steps"]["vpa_serotype"]["source"] == "gspec:vpa_ok"
    # v1.10.26：O:K 必须同时进入统一入口 steps.serotype（Web/报告/检索读它）
    assert summary["steps"]["serotype"]["value"] == "O3:K6"
    assert summary["steps"]["serotype"]["method"] == "gspec vpa_ok"
    assert summary["steps"]["serotype"]["o_antigen"] == "O3"
    assert summary["steps"]["serotype"]["k_antigen"] == "K6"


def test_vpa_virulence_falls_back_to_vfdb(tmp_path):
    """gspec 目录无 vpa_vf 库时，tdh/tlh/trh 仍应从 VFDB 筛查结果得出。"""
    summary = _run(
        tmp_path,
        {"verdict": "V_parahaemolyticus"},
        gspec_typing={
            "status": "ran",
            "databases": {
                "vpa_vf": {
                    "kind": "gene",
                    "status": "unavailable",
                    "error": "Database vpa_vf is not in datadir",
                }
            },
        },
        vfdb_genes=["tdh", "tlh", "cheW"],
    )
    vpa = summary["steps"]["vpa_virulence"]
    assert vpa["database"] == "vfdb"
    assert vpa["tdh"] is True
    assert vpa["tlh"] is True
    assert vpa["trh"] is False
    assert vpa["n_hits"] == 2


def test_vpa_virulence_absent_when_vfdb_has_no_marker(tmp_path):
    summary = _run(
        tmp_path,
        {"verdict": "V_parahaemolyticus"},
        vfdb_genes=["cheW", "flaA"],
    )
    assert "vpa_virulence" not in summary["steps"]


def test_shigella_serotype_from_gspec_shi_sero(tmp_path):
    summary = _run(
        tmp_path,
        {"verdict": "Shigella", "detected_markers": [{"gene": "ipah"}]},
        omit={"sistr", "pathotype"},
        gspec_typing={
            "status": "ran",
            "databases": {
                "shi_sero": {
                    "kind": "gene",
                    "status": "ran",
                    "schemes": {"serotype": "S. flexneri 3a"},
                    "confidence": "high",
                    "genes": ["Sf_wzx", "gtrX", "Oac", "ipaB"],
                }
            },
        },
    )
    assert summary["steps"]["dec"]["serotype_method"] == "gspec shi_sero"
    assert summary["steps"]["dec"]["primary_serotype"] == "S. flexneri 3a"
    assert summary["steps"]["dec"]["shigella_serotype"] == "S. flexneri 3a"
    assert summary["steps"]["dec"]["shigella_status"] == "ran"
    # 前端/报告统一入口
    assert summary["steps"]["serotype"]["value"] == "S. flexneri 3a"
    assert summary["steps"]["serotype"]["method"] == "gspec shi_sero"


def test_non_dec_species_marks_dec_not_applicable(tmp_path):
    summary = _run(
        tmp_path,
        {"verdict": "Salmonella", "detected_markers": []},
        omit={"ectyper", "pathotype"},
    )
    assert summary["steps"]["dec"]["status"] == "not_applicable"
    assert summary["steps"]["serotype"]["sistr"] == "N/A"


def test_annotation_summary_included(tmp_path):
    annotation = {
        "schema": "bacmap.annotation/1",
        "status": "ok",
        "summary": {
            "total_CDS": 100,
            "annotated_CDS": 80,
            "annotation_rate": 0.8,
            "bakta": {"cds": 100, "rrna": 3, "trna": 20},
            "eggnog": {"queries": 100, "annotated": 75, "cog_category_counts": {"J": 10}},
        },
        "features": [
            {"gene": "gyrA", "product": "DNA gyrase subunit A", "identity": 100, "source": "bakta"},
            {"gene": "S1_0002", "product": "hypothetical protein", "identity": 100, "source": "bakta"},
            {"gene": "S1_0003", "product": "beta-lactamase", "identity": None, "source": "bakta"},
        ],
    }
    summary = _run(tmp_path, {"verdict": "Salmonella"}, annotation=annotation)
    step = summary["steps"]["annotation"]
    assert step["status"] == "ok"
    assert step["total_CDS"] == 100
    assert step["annotation_rate"] == 0.8
    assert step["bakta"]["rrna"] == 3
    assert step["eggnog"]["cog_category_counts"] == {"J": 10}
    assert [g["gene"] for g in step["top_genes"]] == ["gyrA", "S1_0003"]
