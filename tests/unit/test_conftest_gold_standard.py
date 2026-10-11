"""gold standard fixture 跳过语义：数据缺失时 skip 而非 error（fresh clone 可移植性）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_conftest():
    spec = importlib.util.spec_from_file_location(
        "bacmap_test_conftest", Path(__file__).parent.parent / "conftest.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_gold_standard_skips(tmp_path: Path):
    mod = _load_conftest()
    with pytest.raises(pytest.skip.Exception):
        mod._load_gold_standard_csv(tmp_path / "nonexistent.csv")


def test_present_gold_standard_loads(tmp_path: Path):
    mod = _load_conftest()
    csv = tmp_path / "gs.csv"
    csv.write_text("sample,species\nS1,Salmonella\n", encoding="utf-8")
    rows = mod._load_gold_standard_csv(csv)
    assert rows == [{"sample": "S1", "species": "Salmonella"}]
