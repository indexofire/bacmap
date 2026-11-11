"""gvixb：结果启动、run 隔离、真实产物适配与 Web 安全边界。"""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store import runs as runs_store
from bacmap.store.genome_object_service import GenomeObject, GenomeObjectService, ObjectType

_TSV_HEADER = (
    "#FILE\tSEQUENCE\tSTART\tEND\tSTRAND\tGENE\tCOVERAGE\tCOVERAGE_MAP\tGAPS\t"
    "%COVERAGE\t%IDENTITY\tDATABASE\tACCESSION\tPRODUCT\tRESISTANCE\n"
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _seed_result(home: Path, task_id: str = "t1", run_id: str | None = None):
    cfg = home / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text("seeds:\n  iqtree: 1\n", encoding="utf-8")
    run = runs_store.create_run(
        workflow="bacmap", workflow_dir=home / "workflows" / "bacmap",
        strain_ids=["S1", "S2"], input_files=[], db_path=home / "runs.sqlite",
        task_id=task_id,
    )
    if run_id is not None:
        run.run_id = run_id
    runs_store.finalize_run(run.run_id, home / "runs.sqlite", home / "runs")
    engine = eng.DbosTaskEngine(home)
    with engine._conn() as conn:
        conn.execute(
            "INSERT INTO tasks (task_id,task_type,state,params_json,submitted_by,created_at,"
            "updated_at,workflow_id,current_step) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, "analyze", "succeeded", "{}", "test", "2026-01-01", "2026-01-01", "", "done"),
        )
    root = home / "results" / "runs" / task_id
    # 现行布局：assembly/注释产物按菌株名命名（v1.10.22 起）；AMR 筛查用旧
    # abricate TSV 名，覆盖 load 布局回退分支（新目录为 gspec/card.json）。
    assembly = root / "S1" / "assembly" / "S1.fasta"
    assembly.parent.mkdir(parents=True)
    assembly.write_text(">c1 description\n" + "ACGT" * 30 + "\n>c2\n" + "GGCC" * 15 + "\n")
    _write_json(
        root / "S1" / "report" / "S1_summary.json",
        {"sample": "S1", "steps": {"species": {"verdict": {"species": "Vibrio_parahaemolyticus"}}}},
    )
    _write_json(
        root / "S1" / "annotation" / "annotation.json",
        {"status": "pending_external_tool", "total_CDS": 0},
    )
    hit = (
        "contigs.fasta\tc1\t2\t20\t+\tblaTEST\t1\t=\t0\t100.0\t99.5\t"
        "card\tacc\ttest beta-lactamase\tbeta-lactam\n"
    )
    for filename, gene_kind in (("abricate_card.tsv", "card"), ("abricate_vfdb.tsv", "vfdb")):
        path = root / "S1" / "amr" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_TSV_HEADER + (hit if gene_kind == "card" else ""), encoding="utf-8")
    bakta = root / "S1" / "annotation" / "bakta"
    bakta.mkdir(parents=True, exist_ok=True)
    (bakta / "S1.gff3").write_text(
        "##gff-version 3\n"
        "##sequence-region c1 1 120\n"
        "c1\tBakta\tCDS\t2\t20\t.\t+\t0\tID=cds:1;locus_tag=LOC1;protein_id=PROT1;gene=blaTest;product=test beta-lactamase\n"
        "c1\tBakta\ttRNA\t40\t60\t.\t-\t0\tID=trna:1;locus_tag=LOC2;product=tRNA-Ala\n",
        encoding="utf-8",
    )
    (bakta / "S1.replicons.tsv").write_text("c1\t-\tchromosome\tcircular\tchromosome\n", encoding="utf-8")
    eggnog = root / "S1" / "annotation" / "eggnog" / "S1.emapper.annotations"
    eggnog.parent.mkdir(parents=True, exist_ok=True)
    eggnog.write_text(
        "#query\tseed_ortholog\tevalue\tscore\teggNOG_OGs\ttax_ceiling\tCOG_category\tPreferred_name\tGOs\tEC\tKEGG_ko\tKEGG_Pathway\tPFAMs\n"
        "PROT1\tseed\t1e-20\t300\tENOG503ID@bact\tBacteria\tEG\tblaTest\tGO:0001,GO:0002\t3.1.1.1\tK01212\tpath:map1\tBeta_lactamase\n"
        "UNKNOWN\tseed\t1e-5\t80\tENOG503X@bact\tBacteria\tS\t-\t-\t-\t-\t-\t-\n",
        encoding="utf-8",
    )

    _write_json(
        root / "snp" / "vpara" / "snp_summary.json",
        {
            "tree_newick": "(S1:0.1,S2:0.2)root;", "samples": ["S1", "S2"],
            "n_snp_sites": 42, "group": "vpara", "organism": "Vibrio parahaemolyticus",
        },
    )
    _write_json(
        root / "cgmlst" / "vpara" / "cgmlst_summary.json",
        {
            "tree_newick": "(S1:1,S2:2)root;", "samples": ["S1", "S2"],
            "n_loci": 3002, "scheme": "vpa", "group": "vpara",
        },
    )
    _write_json(
        root / "cgmlst" / "vpara" / "mst_payload.json",
        {
            "schema_version": "gmlst-visual-mst-v1",
            "data": {
                "nodes": [{"id": 0, "label": "S1"}, {"id": 1, "label": "S2"}],
                "edges": [{"source": 0, "target": 1, "weight": 7}],
            },
        },
    )
    return engine, run, root


@pytest.fixture
def seeded(tmp_path: Path):
    engine, run, root = _seed_result(tmp_path)
    yield engine, TestClient(create_app(engine)), run, root
    eng.shutdown_dbos()


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    """v1.10.24：gvixb 鉴权测试对本地 [debug] enabled 配置免疫（debug 下 Web 免鉴权）。"""
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


class TestGvixbPayloads:
    def test_latest_genome_is_real_assembly_not_orf_inference(self, seeded):
        engine, client, _, _ = seeded
        # The latest alias is a separate, explicitly labelled entry point.
        latest = Path(engine.home) / "results" / "S1"
        latest.mkdir()
        (latest / "assembly").mkdir()
        (latest / "assembly" / "contigs.fasta").write_text(">latest\nACGT\n")
        _write_json(latest / "report" / "S1_summary.json", {"sample": "S1", "steps": {}})
        link = client.get("/api/v1/samples/S1")
        assert link.status_code == 200
        gvixb_links = link.json()["gvixb"]
        assert any(
            view["url"] == "/gvixb/samples/S1/genome"
            and view["label"] == "使用 gvixb 查看 3D 基因组"
            for view in gvixb_links
        )
        response = client.get("/api/v1/gvixb/samples/S1/genome")
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "latest" and data["contigs"][0]["id"] == "latest"
        assert "seq" not in data["contigs"][0] and "sequence" not in data["contigs"][0]

    def test_run_genome_uses_physical_run_not_latest(self, seeded):
        engine, client, run, _ = seeded
        latest = Path(engine.home) / "results" / "S1" / "assembly"
        latest.mkdir(parents=True)
        (latest / "contigs.fasta").write_text(">other-run\nAAAA\n")
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/genome/S1").json()
        assert data["contigs"][0]["id"] == "c1"
        assert data["organism"] == "Vibrio parahaemolyticus"
        assert data["annotation_status"] == "pending_external_tool"
        assert data["total_bp"] == 180
        assert data["features"][0]["gene"] == "blaTEST"
        assert data["features"][0]["start"] == 1 and data["features"][0]["end"] == 20
        assert str(engine.home) not in json.dumps(data)

    def test_tree_and_original_gmlst_mst(self, seeded):
        _, client, run, _ = seeded
        tree = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara")
        assert tree.status_code == 200
        assert tree.json()["newick"] == "(S1:0.1,S2:0.2)root;"
        assert tree.json()["n_snp_sites"] == 42
        mst = client.get(f"/api/v1/gvixb/runs/{run.run_id}/mst/vpara")
        assert mst.status_code == 200
        assert mst.json()["nodes"] == [{"id": "0", "label": "S1"}, {"id": "1", "label": "S2"}]
        assert mst.json()["edges"] == [{"source": "0", "target": "1", "weight": 7.0}]
        assert mst.json()["n_loci"] == 3002

    def test_manifest_lists_only_actual_artifacts(self, seeded):
        _, client, run, _ = seeded
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/manifest").json()
        assert {view["id"] for view in data["views"]} == {
            "genome:S1", "circle:S1", "tree:snp:vpara", "tree:cgmlst:vpara", "mst:vpara"
        }


class TestGvixbAnnotation:
    def test_bakta_and_eggnog_become_circular_payload(self, seeded):
        _, client, run, _ = seeded
        response = client.get(f"/api/v1/gvixb/runs/{run.run_id}/annotated-genome/S1")
        assert response.status_code == 200
        data = response.json()
        assert data["schema"] == "gvixb.annotated-genome/v1"
        assert data["eggnog_available"] is True and data["eggnog_matched"] == 1
        assert data["eggnog_total"] == 2
        replicon = data["replicons"][0]
        assert replicon["topology"] == "circular" and replicon["length"] == 120
        assert replicon["track"]["pos"], "assembly-derived GC track must remain available"
        by_gene = {feature["gene"]: feature for feature in data["features"]}
        assert by_gene["blaTest"]["flag"] == "amr"
        assert by_gene["blaTest"]["category"] == "E"
        assert by_gene["blaTest"]["ec"] == ["3.1.1.1"]
        assert by_gene["blaTest"]["kegg_ko"] == ["K01212"]
        trna = next(feature for feature in data["features"] if feature["product"] == "tRNA-Ala")
        assert trna["category"] == "trna"
        assert "annotation/bakta" not in json.dumps(data) and str(Path.home()) not in json.dumps(data)

    def test_annotation_routes_and_sample_entry(self, seeded):
        engine, client, run, root = seeded
        page = client.get(f"/gvixb/runs/{run.run_id}/annotation/S1")
        assert page.status_code == 200
        assert f"/api/v1/gvixb/runs/{run.run_id}/annotated-genome/S1" in page.text
        latest = Path(engine.home) / "results" / "S1"
        _write_json(latest / "report" / "S1_summary.json", {"sample": "S1", "steps": {}})
        (latest / "assembly").mkdir(parents=True, exist_ok=True)
        (latest / "assembly" / "contigs.fasta").write_text(">c1\nACGT\n")
        shutil.copytree(root / "S1" / "annotation", latest / "annotation")
        sample = client.get("/api/v1/samples/S1")
        assert any(
            view["url"] == "/gvixb/samples/S1/annotation" for view in sample.json()["gvixb"]
        )
        data = client.get("/api/v1/gvixb/samples/S1/annotated-genome")
        assert data.status_code == 200 and data.json()["scope"] == "latest"

    def test_cold_compaction_and_legacy_names(self, seeded):
        """v1.10.20 冷产物压缩（注释目录 .gz）与 v1.10.22 前旧文件名仍可渲染。"""
        _, client, run, root = seeded
        for path in (
            root / "S1" / "annotation" / "bakta" / "S1.gff3",
            root / "S1" / "annotation" / "bakta" / "S1.replicons.tsv",
            root / "S1" / "annotation" / "eggnog" / "S1.emapper.annotations",
        ):
            raw = path.read_bytes()
            path.unlink()
            with gzip.open(str(path) + ".gz", "wb") as dst:
                dst.write(raw)
        response = client.get(f"/api/v1/gvixb/runs/{run.run_id}/annotated-genome/S1")
        assert response.status_code == 200
        assert response.json()["eggnog_available"] is True
        assembly = root / "S1" / "assembly"
        (assembly / "S1.fasta").rename(assembly / "contigs.fasta")
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/genome/S1")
        assert data.status_code == 200
        assert data.json()["contigs"][0]["id"] == "c1"


class TestGvixbPages:
    def test_run_page_and_result_page(self, seeded):
        _, client, run, _ = seeded
        detail = client.get(f"/api/v1/runs/{run.run_id}")
        assert detail.status_code == 200
        assert any(
            view["url"] == f"/gvixb/runs/{run.run_id}/genome/S1"
            for view in detail.json()["gvixb_views"]
        )
        result = client.get(f"/gvixb/runs/{run.run_id}/tree/snp/vpara")
        assert result.status_code == 200
        assert "BACMAP RESULT VISUALIZATION" in result.text
        assert f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara" in result.text
        assert 'type="importmap"' not in result.text
        assert "https://" not in result.text
        assert result.headers["content-security-policy"].startswith("default-src 'self'")
        assert client.get("/static/gvixb/vendor/three.module.js").status_code == 200

    def test_gom_sample_and_cohort_links(self, seeded):
        engine, client, run, _ = seeded
        svc = GenomeObjectService(Path(engine.home) / "gom.sqlite")
        now = datetime.now(UTC)
        for object_id, strain, payload in (
            ("analysis:S1:x", "S1", {"analysis_type": "sample_analysis", "sample_id": "S1", "run_id": run.run_id}),
            ("cohort:vpara-snp:x", "cohort:vpara-snp", {"analysis_type": "snp_cohort", "group": "vpara", "run_id": run.run_id}),
        ):
            svc.create(GenomeObject(
                object_id=object_id, object_type=ObjectType.ANALYSIS, version=1,
                schema_version="1.0.0", created_at=now, created_by="test", payload=payload,
                strain_id=strain, pipeline_version="test-pipeline", tool_versions={"gmlst": "test"},
            ))
        svc.close()
        analysis = client.get("/api/v1/gom/objects/analysis:S1:x")
        assert f"/gvixb/runs/{run.run_id}/genome/S1" in json.dumps(analysis.json()["gvixb_views"])
        cohort = client.get("/api/v1/gom/objects/cohort:vpara-snp:x")
        assert f"/gvixb/runs/{run.run_id}/tree/snp/vpara" in json.dumps(cohort.json()["gvixb_views"])


class TestGvixbBoundaries:
    def test_unknown_run_and_foreign_sample(self, seeded):
        _, client, run, _ = seeded
        assert client.get("/api/v1/gvixb/runs/nope/manifest").status_code == 404
        assert client.get(f"/api/v1/gvixb/runs/{run.run_id}/genome/S3").status_code == 400
        assert client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/../x").status_code in (400, 404)
        assert client.get("/gvixb/samples/../bad/genome").status_code in (400, 404)

    def test_incomplete_task_not_exposed(self, seeded):
        engine, client, run, _ = seeded
        with engine._conn() as conn:
            conn.execute("UPDATE tasks SET state='running' WHERE task_id='t1'")
        response = client.get(f"/api/v1/gvixb/runs/{run.run_id}/manifest")
        assert response.status_code == 409
        detail = client.get(f"/api/v1/runs/{run.run_id}")
        assert detail.status_code == 200
        assert detail.json()["gvixb_views"] == []

    def test_symlink_escape_rejected(self, seeded):
        _, client, run, root = seeded
        outside = root.parent.parent.parent / "outside.json"
        _write_json(outside, {"tree_newick": "(A,B);"})
        tree = root / "snp" / "vpara" / "snp_summary.json"
        tree.unlink()
        tree.symlink_to(outside)
        response = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara")
        assert response.status_code == 400
        assert str(root) not in response.text and str(outside) not in response.text

    def test_authentication_covers_gvixb(self, tmp_path):
        engine, _, _ = _seed_result(tmp_path)
        client = TestClient(create_app(engine, auth_token="secret"))
        assert client.get("/gvixb/samples/S1/genome").status_code == 401
        assert client.get("/api/v1/gvixb/samples/S1/genome").status_code == 401
        assert client.get(
            "/api/v1/gvixb/samples/S1/genome", headers={"Authorization": "Bearer secret"}
        ).status_code == 404  # latest alias not created by this fixture; auth passed
        eng.shutdown_dbos()
