"""部署本地覆盖配置（v1.10.26）。

`deploy()` 在包内容变化时会 rmtree 部署目录后重新拷贝模板——历史上只保留
`config/samples.tsv` 与 `.snakemake`，对 `config/config.yaml` 的部署侧修改
（Bakta/eggNOG 库路径）会被静默清空，下一次注释就以 "database not found" 失败。

现在 `config/config.local.yaml` 进入保留清单，并由 Snakefile 作为第二个
configfile 叠加（Snakemake 深合并，后者覆盖前者）。
"""

from __future__ import annotations

from pathlib import Path

from bacmap.workflow import runner as wf_runner


def _deploy_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(wf_runner, "WORKFLOWS_DIR", tmp_path / "workflows")
    monkeypatch.setattr(wf_runner, "BACMAP_HOME", tmp_path)
    wf_runner.deploy()
    return tmp_path / "workflows" / "bacmap"


def test_local_config_survives_redeploy(tmp_path, monkeypatch):
    deployed = _deploy_home(tmp_path, monkeypatch)
    local = deployed / "config" / "config.local.yaml"
    payload = 'tools:\n  annotation:\n    bakta:\n      db: "/data/db6"\n'
    local.write_text(payload)

    wf_runner.deploy(force=True)

    assert local.is_file()
    assert local.read_text() == payload
    # 模板默认值仍来自 config.yaml（本地覆盖不在模板里）
    assert 'db: ""' in (deployed / "config" / "config.yaml").read_text()


def test_template_ships_empty_local_config(tmp_path, monkeypatch):
    """模板必须自带 config.local.yaml：Snakefile 无条件声明它，缺失会被 Snakemake 判错。"""
    deployed = _deploy_home(tmp_path, monkeypatch)
    local = deployed / "config" / "config.local.yaml"
    assert local.is_file()
    body = [ln for ln in local.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert body == ["{}"]


def test_snakefile_loads_local_config_after_template(tmp_path, monkeypatch):
    deployed = _deploy_home(tmp_path, monkeypatch)
    lines = (deployed / "Snakefile").read_text().splitlines()
    directive = [
        i for i, line in enumerate(lines) if line.startswith("configfile:")
    ]
    assert len(directive) == 2, directive
    template_line, local_line = directive
    assert "config.yaml" in lines[template_line]
    assert "config.local.yaml" in lines[local_line]
    assert template_line < local_line, "本地覆盖必须在模板之后加载（后者覆盖前者）"
