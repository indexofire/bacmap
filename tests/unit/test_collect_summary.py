"""collect_summary.py（Snakemake 脚本）关键字段测试——以桩 snakemake 全局 exec。

回归：gside 标记名小写（"ipah"），旧实现按 "ipaH" 精确比较 → ipaH 恒为 negative。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

_SCRIPT = Path(__file__).resolve().parents[2] / "src/bacmap/workflow/scripts/collect_summary.py"


def _run(tmp_path: Path, species_id: dict) -> dict:
    rep = tmp_path / "results" / "S1" / "report"
    rep.mkdir(parents=True, exist_ok=True)
    sid = tmp_path / "species.json"
    sid.write_text(json.dumps(species_id))
    out = rep / "S1_summary.json"

    missing = str(tmp_path / "missing")
    nope = SimpleNamespace(
        qc_json=missing,
        assembly_stats=missing,
        mlst=missing,
        sistr=missing,
        vfdb=missing,
        card=missing,
        amrfinderplus=missing,
        plasmidfinder=missing,
        ectyper=missing,
        pathotype=missing,
        shigella_serotype=missing,
        vpa_serotype=missing,
        vpa_virulence=missing,
        annotation=missing,
    )
    nope.species_id = str(sid)
    snakemake = SimpleNamespace(
        wildcards=SimpleNamespace(sample="S1"),
        input=nope,
        output=SimpleNamespace(summary=str(out)),
    )
    src = _SCRIPT.read_text()
    exec(
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
