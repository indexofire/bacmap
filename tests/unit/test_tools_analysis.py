"""Unit tests for bacmap.tools — analysis & high-level handlers.

Covers: analyze_pathogen, get_result, verify_result, generate_report,
list_samples, gene_scan, vpa_serotype, snp_tree, search_samples,
validate_taxonomy, annotate_genome, diagnose_failure.

We patch lazily-imported functions on their source module attributes and
monkeypatch tools.pipeline._RESULTS_DIR / _DEPLOYED_WORKFLOWS_DIR / _run_project_script
and tools.services._GOM_DB / _RESULTS_DIR to point to tmp paths or
canned outputs.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap import tools  # noqa: E402
from bacmap.core.analysis import failure_diagnostics  # noqa: E402
from bacmap.store.genome_object_service import (  # noqa: E402
    GenomeObject,
    GenomeObjectService,
    ObjectType,
)
from bacmap.store.strain_index import StrainGenotypeIndex  # noqa: E402
from bacmap.tools import pipeline as tools_pipeline  # noqa: E402
from bacmap.tools import services as tools_services  # noqa: E402


def _parse(result: str) -> dict:
    return json.loads(result)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_results(tmp_path: Path, monkeypatch) -> Path:
    """Redirect tools.pipeline/tools.services _RESULTS_DIR to a tmp directory."""
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(tools_pipeline, "_RESULTS_DIR", results)
    monkeypatch.setattr(tools_services, "_RESULTS_DIR", results)
    return results


@pytest.fixture
def tmp_project_root(tmp_path: Path, monkeypatch) -> Path:
    """Redirect tools.pipeline._DEPLOYED_WORKFLOWS_DIR to a tmp directory."""
    monkeypatch.setattr(tools_pipeline, "_DEPLOYED_WORKFLOWS_DIR", tmp_path)
    return tmp_path


def _write_summary(results: Path, sample_id: str, steps: dict) -> Path:
    """Write a canned <sid>_summary.json under results/<sid>/report/."""
    report_dir = results / sample_id / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{sample_id}_summary.json"
    path.write_text(json.dumps({"sample_id": sample_id, "steps": steps}))
    return path


def _salmonella_steps() -> dict:
    return {
        "species": {"verdict": "Salmonella", "markers": {"invA": "positive"}},
        "mlst": (
            "FILE\tSCHEME\tST\taroC\tdnaN\themD\thisD\tpurE\tsucA\tthrA\n"
            "contigs\tsalmonella_2\t19\t2\t7\t12\t9\t5\t9\t3"
        ),
        "serotype": {"sistr": "Typhimurium", "serogroup": "B"},
        "amr": {
            "abricate_card": [
                {"GENE": "blaCTX-M-15", "%IDENTITY": "99.5"},
                {"GENE": "tet(A)", "%IDENTITY": "98.0"},
            ],
            "abricate_vfdb": [{"GENE": "stfimA"}],
        },
        "plasmid": {"plasmidfinder": [{"GENE": "IncFIB"}]},
        "dec": {},
    }


# ===========================================================================
# analyze_pathogen
# ===========================================================================


class TestAnalyzePathogen:
    def test_returns_summary_when_present(self, tmp_results, monkeypatch):
        _write_summary(tmp_results, "SAM-001", _salmonella_steps())
        captured = {}

        def fake_script(script, args, timeout=3600):
            captured.update(script=script, args=args)
            return "ok"

        monkeypatch.setattr(tools_pipeline, "_run_project_script", fake_script)

        r = _parse(tools.analyze_pathogen({"sample_id": "SAM-001", "cores": 4}))
        assert "Salmonella" in r["steps"]["species"]["verdict"]
        assert captured["script"] == "run_analysis.py"
        assert "--sample" in captured["args"]
        assert "SAM-001" in captured["args"]
        assert "4" in captured["args"]

    def test_summary_missing_after_run(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_pipeline, "_run_project_script", lambda *a, **k: "ok")
        r = _parse(tools.analyze_pathogen({"sample_id": "NO-SUCH"}))
        assert "error" in r
        assert "summary not found" in r["error"]


# ===========================================================================
# get_result
# ===========================================================================


class TestGetResult:
    def test_no_results_for_unknown_sample(self, tmp_results):
        r = _parse(tools.get_result({"sample_id": "MISSING"}))
        assert "error" in r
        assert "No results" in r["error"]

    def test_salmonella_branch(self, tmp_results):
        _write_summary(tmp_results, "SAM-SAL", _salmonella_steps())
        r = _parse(tools.get_result({"sample_id": "SAM-SAL"}))
        assert r["species_type"] == "Salmonella"
        assert r["species_verdict"] == "Salmonella"
        assert r["mlst_st"] == "19"
        assert r["serotype"] == "Typhimurium"
        assert r["amr_genes_count"] == 2
        assert r["virulence_genes_count"] == 1
        assert r["plasmid_count"] == 1
        assert r["ipaH"] == "N/A"

    def test_shigella_branch_ipah_positive(self, tmp_results):
        steps = _salmonella_steps()
        steps["species"] = {"verdict": "Shigella"}
        steps["dec"] = {"ipaH": "positive", "pathotype": "EIEC"}
        _write_summary(tmp_results, "SAM-SHI", steps)
        r = _parse(tools.get_result({"sample_id": "SAM-SHI"}))
        assert r["species_type"] == "Shigella/EIEC"

    def test_not_salmonella_branch(self, tmp_results):
        steps = _salmonella_steps()
        steps["species"] = {"verdict": "not_Salmonella (DEC)"}
        _write_summary(tmp_results, "SAM-DEC", steps)
        r = _parse(tools.get_result({"sample_id": "SAM-DEC"}))
        assert r["species_type"] == "E. coli/DEC"

    def test_unknown_species_default(self, tmp_results):
        steps = _salmonella_steps()
        steps["species"] = {"verdict": "Vibrio"}
        _write_summary(tmp_results, "SAM-VIB", steps)
        r = _parse(tools.get_result({"sample_id": "SAM-VIB"}))
        assert r["species_type"] == "unknown"

    def test_pathotype_extraction(self, tmp_results):
        steps = _salmonella_steps()
        steps["dec"] = {
            "ipaH": "negative",
            "pathotype": "header_line\nEHEC\tstx1,stx2",
        }
        _write_summary(tmp_results, "SAM-DEC2", steps)
        r = _parse(tools.get_result({"sample_id": "SAM-DEC2"}))
        # pathotype last line, first tab-field
        assert r["pathotype"] == "EHEC"

    def test_empty_mlst(self, tmp_results):
        steps = _salmonella_steps()
        steps["mlst"] = ""
        _write_summary(tmp_results, "SAM-NOST", steps)
        r = _parse(tools.get_result({"sample_id": "SAM-NOST"}))
        assert r["mlst_st"] == "N/A"

    def test_non_dict_steps_handled_gracefully(self, tmp_results):
        # Species verdict as plain string instead of dict.
        steps = {
            "species": "Salmonella",
            "mlst": "",
            "serotype": "Typhimurium",
            "amr": [],
            "dec": "",
        }
        _write_summary(tmp_results, "SAM-ODD", steps)
        r = _parse(tools.get_result({"sample_id": "SAM-ODD"}))
        # verdict fallback path: str(species) = "Salmonella" → still Salmonella
        assert r["species_type"] == "Salmonella"
        assert r["amr_genes_count"] == 0


# ===========================================================================
# verify_result
# ===========================================================================


class TestVerifyResult:
    def test_missing_sample(self, tmp_results):
        r = _parse(tools.verify_result({"sample_id": "NOPE"}))
        assert "error" in r

    def test_salmonella_passes_verification(self, tmp_results):
        _write_summary(tmp_results, "SAM-SAL", _salmonella_steps())
        r = _parse(tools.verify_result({"sample_id": "SAM-SAL"}))
        assert "passed" in r
        assert "checks" in r
        assert isinstance(r["checks"], list)
        # 4 checks: species, mlst, serotype, amr
        names = [c["name"] for c in r["checks"]]
        assert set(names) >= {"species", "mlst", "serotype", "amr"}

    def test_failed_species_check(self, tmp_results):
        steps = _salmonella_steps()
        steps["species"] = {"verdict": "Listeria"}
        _write_summary(tmp_results, "SAM-LIS", steps)
        r = _parse(tools.verify_result({"sample_id": "SAM-LIS"}))
        assert r["passed"] is False
        assert r["failed_count"] >= 1
        species = [c for c in r["checks"] if c["name"] == "species"][0]
        assert species["passed"] is False


# ===========================================================================
# generate_report
# ===========================================================================


class TestGenerateReport:
    def test_returns_existing_report_path(self, tmp_results, monkeypatch):
        sample = "SAM-001"
        report_dir = tmp_results / sample / "report"
        report_dir.mkdir(parents=True)
        html_path = report_dir / f"{sample}_report.html"
        html_path.write_text("<html>ok</html>")
        monkeypatch.setattr(tools_pipeline, "_run_project_script", lambda *a, **k: "ok")
        r = _parse(tools.generate_report({"sample_id": sample}))
        assert r["sample_id"] == sample
        assert r["report_path"] == str(html_path)

    def test_report_generation_failed(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_pipeline, "_run_project_script", lambda *a, **k: "ok")
        r = _parse(tools.generate_report({"sample_id": "NOPE"}))
        assert "error" in r
        assert "Report generation failed" in r["error"]


# ===========================================================================
# list_samples
# ===========================================================================


class TestListSamples:
    def _make_samples_tsv(self, project_root: Path, rows: list[tuple[str, str]]):
        cfg = project_root / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        tsv = cfg / "samples.tsv"
        lines = ["sample\tspecies"] + [f"{s}\t{sp}" for s, sp in rows]
        tsv.write_text("\n".join(lines))
        return tsv

    def test_samples_tsv_missing(self, tmp_project_root):
        r = _parse(tools.list_samples({}))
        assert "samples.tsv not found" in r["error"]

    def test_all_three_statuses(self, tmp_project_root, tmp_results):
        self._make_samples_tsv(
            tmp_project_root,
            [
                ("SAM-DONE", "Salmonella"),
                ("SAM-PROG", "DEC"),
                ("SAM-NEW", "Shigella"),
            ],
        )
        # SAM-DONE has summary.json → completed
        _write_summary(tmp_results, "SAM-DONE", _salmonella_steps())
        # SAM-PROG has contigs.fasta but no summary → in-progress
        asm_dir = tmp_results / "SAM-PROG" / "assembly"
        asm_dir.mkdir(parents=True)
        (asm_dir / "contigs.fasta").write_text(">c\nACGT\n")
        # SAM-NEW has nothing → not-started

        r = _parse(tools.list_samples({}))
        by_id = {s["sample_id"]: s for s in r["samples"]}
        assert by_id["SAM-DONE"]["status"] == "completed"
        assert by_id["SAM-PROG"]["status"] == "in-progress"
        assert by_id["SAM-NEW"]["status"] == "not-started"
        assert by_id["SAM-DONE"]["species"] == "Salmonella"


# ===========================================================================
# gene_scan
# ===========================================================================


class TestGeneScan:
    def test_contigs_not_found(self):
        r = _parse(tools.gene_scan({"contigs_path": "/no/such.fa"}))
        assert "Contigs not found" in r["error"]

    def test_single_db_happy(self, tmp_path, monkeypatch):
        contigs = tmp_path / "contigs.fa"
        contigs.write_text(">c\nACGT\n")
        tsv = (
            "#FILE\tSEQUENCE\tSTART\tEND\tSTRAND\tGENE\tCOVERAGE\tCOVERAGE_MAP\tGAPS"
            "\t%COVERAGE\t%IDENTITY\tDATABASE\tACCESSION\tPRODUCT\tRESISTANCE\n"
            "c.fa\tcontig1\t1\t100\t+\tblaCTX-M-15\t1-100/100\t====\t0/0\t100.00"
            "\t99.50\tcard\tX1\tbeta-lactamase\tcephalosporin\n"
        )

        def fake_run(cmd, capture_output=True, text=True, timeout=600):
            assert cmd[:3] == ["gapit", "screen", str(contigs)]
            assert cmd[cmd.index("--db") + 1] == "card"
            assert cmd[cmd.index("--minid") + 1] == "90.0"

            class P:
                returncode = 0
                stdout = tsv
                stderr = ""
            return P()

        monkeypatch.setattr("bacmap.tools.pipeline.subprocess.run", fake_run)
        r = _parse(
            tools.gene_scan(
                {"contigs_path": str(contigs), "database": "card",
                 "min_identity": 90.0, "min_coverage": 95.0}
            )
        )
        assert r["database"] == "card"
        assert r["n_hits"] == 1
        assert r["hits"][0]["gene"] == "blaCTX-M-15"

    def test_multi_db_happy(self, tmp_path, monkeypatch):
        contigs = tmp_path / "contigs.fa"
        contigs.write_text(">c\nACGT\n")

        def fake_run(cmd, capture_output=True, text=True, timeout=600):
            class P:
                returncode = 0
                stdout = ""
                stderr = ""
            return P()

        monkeypatch.setattr("bacmap.tools.pipeline.subprocess.run", fake_run)
        r = _parse(tools.gene_scan({"contigs_path": str(contigs), "database": "card,vfdb"}))
        assert [x["database"] for x in r["results"]] == ["card", "vfdb"]

    def test_gapit_failure_returns_error(self, tmp_path, monkeypatch):
        contigs = tmp_path / "contigs.fa"
        contigs.write_text(">c\nACGT\n")

        def fake_run(cmd, capture_output=True, text=True, timeout=600):
            class P:
                returncode = 2
                stdout = ""
                stderr = "db not found"
            return P()

        monkeypatch.setattr("bacmap.tools.pipeline.subprocess.run", fake_run)
        r = _parse(tools.gene_scan({"contigs_path": str(contigs), "database": "nope"}))
        assert "error" in r




# ===========================================================================
# vpa_serotype
# ===========================================================================



class TestSnpTree:
    def test_no_db_no_disk_summary(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_services, "_GOM_DB", tmp_results / "no.sqlite")
        r = _parse(tools.snp_tree({}))
        assert "error" in r
        assert "SNP tree not available" in r["error"]

    def test_disk_summary_happy(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_services, "_GOM_DB", tmp_results / "no.sqlite")
        snp_dir = tmp_results / "snp"
        snp_dir.mkdir()
        summary_path = snp_dir / "snp_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "tree_newick": "(A,B);",
                    "n_samples": 3,
                    "n_snp_sites": 150,
                }
            )
        )
        r = _parse(tools.snp_tree({}))
        assert r["source"] == "disk"
        assert r["n_samples"] == 3
        assert r["n_snp_sites"] == 150
        assert r["tree_newick"] == "(A,B);"

    def test_disk_summary_corrupt(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_services, "_GOM_DB", tmp_results / "no.sqlite")
        snp_dir = tmp_results / "snp"
        snp_dir.mkdir()
        (snp_dir / "snp_summary.json").write_text("{not json")
        r = _parse(tools.snp_tree({}))
        assert "Failed to read SNP summary" in r["error"]

    def test_gom_lookup_happy(self, tmp_results, monkeypatch, tmp_path):
        db_path = tmp_path / "gom.sqlite"

        # Populate the GOM with a cohort SNP analysis object.
        cohort_payload = {
            "analysis_type": "snp_phylogeny",
            "samples": ["SAM-001", "SAM-002"],
            "n_samples": 2,
            "n_snp_sites": 200,
            "missing_rate": 0.05,
            "tree_newick": "(SAM-001,SAM-002);",
            "pairwise_distances": {"SAM-001": {"SAM-002": 12}},
        }
        with GenomeObjectService(db_path) as gos:
            obj = GenomeObject(
                object_id="00000000-0000-4000-8000-000000000001",
                object_type=ObjectType.ANALYSIS,
                version=3,
                schema_version="0.1.0",
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
                created_by="test",
                payload=cohort_payload,
                organism="Salmonella",
                strain_id="cohort:outbreak-snp",
                pipeline_version="v0.4",
                database_versions={"card": "3.3.0"},
                tool_versions={"snippy": "4.6.0"},
            )
            gos.create(obj)

        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)
        r = _parse(tools.snp_tree({}))
        assert r["source"] == "gom"
        assert r["n_samples"] == 2
        assert r["n_snp_sites"] == 200
        assert r["version"] == 3
        assert r["tree_newick"] == "(SAM-001,SAM-002);"


# ===========================================================================
# search_samples
# ===========================================================================


class TestSearchSamples:
    def test_db_missing(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_services, "_GOM_DB", tmp_results / "no.sqlite")
        r = _parse(tools.search_samples({}))
        assert "GOM database not found" in r["error"]

    def test_no_query_no_filters(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gom.sqlite"
        GenomeObjectService(db_path).close()  # create empty DB
        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)
        r = _parse(tools.search_samples({}))
        assert "error" in r
        assert "Provide at least one" in r["error"]

    def test_structured_search_by_serotype(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gom.sqlite"
        idx = StrainGenotypeIndex(db_path)
        idx.upsert(
            strain_id="SAM-001",
            organism="Salmonella enterica",
            species="Salmonella",
            serotype="Typhimurium",
            serotype_method="SISTR",
            mlst_scheme="salmonella_2",
            mlst_st="ST19",
            amr_genes=[{"gene": "blaCTX-M-15", "database": "card"}],
            object_id="obj-001",
        )
        idx.upsert(
            strain_id="SAM-002",
            organism="Salmonella enterica",
            species="Salmonella",
            serotype="Enteritidis",
            serotype_method="SISTR",
            mlst_scheme="salmonella_2",
            mlst_st="ST11",
            amr_genes=[],
            object_id="obj-002",
        )
        idx.close()
        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)

        r = _parse(tools.search_samples({"serotype": "Typhimurium"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-001"
        assert r["filters"] == {"serotype": "Typhimurium"}
        assert r["results"][0]["serotype"] == "Typhimurium"

    def test_structured_search_by_amr_gene(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gom.sqlite"
        idx = StrainGenotypeIndex(db_path)
        idx.upsert(
            strain_id="SAM-001",
            organism="Salmonella",
            species="Salmonella",
            serotype="Typhimurium",
            amr_genes=[{"gene": "blaCTX-M-15"}, {"gene": "tet(A)"}],
            object_id="obj-001",
        )
        idx.upsert(
            strain_id="SAM-002",
            organism="Salmonella",
            species="Salmonella",
            serotype="Enteritidis",
            amr_genes=[{"gene": "qnrS"}],
            object_id="obj-002",
        )
        idx.close()
        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)

        r = _parse(tools.search_samples({"amr_gene": "blaCTX-M-15"}))
        assert r["count"] == 1
        assert r["results"][0]["strain_id"] == "SAM-001"

    def test_full_text_search_via_gom(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gom.sqlite"
        # strain_id includes the literal "ST 19" so FTS5 tokenises "ST" and
        # "19" as separate searchable tokens (otherwise the json-encoded
        # \\t separator in mlst text would merge them).
        with GenomeObjectService(db_path) as gos:
            obj = GenomeObject(
                object_id="00000000-0000-4000-8000-000000000010",
                object_type=ObjectType.ANALYSIS,
                version=1,
                schema_version="0.1.0",
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
                created_by="test",
                payload={
                    "serotype": {"sistr": "Typhimurium"},
                    "mlst": ("FILE\tSCHEME\tST\ncontigs\tsalmonella_2\t19"),
                    "amr": {
                        "abricate_card": [
                            {"GENE": "blaCTX-M-15"},
                        ],
                    },
                },
                organism="Salmonella",
                strain_id="ST 19 outbreak strain",
                pipeline_version="v0.4",
                database_versions={"card": "3.3.0"},
                tool_versions={"abricate": "1.0.0"},
            )
            gos.create(obj)
        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)

        # "ST 19" form — handler parses ST-number query and matches mlst ST=19.
        r = _parse(tools.search_samples({"query": "ST 19"}))
        assert r["count"] >= 1
        ids = [m["strain_id"] for m in r["results"]]
        assert "ST 19 outbreak strain" in ids
        m = next(x for x in r["results"] if x["strain_id"] == "ST 19 outbreak strain")
        assert any("MLST" in rsn for rsn in m["matched_fields"])

    def test_full_text_amr_match(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gom.sqlite"
        with GenomeObjectService(db_path) as gos:
            obj = GenomeObject(
                object_id="00000000-0000-4000-8000-000000000020",
                object_type=ObjectType.ANALYSIS,
                version=1,
                schema_version="0.1.0",
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
                created_by="test",
                payload={
                    "serotype": {"sistr": "Enteritidis"},
                    "mlst": "",
                    "amr": {
                        "abricate_card": [{"GENE": "tet(A)"}],
                    },
                },
                organism="Salmonella",
                strain_id="SAM-AMR-001",
                pipeline_version="v0.4",
                database_versions={"card": "3.3.0"},
                tool_versions={"abricate": "1.0.0"},
            )
            gos.create(obj)
        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)

        r = _parse(tools.search_samples({"query": "tet(A)"}))
        assert r["count"] >= 1
        ids = [m["strain_id"] for m in r["results"]]
        assert "SAM-AMR-001" in ids

    def test_serotype_full_text_match(self, tmp_path, monkeypatch):
        db_path = tmp_path / "gom.sqlite"
        with GenomeObjectService(db_path) as gos:
            obj = GenomeObject(
                object_id="00000000-0000-4000-8000-000000000030",
                object_type=ObjectType.ANALYSIS,
                version=1,
                schema_version="0.1.0",
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
                created_by="test",
                payload={
                    "serotype": {"sistr": "Typhimurium"},
                    "mlst": "",
                    "amr": {},
                },
                organism="Salmonella",
                strain_id="SAM-SERO-001",
                pipeline_version="v0.4",
                database_versions={"card": "3.3.0"},
                tool_versions={"sistr": "1.1.0"},
            )
            gos.create(obj)
        monkeypatch.setattr(tools_services, "_GOM_DB", db_path)

        r = _parse(tools.search_samples({"query": "typhimurium"}))
        assert r["count"] >= 1
        ids = [m["strain_id"] for m in r["results"]]
        assert "SAM-SERO-001" in ids
        # matched_fields should reference serotype
        m = next(x for x in r["results"] if x["strain_id"] == "SAM-SERO-001")
        assert any("serotype" in r for r in m["matched_fields"])


# ===========================================================================
# validate_taxonomy
# ===========================================================================




# ===========================================================================
# annotate_genome
# ===========================================================================




# ===========================================================================
# diagnose_failure
# ===========================================================================


class TestDiagnoseFailure:
    def test_stderr_text_input(self):
        r = _parse(
            tools.diagnose_failure({"stderr_text": "Error locking directory workflows/bacmap"})
        )
        assert r["error_type"] == "lock"

    def test_stderr_oom(self):
        r = _parse(tools.diagnose_failure({"stderr_text": "ChildIOException signal 9"}))
        assert r["error_type"] == "oom"
        assert r["severity"] == "critical"

    def test_empty_stderr(self):
        r = _parse(tools.diagnose_failure({"stderr_text": "   "}))
        assert r["error_type"] == "empty"

    def test_unknown_error_shows_last_lines(self):
        r = _parse(tools.diagnose_failure({"stderr_text": "weird\nexception\ntraceback here"}))
        assert r["error_type"] == "unknown"

    def test_log_path_no_log(self, tmp_path, monkeypatch):
        # No log file at given path and no .snakemake/log either.
        # diagnose_from_log falls back to failure_diagnostics._PROJECT_ROOT,
        # so patch both module roots to keep the test off the real log dir.
        monkeypatch.setattr(failure_diagnostics, "WORKFLOW_LOG_DIR", tmp_path / "no_log")
        r = _parse(tools.diagnose_failure({"log_path": str(tmp_path / "missing.log")}))
        assert r["error_type"] == "no_log"

    def test_log_path_with_errors(self, tmp_path, monkeypatch):
        log_path = tmp_path / "snakemake.log"
        log_path.write_text(
            "Running rule shovill\nError locking directory workflows/bacmap\nTraceback shown.\n"
        )
        monkeypatch.setattr(tools_pipeline, "_DEPLOYED_WORKFLOWS_DIR", tmp_path)
        r = _parse(tools.diagnose_failure({"log_path": str(log_path)}))
        assert r["error_type"] == "lock"

    def test_log_path_no_errors(self, tmp_path, monkeypatch):
        log_path = tmp_path / "snakemake.log"
        log_path.write_text("all good today\n")
        monkeypatch.setattr(tools_pipeline, "_DEPLOYED_WORKFLOWS_DIR", tmp_path)
        r = _parse(tools.diagnose_failure({"log_path": str(log_path)}))
        assert r["error_type"] == "no_error"

    def test_fallback_to_default_log_dir(self, tmp_path, monkeypatch):
        # When neither stderr_text nor log_path given, handler uses the
        # deployed $BACMAP_HOME/workflows/bacmap/.snakemake/log dir. Point the
        # deployed dir + failure_diagnostics fallback to tmp → no_log.
        monkeypatch.setattr(tools_pipeline, "_DEPLOYED_WORKFLOWS_DIR", tmp_path / "deployed")
        monkeypatch.setattr(failure_diagnostics, "WORKFLOW_LOG_DIR", tmp_path / "no_log")
        r = _parse(tools.diagnose_failure({}))
        assert r["error_type"] == "no_log"


class TestSampleIdWhitelist:
    """P2-2（安全）：LLM 可控 sample_id 白名单——路径遍历/绝对路径拒绝。"""

    def test_verify_result_rejects_traversal(self, tmp_results):
        r = _parse(tools.verify_result({"sample_id": "../../etc/passwd"}))
        assert "invalid sample_id" in r["error"]

    def test_get_result_rejects_absolute_path(self, tmp_results):
        r = _parse(tools.get_result({"sample_id": "/etc/shadow"}))
        assert "invalid sample_id" in r["error"]

    def test_analyze_pathogen_rejects_traversal(self, tmp_results, monkeypatch):
        monkeypatch.setattr(tools_pipeline, "_run_project_script", lambda *a, **k: "ok")
        r = _parse(tools.analyze_pathogen({"sample_id": "../x/y"}))
        assert "invalid sample_id" in r["error"]

    def test_valid_id_still_passes(self, tmp_results):
        _write_summary(tmp_results, "SAM-OK-1", _salmonella_steps())
        r = _parse(tools.get_result({"sample_id": "SAM-OK-1"}))
        assert "error" not in r
