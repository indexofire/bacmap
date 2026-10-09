"""Unit tests for bacmap.core.analysis.genome_annotator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis import genome_annotator  # noqa: E402
from bacmap.core.analysis.genome_annotator import (  # noqa: E402
    AnnotationResult,
    Feature,
    _make_locus_tag,
    _parse_prokka_header,
    _predict_cds,
    _read_contigs,
)
from bacmap.core.engine.hits import Hit  # noqa: E402

_BACTERIAL_SEQ = (
    "ATGACCATGATTACGGATTCACTGGCCGTCGTTTTACAACGT"  # pragma: allowlist secret
    "CGTGACTGGGAAAACCCTGGCGTTACCCAACTTA"
    "ATCGCCTTGCAGCACATCCCCCTTTCGCCAGCTGGCGTAATAGCGAAGAGGCCCGCACCGATCGCCCTTCCCAACA"
    "GTTGCGCAGCCTGAATGGCGAATGGCGCCTGATGCGGTATTTTCTCCTTACGCATCTGTGCGGTATTTCACACCGC"
    "ATATGGTGCACTCTCAGTACAATCTGCTCTGATGCCGCATAGTTAAGCCAGTATACACTCCCGTCATTTGGCGTTA"
    "ACGACGTGAACCATCACCAGATCGAGCGCAACCGCAATAT"  # pragma: allowlist secret
    "CAGCAAGAGCGCCGTCATATTGCGCGGTAAACGCAC"
    "CATGCAGTGGCGTAACGATGATTGCGGTAAACGCACCATGCAGTGGCGTAACGAC"  # pragma: allowlist secret
)


class TestReadContigs:
    def test_reads_single_record(self, tmp_path):
        f = tmp_path / "x.fasta"
        f.write_text(">ctg1 description\nACGT\nACGT\n")
        out = _read_contigs(f)
        assert out == [("ctg1", "ACGTACGT")]

    def test_reads_multiple_records(self, tmp_path):
        f = tmp_path / "x.fasta"
        f.write_text(">a\nACGT\n>b desc\nTTTT\nGGGG\n")
        out = _read_contigs(f)
        assert out == [("a", "ACGT"), ("b", "TTTTGGGG")]

    def test_uppercases_sequence(self, tmp_path):
        f = tmp_path / "x.fasta"
        f.write_text(">a\nacgt\n")
        assert _read_contigs(f) == [("a", "ACGT")]

    def test_strips_header_description(self, tmp_path):
        f = tmp_path / "x.fasta"
        f.write_text(">first_word rest of desc\nACGT\n")
        assert _read_contigs(f)[0][0] == "first_word"

    def test_empty_file_returns_empty_list(self, tmp_path):
        f = tmp_path / "x.fasta"
        f.write_text("")
        assert _read_contigs(f) == []


class TestPredictCdsMetaMode:
    def test_predicts_orfs_with_real_pyrodigal(self):
        contigs = [("ctg1", _BACTERIAL_SEQ)]
        out = _predict_cds(contigs)
        assert len(out) >= 1
        for tup in out:
            assert len(tup) == 6
            contig_name, begin, end, strand, na_seq, prot_seq = tup
            assert contig_name == "ctg1"
            assert isinstance(begin, int)
            assert isinstance(end, int)
            assert strand in (1, -1)
            assert isinstance(na_seq, str)
            assert isinstance(prot_seq, str)
            assert "*" not in prot_seq

    def test_skips_short_contigs(self):
        contigs = [("short", "ACGT" * 10)]
        out = _predict_cds(contigs)
        assert out == []

    def test_total_bp_under_threshold_uses_meta_mode(self):
        assert len(_BACTERIAL_SEQ) < genome_annotator._SINGLE_MODE_THRESHOLD


class TestPredictCdsSingleMode:
    def test_uses_single_mode_when_total_bp_exceeds_threshold(self, monkeypatch):
        captured = {}

        class FakeGeneFinder:
            def __init__(self, **kwargs):
                captured["init_kwargs"] = kwargs

            def train(self, seq):
                captured["trained_with"] = len(seq)

            def find_genes(self, seq):
                captured["find_called"] = True

                class FakeGene:
                    def __init__(self, b, e, s):
                        self.begin = b
                        self.end = e
                        self.strand = s

                    def sequence(self):
                        return "ACGT" * 30

                    def translate(self, translation_table=11):
                        return "M" + "A" * 119

                return [FakeGene(1, 120, 1)]

        long_seq = "A" * (genome_annotator._SINGLE_MODE_THRESHOLD + 100)
        monkeypatch.setattr(genome_annotator.pyrodigal, "GeneFinder", FakeGeneFinder)
        out = _predict_cds([("big", long_seq)])
        assert "meta" not in captured["init_kwargs"]
        assert captured["init_kwargs"]["closed"] is True
        assert captured["init_kwargs"]["mask"] is True
        assert "trained_with" in captured
        assert len(out) == 1


class TestFeature:
    def test_to_dict_contains_all_dataclass_fields(self):
        feat = Feature(
            locus_tag="SAM_0001",
            ftype="CDS",
            contig="ctg1",
            start=1,
            end=100,
            strand=1,
            length_bp=100,
            gene="dnaA",
            product="chromosomal replication initiator",
            ec_number="1.1.1.1",
            cog="COG1234",
            source="sprot",
            identity=99.0,
            coverage=98.0,
            protein_seq="M" * 30,
            na_seq="ATGC" * 30,
        )
        d = feat.to_dict()
        expected = {
            "locus_tag",
            "ftype",
            "contig",
            "start",
            "end",
            "strand",
            "length_bp",
            "gene",
            "product",
            "ec_number",
            "cog",
            "source",
            "identity",
            "coverage",
            "protein_seq",
            "na_seq",
        }
        assert set(d.keys()) == expected
        assert d["gene"] == "dnaA"
        assert d["identity"] == 99.0


class TestAnnotationResultSummary:
    def test_summary_empty_features(self):
        r = AnnotationResult(sample_id="SAM-001")
        s = r.summary
        assert s["total_CDS"] == 0
        assert s["annotation_rate"] == 0
        assert s["total_contigs"] == 0
        assert s["total_length_bp"] == 0

    def test_summary_with_contigs_and_features(self):
        r = AnnotationResult(sample_id="SAM-001")
        r.contigs = [
            {"id": "ctg1", "length": 1000, "gc_content": 0.5},
            {"id": "ctg2", "length": 500, "gc_content": 0.4},
        ]
        r.features = [
            Feature("a", "CDS", "ctg1", 1, 100, 1, 100, gene="dnaA", product="initiator"),
            Feature("b", "CDS", "ctg1", 200, 300, 1, 101, product="hypothetical protein"),
            Feature("c", "CDS", "ctg2", 1, 100, 1, 100, gene="", product="hypothetical protein"),
            Feature("d", "rRNA", "ctg2", 200, 400, 1, 201, product="16S"),
        ]
        s = r.summary
        assert s["total_contigs"] == 2
        assert s["total_length_bp"] == 1500
        assert s["total_CDS"] == 3
        assert s["annotated_CDS"] == 1
        assert s["hypothetical_CDS"] == 2
        assert s["annotation_rate"] == round(1 / 3, 3)

    def test_summary_handles_zero_cds_safely(self):
        r = AnnotationResult(sample_id="x")
        r.features = [Feature("a", "rRNA", "c", 1, 100, 1, 100, product="16S")]
        assert r.summary["total_CDS"] == 0
        assert r.summary["annotation_rate"] == 0


class TestAnnotationResultSave:
    def test_save_writes_json_with_parent_dirs(self, tmp_path):
        r = AnnotationResult(sample_id="SAM-001")
        r.contigs = [{"id": "ctg1", "length": 100, "gc_content": 0.5}]
        r.features = [Feature("a", "CDS", "ctg1", 1, 100, 1, 100, gene="dnaA", product="initiator")]
        out = tmp_path / "results" / "SAM-001" / "annotation" / "annotation.json"
        r.save(out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["sample_id"] == "SAM-001"
        assert data["summary"]["total_CDS"] == 1
        assert data["features"][0]["gene"] == "dnaA"

    def test_to_dict_includes_summary_and_features(self):
        r = AnnotationResult(sample_id="x")
        r.features = [Feature("a", "CDS", "c", 1, 100, 1, 100, product="hypothetical protein")]
        d = r.to_dict()
        assert "summary" in d
        assert "features" in d
        assert d["summary"]["total_CDS"] == 1


class TestParseProkkaHeader:
    def test_four_or_more_fields(self):
        assert _parse_prokka_header("db~~~gene1~~~ACC~~~product description") == (
            "gene1",
            "product description",
        )

    def test_three_fields(self):
        assert _parse_prokka_header("db~~~gene1~~~ACC") == ("gene1", "ACC")

    def test_two_fields(self):
        assert _parse_prokka_header("db~~~gene1") == ("gene1", "")

    def test_single_field_returns_hypothetical(self):
        assert _parse_prokka_header("justaname") == ("justaname", "hypothetical protein")


class TestMakeLocusTag:
    def test_strips_dashes_and_underscores(self):
        tag = _make_locus_tag("SAM-DEC-001", 5)
        assert tag.startswith("SAMDEC00_")
        assert tag.endswith("_00005")

    def test_empty_sample_uses_SAMPLE_prefix(self):
        tag = _make_locus_tag("", 1)
        assert tag.startswith("SAMPLE_")

    def test_index_is_zero_padded(self):
        tag = _make_locus_tag("SAM", 42)
        assert tag.endswith("_00042")

    def test_unique_for_different_ids(self):
        assert _make_locus_tag("SAM-001", 1) != _make_locus_tag("SAM-002", 1)


class TestRunBlastp:
    def test_invokes_sequence_matcher_and_parses_hits(self, monkeypatch):
        captured = {}

        def fake_match(**kwargs):
            captured.update(kwargs)
            return [
                Hit(
                    query_id="q1",
                    subject_id="prokka_sprot~~~dnaA~~~ACC~~~DNA replication initiator",
                    identity=99.0,
                    subject_coverage=98.0,
                    evalue=1e-50,
                ),
                Hit(
                    query_id="q2",
                    subject_id="prokka_sprot~~~parB~~~ACC2~~~partition protein",
                    identity=95.0,
                    subject_coverage=90.0,
                    evalue=1e-30,
                ),
            ]

        monkeypatch.setattr(
            "bacmap.core.engine.SequenceMatcher",
            type("SM", (), {"match": classmethod(lambda cls, **kw: fake_match(**kw))}),
            raising=True,
        )

        proteins = Path("/tmp/dummy.faa")
        hits = genome_annotator._run_blastp(proteins, "prokka_sprot", 1e-6, 80.0)
        assert captured["mode"] == "blastp"
        assert captured["query_type"] == "prot"
        assert captured["evalue"] == 1e-6
        assert captured["max_targets"] == 1
        assert set(hits.keys()) == {"q1", "q2"}
        assert hits["q1"]["gene"] == "dnaA"
        assert hits["q1"]["product"] == "DNA replication initiator"
        assert hits["q1"]["identity"] == 99.0
        assert hits["q2"]["gene"] == "parB"

    def test_dedup_keeps_first_hit_per_query(self, monkeypatch):
        hits_seq = [
            Hit(
                query_id="q1",
                subject_id="db~~~first~~~A~~~p1",
                identity=99.0,
                subject_coverage=99.0,
                evalue=1e-30,
            ),
            Hit(
                query_id="q1",
                subject_id="db~~~second~~~A~~~p2",
                identity=50.0,
                subject_coverage=50.0,
                evalue=1e-5,
            ),
        ]

        class FakeMatcher:
            @classmethod
            def match(cls, **kwargs):
                return list(hits_seq)

        monkeypatch.setattr("bacmap.core.engine.SequenceMatcher", FakeMatcher)
        out = genome_annotator._run_blastp(Path("/tmp/x.faa"), "db", 1e-6, 80.0)
        assert set(out.keys()) == {"q1"}
        assert out["q1"]["gene"] == "first"


class TestAnnotateEndToEnd:
    def test_raises_on_missing_contigs(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Contigs not found"):
            genome_annotator.annotate(tmp_path / "nope.fasta")

    def test_annotates_synthetic_contig_no_db(self, tmp_path):
        f = tmp_path / "ctgs.fasta"
        f.write_text(f">ctg1\n{_BACTERIAL_SEQ}\n")

        result = genome_annotator.annotate(f, sample_id="SAM-001")
        assert result.sample_id == "SAM-001"
        assert len(result.contigs) == 1
        assert result.contigs[0]["id"] == "ctg1"
        assert result.contigs[0]["length"] == len(_BACTERIAL_SEQ)
        assert 0 <= result.contigs[0]["gc_content"] <= 1
        assert len(result.features) >= 1
        for feat in result.features:
            assert feat.product == "hypothetical protein"
            assert feat.gene == ""

    def test_annotates_and_attaches_known_annotation(self, tmp_path, monkeypatch):
        f = tmp_path / "ctgs.fasta"
        f.write_text(f">ctg1\n{_BACTERIAL_SEQ}\n")

        contigs_list = _read_contigs(f)
        predictions = _predict_cds(contigs_list)
        assert len(predictions) >= 1
        first_tag = _make_locus_tag("SAM-001", 1)

        canned = {
            first_tag: {
                "gene": "dnaA",
                "product": "chromosomal replication initiator",
                "identity": 99.0,
                "coverage": 98.0,
                "evalue": 1e-50,
            }
        }

        def fake_run_blastp(proteins_faa, db_name, evalue, min_cov):
            return dict(canned) if db_name == "prokka_sprot" else {}

        monkeypatch.setattr(genome_annotator, "_run_blastp", fake_run_blastp)

        ref_dir = tmp_path / "ref"
        ref_dir.mkdir()
        (ref_dir / "prokka_sprot.phr").write_text("")
        monkeypatch.setattr(genome_annotator, "_REF_DIR", ref_dir)

        result = genome_annotator.annotate(f, sample_id="SAM-001")
        feat = next(f for f in result.features if f.locus_tag == first_tag)
        assert feat.gene == "dnaA"
        assert feat.product == "chromosomal replication initiator"
        assert feat.identity == 99.0
        assert feat.coverage == 98.0
        assert feat.source == "sprot"

    def test_first_db_per_query_wins_over_later_dbs(self, tmp_path, monkeypatch):
        f = tmp_path / "ctgs.fasta"
        f.write_text(f">ctg1\n{_BACTERIAL_SEQ}\n")
        first_tag = _make_locus_tag("SAM-001", 1)

        def fake_run_blastp(proteins_faa, db_name, evalue, min_cov):
            if db_name == "prokka_sprot":
                return {
                    first_tag: {
                        "gene": "sprot_gene",
                        "product": "from sprot",
                        "identity": 90.0,
                        "coverage": 90.0,
                        "evalue": 1e-10,
                    }
                }
            if db_name == "prokka_is":
                return {
                    first_tag: {
                        "gene": "is_gene",
                        "product": "from IS",
                        "identity": 99.0,
                        "coverage": 99.0,
                        "evalue": 1e-100,
                    }
                }
            return {}

        monkeypatch.setattr(genome_annotator, "_run_blastp", fake_run_blastp)

        ref_dir = tmp_path / "ref"
        ref_dir.mkdir()
        (ref_dir / "prokka_sprot.phr").write_text("")
        (ref_dir / "prokka_is.phr").write_text("")
        monkeypatch.setattr(genome_annotator, "_REF_DIR", ref_dir)

        result = genome_annotator.annotate(f, sample_id="SAM-001")
        feat = next(f for f in result.features if f.locus_tag == first_tag)
        assert feat.gene == "sprot_gene"
        assert feat.source == "sprot"

    def test_save_after_annotate(self, tmp_path, monkeypatch):
        f = tmp_path / "ctgs.fasta"
        f.write_text(f">ctg1\n{_BACTERIAL_SEQ}\n")
        monkeypatch.setattr(genome_annotator, "_run_blastp", lambda *a, **kw: {})
        monkeypatch.setattr(genome_annotator, "_REF_DIR", tmp_path / "no_dbs")
        result = genome_annotator.annotate(f, sample_id="SAM-001")
        out = tmp_path / "annotation.json"
        result.save(out)
        data = json.loads(out.read_text())
        assert data["sample_id"] == "SAM-001"
        assert len(data["features"]) == len(result.features)


class TestAnnotateSampleIdInference:
    def test_sample_id_inferred_from_parent_parent_dir(self, tmp_path):
        sample_dir = tmp_path / "SAM-XYZ-001" / "assembly"
        sample_dir.mkdir(parents=True)
        f = sample_dir / "contigs.fasta"
        f.write_text(f">ctg1\n{_BACTERIAL_SEQ}\n")
        result = genome_annotator.annotate(f)
        assert result.sample_id == "SAM-XYZ-001"
