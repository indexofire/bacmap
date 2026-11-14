"""`--cores` 与规则线程解耦（v1.10.27）。

历史行为：`--cores` 与每条规则的 `threads` 都取部署 config 的 `threads`，
所以"少线程多并发"无法表达；174 株批处理时单株 Bakta 12 线程串行 ≈ 16 小时。
现在 `--cores` 优先读部署配置的 `cores`，缺省回退 `threads`（旧行为不变），
并读取 config.local.yaml 的部署本地覆盖（与 Snakefile 双 configfile 一致）。
"""

from __future__ import annotations

from bacmap.tasks.engine.dbos_engine import _deployed_config, _snakemake_cores


def _write(tmp_path, name: str, text: str):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / name).write_text(text, encoding="utf-8")


def test_cores_falls_back_to_threads(tmp_path):
    _write(tmp_path, "config.yaml", "threads: 12\n")
    assert _snakemake_cores(tmp_path, {}) == 12


def test_cores_key_wins_over_threads(tmp_path):
    _write(tmp_path, "config.yaml", "threads: 4\ncores: 12\n")
    assert _snakemake_cores(tmp_path, {}) == 12


def test_local_override_applies(tmp_path):
    _write(tmp_path, "config.yaml", "threads: 12\n")
    _write(tmp_path, "config.local.yaml", "threads: 4\ncores: 12\n")
    assert _deployed_config(tmp_path)["threads"] == 4
    assert _snakemake_cores(tmp_path, {}) == 12


def test_explicit_param_wins(tmp_path):
    _write(tmp_path, "config.yaml", "threads: 12\n")
    assert _snakemake_cores(tmp_path, {"cores": 6}) == 6


def test_unreadable_config_defaults_to_8(tmp_path):
    assert _snakemake_cores(tmp_path, {}) == 8
