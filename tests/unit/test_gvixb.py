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
from bacmap.interfaces import gvixb as gvixb_service
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
                "nodes": [
                    {
                        "id": 0, "label": "S1 (+1)",
                        "member_count": 2, "members": ["S1", "S2"],
                        "meta": {"country": "CN"},
                        "profile_key": "1|2|3",
                    },
                    {"id": 1, "label": "S2"},
                ],
                "edges": [
                    {"source": 0, "target": 1, "weight": 7, "mismatch_loci": ["adk"]},
                ],
            },
        },
    )
    (root / "cgmlst" / "vpara" / "cgmlst_profiles.tsv").write_text(
        "File\tScheme\tST\tadk\tatpA\nS1\tvpa\t3\t1\t4\nS2\tvpa\t8\t2\t4\n",
        encoding="utf-8",
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
        assert tree.json()["schema"] == "gvixb.phylogeny/v2"
        assert tree.json()["tree"]["newick"] == "(S1:0.1,S2:0.2)root;"
        assert tree.json()["summary"]["n_snp_sites"] == 42
        mst = client.get(f"/api/v1/gvixb/runs/{run.run_id}/mst/vpara")
        assert mst.status_code == 200
        nodes = mst.json()["nodes"]
        assert [(n["id"], n["label"]) for n in nodes] == [("0", "S1 (+1)"), ("1", "S2")]
        # rich gvixb.mst/v1 fields must survive the adapter boundary
        first = nodes[0]
        assert first["member_count"] == 2
        assert [m["id"] for m in first["members"]] == ["S1", "S2"]
        assert first["members"][0]["meta"] == {"scheme": "vpa", "ST": "3"}
        # aggregated node meta uses the representative sample ("S1 (+1)" -> "S1")
        assert first["meta"]["country"] == "CN" and first["meta"]["ST"] == "3"
        # breakdown is derived from member metas when gmlst omits it
        assert first["meta_breakdown"]["ST"] == {"3": 1, "8": 1}
        assert first["meta_breakdown"]["scheme"] == {"vpa": 2}
        assert first["profile"] == ["1", "2", "3"]
        assert nodes[1]["meta"]["ST"] == "8"
        edges = mst.json()["edges"]
        assert [(e["source"], e["target"], e["weight"]) for e in edges] == [("0", "1", 7.0)]
        assert edges[0]["mismatch_loci"] == ["adk"]
        assert mst.json()["loci"] == ["adk", "atpA"]
        assert mst.json()["n_loci"] == 3002

    def test_manifest_lists_only_actual_artifacts(self, seeded):
        _, client, run, _ = seeded
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/manifest").json()
        assert {view["id"] for view in data["views"]} == {
            "genome:S1", "circle:S1", "tree:snp:vpara", "mst:vpara"
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

    def test_bakta_renamed_contigs_keep_gc_track(self, seeded):
        """Bakta 把 contig00001 改名为 contig_1 且无 replicons 表时，按长度回填 GC 轨道。"""
        engine, _, run, root = seeded
        sample = root / "S1"
        (sample / "annotation" / "bakta" / "S1.replicons.tsv").unlink()
        (sample / "assembly" / "S1.fasta").write_text(
            ">contig00001 len=120\n" + "ACGT" * 30 + "\n", encoding="utf-8"
        )
        (sample / "annotation" / "bakta" / "S1.gff3").write_text(
            "##gff-version 3\n"
            "##sequence-region contig_1 1 120\n"
            "contig_1\tBakta\tCDS\t2\t20\t.\t+\t0\tID=cds:1;locus_tag=LOC1;product=test\n",
            encoding="utf-8",
        )
        for name in ("abricate_card.tsv", "abricate_vfdb.tsv"):
            path = sample / "amr" / name
            path.write_text(path.read_text(encoding="utf-8").replace("\tc1\t", "\tcontig00001\t"),
                            encoding="utf-8")
        payload = gvixb_service.annotated_genome_payload(engine, run.run_id, "S1")
        replicon = payload.replicons[0]
        assert replicon.id == "contig_1"
        assert replicon.gc is not None
        assert replicon.track is not None and replicon.track.pos

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


def test_gvixb_demo_route_and_no_cache(seeded):
    _, client, _, _ = seeded
    assert client.get("/gvixb/demo/").status_code == 200
    assert "GVIXB" in client.get("/gvixb/demo/").text
    asset = client.get("/static/gvixb/views/circular-annotation-view.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "no-cache, must-revalidate"


class TestSnpTreeV2:
    def _v2_snp(self, root: Path, newick: str | None = None, **overrides) -> None:
        summary = {
            "tree_newick": newick or "((S1:0.1,S2:0.2)95/98:0.05,S3:0.3);",
            "samples": ["S1", "S2", "S3"],
            "n_snp_sites": 42,
            "group": "vpara",
            "organism": "Vibrio parahaemolyticus",
            "missing_rate": 0.01,
            "pairwise_distances": {"S1|S2": 4, "S3|S1": 9},
        }
        summary.update(overrides)
        _write_json(root / "snp" / "vpara" / "snp_summary.json", summary)

    def test_snp_tree_v2_shape_support_and_summary(self, seeded):
        _, client, run, root = seeded
        self._v2_snp(root)
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara").json()
        assert data["schema"] == "gvixb.phylogeny/v2" and data["demo"] is False
        assert data["title"] == "Vibrio parahaemolyticus 核心 SNP 树 · vpara"
        assert data["source"].startswith(f"bacmap 运行 {run.run_id}")
        tree = data["tree"]
        assert tree["kind"] == "inferred" and tree["root"] == {"status": "unrooted"}
        assert tree["method"].endswith("SH-aLRT/UFBoot ×1000")
        assert tree["support"] == {"labels": ["SH-aLRT", "UFBoot"], "scale": 100}
        assert tree["branch_length"]["unit"] == "substitutions_per_site"
        assert tree["branch_length"]["alignment_sites"] == 42
        assert data["summary"]["n_samples"] == 3
        assert data["summary"]["missing_rate"] == 0.01

    def test_snp_tree_without_support_labels_omits_support(self, seeded):
        _, client, run, root = seeded
        self._v2_snp(root, newick="(S1:0.1,(S2:0.2,S3:0.1):0.05);")
        tree = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara").json()["tree"]
        assert "support" not in tree
        assert "SH-aLRT" not in tree["method"]

    def test_snp_sample_st_serotype_and_missing_values(self, seeded):
        _, client, run, root = seeded
        self._v2_snp(root)
        _write_json(
            root / "S1" / "report" / "S1_summary.json",
            {"steps": {"mlst": {"st": "3"}, "serotype": {"value": "O3:K6"}}},
        )
        _write_json(
            root / "S2" / "report" / "S2_summary.json",
            {"steps": {"mlst": {"st": "N/A"}, "serotype": {"value": "-"}}},
        )
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara").json()
        assert data["metadata"]["S1"] == {"ST": "3", "serotype": "O3:K6"}
        assert "S2" not in data["metadata"] and "S3" not in data["metadata"]
        field_keys = [f["key"] for f in data["fields"]]
        assert "ST" in field_keys and "serotype" in field_keys

    def test_strain_metadata_whitelist_isolate_mapping_and_dates(self, seeded):
        engine, client, run, root = seeded
        self._v2_snp(root)
        home = Path(engine.home)
        (home / "workflows" / "bacmap" / "config" / "samples.tsv").write_text(
            "sample\tisolate\nS1\tISO1\nS2\tISO2\n", encoding="utf-8"
        )
        from bacmap.store.strain_metadata import StrainMetadataService

        with StrainMetadataService(home / "data" / "bacmap.sqlite") as svc:
            svc.upsert("ISO1", {
                "isolation_date": "2024/03/05", "collection_date": "2024-02",
                "province": "上海", "city": "黄浦", "district": "外滩",
                "sample_source": "食品", "outbreak_id": "OB7",
                "patient_name": "张三", "patient_phone": "13800000000",
                "onset_date": "2024-03-01", "hospital": "某医院",
                "cluster_note": "note", "submit_date": "2024-04-01",
            })
            svc.upsert("ISO2", {"province": "江苏"})
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara").json()
        s1 = data["metadata"]["S1"]
        assert s1["isolation_date"] == "2024-03-05"
        assert s1["collection_date"] == "2024-02"
        assert s1["province"] == "上海" and s1["outbreak_id"] == "OB7"
        assert data["metadata"]["S2"] == {"province": "江苏"}
        text = json.dumps(data, ensure_ascii=False)
        for forbidden in (
            "patient_name", "patient_phone", "onset_date", "hospital",
            "cluster_note", "submit_date", "张三", "13800000000", "某医院", "extra",
        ):
            assert forbidden not in text
        fields = {f["key"]: f for f in data["fields"]}
        assert fields["isolation_date"]["role"] == "time"
        assert fields["isolation_date"]["primary"] is True
        assert "primary" not in fields["collection_date"]
        assert fields["city"] == {
            "key": "city", "type": "categorical", "label": "城市",
            "role": "place", "parent": "province",
        }
        assert fields["district"]["parent"] == "city"
        assert fields["outbreak_id"]["role"] == "cluster"

    def test_fields_only_when_present_and_primary_fallback(self, seeded):
        engine, client, run, root = seeded
        self._v2_snp(root)
        home = Path(engine.home)
        (home / "workflows" / "bacmap" / "config" / "samples.tsv").write_text(
            "sample\tisolate\nS1\tISO1\n", encoding="utf-8"
        )
        from bacmap.store.strain_metadata import StrainMetadataService

        with StrainMetadataService(home / "data" / "bacmap.sqlite") as svc:
            # city 无 province：parent 不得悬挂；collection_date 单独存在时 primary。
            svc.upsert("ISO1", {
                "city": "黄浦", "district": "外滩",
                "collection_date": "2023-12", "isolation_date": "nope",
            })
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara").json()
        fields = {f["key"]: f for f in data["fields"]}
        assert "isolation_date" not in fields and "province" not in fields
        assert "parent" not in fields["city"]
        assert fields["district"]["parent"] == "city"
        assert fields["collection_date"]["primary"] is True
        assert "isolation_date" not in data["metadata"]["S1"]

    def test_snp_matrices_null_and_zero_rows(self, seeded):
        _, client, run, root = seeded
        self._v2_snp(root)
        _write_json(
            root / "S1" / "gspec" / "card.json",
            {"files": [{"file": "S1", "hits": [
                {"gene": "blaA", "resistance": "beta-lactam;other"},
                {"gene": "tetM", "resistance": "tetracycline"},
            ]}]},
        )
        _write_json(
            root / "S2" / "gspec" / "card.json",
            {"files": [{"file": "S2", "hits": [{"gene": "blaA"}]}]},
        )
        data = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara").json()
        amr = next(m for m in data["matrices"] if m["id"] == "amr")
        assert amr["label"] == "AMR 基因（CARD）"
        assert [c["id"] for c in amr["columns"]] == ["blaA", "tetM"]
        assert amr["columns"][0]["group"] == "beta-lactam"
        assert "group" not in amr["columns"][1] or amr["columns"][1]["group"] == "tetracycline"
        assert amr["rows"]["S1"] == [1, 1]
        assert amr["rows"]["S2"] == [1, 0]
        assert amr["rows"]["S3"] == [None, None]
        assert all(m["id"] != "plasmid" for m in data["matrices"])

    def test_snp_distances_triangle_order_and_nulls(self, seeded):
        _, client, run, root = seeded
        self._v2_snp(root)
        distances = client.get(
            f"/api/v1/gvixb/runs/{run.run_id}/tree/snp/vpara"
        ).json()["distances"]
        assert distances["unit"] == "snp" and distances["samples"] == ["S1", "S2", "S3"]
        # 上三角 i<j：(S1,S2)=4、(S1,S3)=9（反向键 "S3|S1" 命中）、(S2,S3) 缺失 → null
        assert distances["values"] == [4.0, 9.0, None]

    def test_cgmlst_tree_withdrawn(self, seeded):
        _, client, run, _ = seeded
        views = client.get(f"/api/v1/gvixb/runs/{run.run_id}/manifest").json()["views"]
        assert not any(view["id"].startswith("tree:cgmlst") for view in views)
        api = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/cgmlst/vpara")
        assert api.status_code == 410
        assert f"/api/v1/gvixb/runs/{run.run_id}/mst/vpara" in api.json()["detail"]
        page = client.get(
            f"/gvixb/runs/{run.run_id}/tree/cgmlst/vpara", follow_redirects=False
        )
        assert page.status_code == 307
        assert page.headers["location"] == f"/gvixb/runs/{run.run_id}/mst/vpara"
        bad = client.get(f"/api/v1/gvixb/runs/{run.run_id}/tree/cgmlst/bad%2Fpath")
        assert bad.status_code in (400, 404, 410)


def test_strain_meta_whitelist_disjoint_from_d4():
    from bacmap.interfaces.gvixb import _TREE_STRAIN_META_KEYS
    from bacmap.tasks.gates import _D4_KEYS

    assert not (_TREE_STRAIN_META_KEYS & _D4_KEYS)
