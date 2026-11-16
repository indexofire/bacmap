"""数据库/参考基因组预检（v1.10.38）：只检查、不下载，缺库 fail-fast。"""

from __future__ import annotations

from pathlib import Path

from bacmap.core.pipeline.resources import preflight_resources


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    cfg = home / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
        "\tchecksum\tspecimen\n"
        "CPE1\tCPE\t\t\t\t/home/cpe.fna\tCPE1\tunknown\t\t\n",
        encoding="utf-8",
    )
    (cfg / "config.yaml").write_text("tools:\n  annotation:\n    enabled: true\n")
    return home


def _populate(home: Path) -> tuple[Path, Path]:
    amr = home / "data" / "db" / "amrfinderplus" / "2026-01-01"
    amr.mkdir(parents=True)
    (amr / "AMR_CDS.fa").write_text(">x\nACGT\n")
    gspec = home / "gspec"
    for name in ("vfdb", "card", "plasmidfinder"):
        (gspec / name).mkdir(parents=True)
        (gspec / name / "records.jsonl").write_text("")
    gmlst = home / "gmlst"
    for scheme in ("cperfringens_1", "cperfringens_2"):
        target = gmlst / "pubmlst" / scheme
        target.mkdir(parents=True)
        (target / ".meta.json").write_text("{}")
    return gspec, gmlst


def test_preflight_ok_without_annotation(tmp_path: Path):
    home = _home(tmp_path)
    gspec, gmlst = _populate(home)
    report = preflight_resources(
        home, ["CPE1"], annotation=False,
        config={}, env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
    )
    assert report.ok
    assert report.missing == ()
    assert [item.name for item in report.skipped] == ["annotation_databases"]
    names = {item.name for item in report.checked}
    assert "amrfinderplus_db" in names and "gmlst:cperfringens_2" in names
    assert "bakta_db" not in names


def test_preflight_reports_missing_with_install_commands(tmp_path: Path):
    home = _home(tmp_path)
    report = preflight_resources(
        home, ["CPE1"], annotation=True,
        config={}, env={"GSPEC_DATADIR": str(home / "none"), "GMLST_CACHE_DIR": str(home / "none")},
    )
    assert not report.ok
    missing = {item.name: item for item in report.missing}
    assert "bakta_db" in missing and "eggnog_data" in missing
    assert "amrfinderplus_db" in missing
    assert "gspec:vfdb" in missing
    assert "gmlst:cperfringens_2" in missing
    assert "gmlst scheme download cperfringens_2" in missing["gmlst:cperfringens_2"].install
    assert "gspec db fetch -d vfdb" in missing["gspec:vfdb"].install
    assert "missing databases" in report.failure_message()


def test_missing_samples_tsv_is_non_blocking(tmp_path: Path):
    report = preflight_resources(tmp_path / "empty", ["S1"], env={}, config={})
    assert report.ok and "skipped" in report.warning


def test_analyze_params_annotation_flag():
    from bacmap.tasks.params import AnalyzeParams, engine_params

    task = AnalyzeParams(samples=["S1"], annotation=False)
    assert engine_params(task)["annotation"] is False
    assert AnalyzeParams(samples=["S1"]).annotation is True


def test_cli_database_status_json(tmp_path: Path, capsys):
    from bacmap.interfaces.cli import main as cli

    home = _home(tmp_path)
    gspec, gmlst = _populate(home)
    # CLI 读取当前进程环境；用 monkeypatch 会污染其他测试，这里直接传 --home
    # 并通过环境变量临时指向临时资源目录。
    import os
    old = {k: os.environ.get(k) for k in ("GSPEC_DATADIR", "GMLST_CACHE_DIR")}
    os.environ["GSPEC_DATADIR"] = str(gspec)
    os.environ["GMLST_CACHE_DIR"] = str(gmlst)
    try:
        cli.main(["database", "status", "--home", str(home), "--no-annotation", "--json"])
        out = capsys.readouterr().out
        assert '"ok": true' in out
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_analyze_fails_fast_before_snakemake_when_database_missing(tmp_path: Path, monkeypatch):
    import time

    import bacmap.tasks.engine.dbos_engine as eng
    from bacmap.tasks.spec import TaskState, TaskType

    home = _home(tmp_path)
    # 只写 samples.tsv，不创建任何数据库
    monkeypatch.setenv("GMLST_CACHE_DIR", str(home / "no-gmlst"))
    monkeypatch.setenv("GSPEC_DATADIR", str(home / "no-gspec"))
    engine = eng.DbosTaskEngine(home)

    def _must_not_run(_params):
        raise AssertionError("snakemake must not run when preflight fails")

    monkeypatch.setattr(eng, "_run_snakemake", _must_not_run)
    try:
        task_id = engine.submit(TaskType.ANALYZE, {"samples": ["CPE1"]}, "test")
        deadline = time.time() + 30
        while time.time() < deadline:
            status = engine.status(task_id)
            if status.state != TaskState.RUNNING:
                break
            time.sleep(0.1)
        assert status.state == TaskState.FAILED
        assert "数据库预检失败" in (status.message or "")
        assert "gmlst scheme download" in (status.message or "")
    finally:
        eng.shutdown_dbos()
