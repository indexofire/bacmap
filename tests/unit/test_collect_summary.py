"""collect_summary.py（Snakemake 脚本）关键字段测试——以桩 snakemake 全局 exec。

回归：gside 标记名小写（"ipah"），旧实现按 "ipaH" 精确比较 → ipaH 恒为 negative。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

_SCRIPT = Path(__file__).resolve().parents[2] / "src/bacmap/workflow/scripts/collect_summary.py"


def _run(tmp_path: Path, species_id: dict, omit: set[str] | None = None) -> dict:
    rep = tmp_path / "results" / "S1" / "report"
    rep.mkdir(parents=True, exist_ok=True)
    sid = tmp_path / "species.json"
    sid.write_text(json.dumps(species_id))
    out = rep / "S1_summary.json"

    missing = str(tmp_path / "missing")
    attrs = {
        "qc_json": missing,
        "assembly_stats": missing,
        "mlst": missing,
        "sistr": missing,
        "vfdb": missing,
        "card": missing,
        "amrfinderplus": missing,
        "plasmidfinder": missing,
        "ectyper": missing,
        "pathotype": missing,
        "gapit_typing": missing,
        "shigella_serotype": missing,
        "vpa_serotype": missing,
        "vpa_virulence": missing,
        "annotation": missing,
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
        omit={"sistr", "pathotype", "shigella_serotype", "vpa_serotype", "vpa_virulence"},
    )
    assert summary["steps"]["serotype"]["sistr_status"] == "not_applicable"
    assert "vpa_serotype" not in summary["steps"]
    assert "vpa_virulence" not in summary["steps"]
    # DEC 致病型仍适用（ECO 有 ecoli_dec）
    # 本桩未提供 pathotype 文件 → 该子步骤不适用
    assert summary["steps"]["dec"]["pathotype_status"] == "not_applicable"


def test_non_dec_species_marks_dec_not_applicable(tmp_path):
    summary = _run(
        tmp_path,
        {"verdict": "Salmonella", "detected_markers": []},
        omit={"ectyper", "pathotype", "shigella_serotype"},
    )
    assert summary["steps"]["dec"]["status"] == "not_applicable"
    assert summary["steps"]["serotype"]["sistr"] == "N/A"
