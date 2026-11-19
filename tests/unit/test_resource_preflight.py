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


# ---- v1.10.39：catalog 有、但本物种没声明的分型方案 ----------------------


def _home_with(tmp_path: Path, rows: str) -> Path:
    home = tmp_path / "home"
    cfg = home / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
        "\tchecksum\tspecimen\n" + rows,
        encoding="utf-8",
    )
    (cfg / "config.yaml").write_text("tools:\n  annotation:\n    enabled: false\n")
    return home


def _catalog() -> dict[str, object]:
    from bacmap.core.tool_selection_validate import GmlstScheme

    def scheme(name: str, organism: str, scheme_type: str = "mlst", loci: int = 7):
        return GmlstScheme(
            name=name, organism=organism, scheme_type=scheme_type,
            n_loci=loci, provider="pubmlst", display_name=name,
        )

    return {
        # 同属的"非本种"方案：organism 同样是 Campylobacter ...，必须被排除。
        "campylobacter_1": scheme("campylobacter_1", "Campylobacter non-jejuni/coli"),
        "campylobacter_10": scheme("campylobacter_10", "Campylobacter jejuni/coli"),
        "campylobacter_11": scheme(
            "campylobacter_11", "Campylobacter jejuni/coli", "cgmlst", 1343
        ),
        "cdifficile_1": scheme("cdifficile_1", "Clostridioides difficile"),
    }


def _resources(home: Path) -> tuple[Path, Path]:
    amr = home / "data" / "db" / "amrfinderplus" / "2026-01-01"
    amr.mkdir(parents=True)
    (amr / "AMR_CDS.fa").write_text(">x\nACGT\n")
    gspec = home / "gspec"
    for name in ("vfdb", "card", "plasmidfinder"):
        (gspec / name).mkdir(parents=True)
        (gspec / name / "records.jsonl").write_text("")
    gmlst = home / "gmlst"
    gmlst.mkdir()
    return gspec, gmlst


def test_undeclared_scheme_becomes_decision_not_failure(tmp_path: Path):
    """CJE 没有任何分型声明：ok 仍为 True，但必须出现在 decisions 里。"""
    home = _home_with(
        tmp_path, "CJE1\tCJE\t\t\t\t/home/cje.fna\tCJE1\tunknown\t\t\n"
    )
    gspec, gmlst = _resources(home)
    report = preflight_resources(
        home, ["CJE1"], annotation=False, config={},
        env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
        gmlst_catalog=_catalog(),  # type: ignore[arg-type]
    )
    assert report.ok
    assert report.missing == ()
    names = [item.name for item in report.decisions]
    assert "gmlst:campylobacter_10" in names
    # cgMLST 也是该物种的可用方案
    assert "gmlst:campylobacter_11" in names
    # non-jejuni/coli 方案不得混进来
    assert "gmlst:campylobacter_1" not in names
    decision = {item.name: item for item in report.decisions}["gmlst:campylobacter_10"]
    assert decision.present is False
    assert decision.install == "gmlst scheme download campylobacter_10"
    assert "not enabled" in report.decision_message()
    # 待决项不是缺失项：不能触发 fail-fast
    assert report.failure_message() == ""


def test_decision_for_c_difficile(tmp_path: Path):
    home = _home_with(
        tmp_path, "CDI1\tCDI\t\t\t\t/home/cdi.fna\tCDI1\tunknown\t\t\n"
    )
    gspec, gmlst = _resources(home)
    report = preflight_resources(
        home, ["CDI1"], annotation=False, config={},
        env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
        gmlst_catalog=_catalog(),  # type: ignore[arg-type]
    )
    assert report.ok
    assert [item.name for item in report.decisions] == ["gmlst:cdifficile_1"]


def test_cached_but_undeclared_says_enable_not_download(tmp_path: Path):
    """下了但没声明 → 仍要报出来，且文案指向 selection 而不是下载。"""
    home = _home_with(
        tmp_path, "CJE1\tCJE\t\t\t\t/home/cje.fna\tCJE1\tunknown\t\t\n"
    )
    gspec, gmlst = _resources(home)
    target = gmlst / "pubmlst" / "campylobacter_10"
    target.mkdir(parents=True)
    (target / ".meta.json").write_text("{}")
    report = preflight_resources(
        home, ["CJE1"], annotation=False, config={},
        env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
        gmlst_catalog=_catalog(),  # type: ignore[arg-type]
    )
    decision = {item.name: item for item in report.decisions}["gmlst:campylobacter_10"]
    assert decision.present is True
    assert "bacmap selection select" in decision.detail


def test_declared_scheme_is_checked_not_decided(tmp_path: Path):
    from bacmap.core.tool_selection import ToolSelection

    home = _home_with(
        tmp_path, "CJE1\tCJE\t\t\t\t/home/cje.fna\tCJE1\tunknown\t\t\n"
    )
    gspec, gmlst = _resources(home)
    target = gmlst / "pubmlst" / "campylobacter_10"
    target.mkdir(parents=True)
    (target / ".meta.json").write_text("{}")
    selection = ToolSelection.model_validate({
        "schema": "bacmap.tool_selection/1",
        "species": {
            "CJE": {
                "gmlst": {
                    "mode": "replace",
                    "modes": ["mlst"],
                    "schemes": {"mlst": "campylobacter_10"},
                }
            }
        },
    })
    report = preflight_resources(
        home, ["CJE1"], annotation=False, config={},
        env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
        selection=selection,
        gmlst_catalog=_catalog(),  # type: ignore[arg-type]
    )
    assert report.ok
    assert "gmlst:campylobacter_10" in {item.name for item in report.checked}
    assert report.decisions == ()


def test_undeclared_decision_carries_samples(tmp_path: Path):
    home = _home_with(
        tmp_path,
        "CJE1\tCJE\t\t\t\t/home/cje1.fna\tCJE1\tunknown\t\t\n"
        "CJE2\tCJE\t\t\t\t/home/cje2.fna\tCJE2\tunknown\t\t\n",
    )
    gspec, gmlst = _resources(home)
    report = preflight_resources(
        home, ["CJE1", "CJE2"], annotation=False, config={},
        env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
        gmlst_catalog=_catalog(),  # type: ignore[arg-type]
    )
    decision = {item.name: item for item in report.decisions}["gmlst:campylobacter_10"]
    assert decision.required_by == ("CJE1", "CJE2")


def test_shared_scheme_reported_once_for_two_species(tmp_path: Path):
    """C. jejuni 与 C. coli 共用 campylobacter_10 → 只报一条，样本合并。"""
    home = _home_with(
        tmp_path,
        "CJE1\tCJE\t\t\t\t/home/cje1.fna\tCJE1\tunknown\t\t\n"
        "CCO1\tCCO\t\t\t\t/home/cco1.fna\tCCO1\tunknown\t\t\n",
    )
    gspec, gmlst = _resources(home)
    report = preflight_resources(
        home, ["CJE1", "CCO1"], annotation=False, config={},
        env={"GSPEC_DATADIR": str(gspec), "GMLST_CACHE_DIR": str(gmlst)},
        gmlst_catalog=_catalog(),  # type: ignore[arg-type]
    )
    names = [item.name for item in report.decisions]
    assert names.count("gmlst:campylobacter_10") == 1
    decision = {item.name: item for item in report.decisions}["gmlst:campylobacter_10"]
    assert decision.required_by == ("CCO1", "CJE1")
    assert "CCO" in decision.detail and "CJE" in decision.detail
