"""Unit tests for bacmap.core.analysis.gene_scanner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis import gene_scanner  # noqa: E402
from bacmap.core.analysis.gene_scanner import (  # noqa: E402
    GeneHit,
    ScanResult,
    _parse_db_header,
    normalize_synonyms,
    resolve_gene_name,
)
from bacmap.core.engine.hits import Hit  # noqa: E402


class TestNormalizeSynonyms:
    def test_empty_dict_returns_empty(self):
        assert normalize_synonyms({}) == {}

    def test_none_returns_empty(self):
        assert normalize_synonyms(None) == {}  # type: ignore[arg-type]

    def test_canonical_to_aliases_format(self):
        raw = {"stx1": ["stx1a", "stxA1"]}
        assert normalize_synonyms(raw) == {"stx1": ["stx1a", "stxa1"]}

    def test_alias_to_canonical_format(self):
        raw = {"stx1a": "stx1", "stxA1": "stx1"}
        assert normalize_synonyms(raw) == {"stx1": ["stx1a", "stxa1"]}

    def test_mixed_formats_merge(self):
        raw = {"stx1": ["stxA1"], "stx1a": "stx1"}
        assert normalize_synonyms(raw) == {"stx1": ["stxa1", "stx1a"]}

    def test_keys_and_values_lowercased_and_stripped(self):
        raw = {"  Stx1 ": ["  StxA1 ", "stxa2"]}
        assert normalize_synonyms(raw) == {"stx1": ["stxa1", "stxa2"]}

    def test_invalid_value_type_yields_empty_alias_list(self):
        assert normalize_synonyms({"x": 123}) == {"x": []}


class TestResolveGeneName:
    def test_no_synonyms_returns_raw(self):
        assert resolve_gene_name("invA") == "invA"

    def test_empty_synonyms_returns_raw(self):
        assert resolve_gene_name("invA", {}) == "invA"

    def test_canonical_match_returns_canonical(self):
        assert resolve_gene_name("invA", {"inva": ["stxa1"]}) == "inva"

    def test_alias_match_returns_canonical(self):
        assert resolve_gene_name("stxA1", {"stx1": ["stx1a", "stxa1"]}) == "stx1"

    def test_no_match_returns_raw(self):
        assert resolve_gene_name("blaTEM", {"stx1": ["stx1a"]}) == "blaTEM"


class TestParseDbHeader:
    def test_four_or_more_fields(self):
        out = _parse_db_header("card~~~blaTEM~~~A123~~~beta-lactamase~~~extra")
        assert out == ("blaTEM", "A123", "beta-lactamase", "")

    def test_exactly_four_fields(self):
        assert _parse_db_header("card~~~blaTEM~~~A123~~~beta-lactamase") == (
            "blaTEM",
            "A123",
            "beta-lactamase",
            "",
        )

    def test_three_fields(self):
        assert _parse_db_header("db~~~gene~~~acc") == ("gene", "acc", "", "")

    def test_two_fields(self):
        assert _parse_db_header("db~~~gene") == ("gene", "", "", "")

    def test_single_field(self):
        assert _parse_db_header("justaname") == ("justaname", "", "", "")

    def test_fields_are_stripped(self):
        assert _parse_db_header("  db ~~~  gene  ~~~ acc ~~~ prod") == (
            "gene",
            "acc",
            "prod",
            "",
        )


class TestGeneHit:
    def test_to_dict_contains_all_keys(self):
        gh = GeneHit(
            gene="blaTEM",
            identity=99.5,
            coverage=98.0,
            contig="ctg1",
            start=100,
            end=400,
            strand="+",
            accession="A123",
            product="beta-lactamase",
            database="card",
        )
        d = gh.to_dict()
        for key in (
            "gene",
            "identity",
            "coverage",
            "contig",
            "start",
            "end",
            "strand",
            "accession",
            "product",
            "hit_length",
        ):
            assert key in d
        assert d["hit_length"] == 301

    def test_hit_length_forward(self):
        gh = GeneHit(gene="g", identity=0, coverage=0, contig="c", start=10, end=20, strand="+")
        assert gh.hit_length == 11

    def test_hit_length_reverse_is_absolute(self):
        gh = GeneHit(gene="g", identity=0, coverage=0, contig="c", start=20, end=10, strand="-")
        assert gh.hit_length == 11

    def test_product_truncated_to_200_chars(self):
        gh = GeneHit(
            gene="g",
            identity=0,
            coverage=0,
            contig="c",
            start=0,
            end=10,
            strand="+",
            product="X" * 500,
        )
        assert len(gh.to_dict()["product"]) == 200

    def test_empty_product_yields_empty_string(self):
        gh = GeneHit(
            gene="g",
            identity=0,
            coverage=0,
            contig="c",
            start=0,
            end=10,
            strand="+",
            product="",
        )
        assert gh.to_dict()["product"] == ""


class TestScanResult:
    def test_to_dict_shape(self):
        sr = ScanResult(
            database="card",
            input_file="/tmp/x.fasta",
            min_identity=80.0,
            min_coverage=90.0,
        )
        d = sr.to_dict()
        assert d["database"] == "card"
        assert d["thresholds"] == {"min_identity": 80.0, "min_coverage": 90.0}
        assert d["total_hits"] == 0
        assert d["unique_gene_count"] == 0
        assert d["unique_genes"] == []
        assert d["genes"] == []
        assert d["summary"] == {}

    def test_build_summary_counts_unique_genes(self):
        sr = ScanResult(database="card", input_file="x", min_identity=80.0, min_coverage=80.0)
        sr.genes = [
            GeneHit("a", 99.0, 100.0, "c", 1, 100, "+"),
            GeneHit("a", 98.0, 99.0, "c", 1, 100, "+"),
            GeneHit("b", 95.0, 95.0, "c", 1, 100, "+"),
        ]
        out = sr.build_summary()
        assert out == {"total_hits": 3, "unique_genes": 2}
        assert sr.unique_genes == ["a", "b"]
        assert sr.total_hits == 0


class TestFindDb:
    def test_finds_ndb_in_search_path(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        (base / "card_blastdb.ndb").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        assert gene_scanner._find_db("card") == base / "card_blastdb"

    def test_finds_nhr_in_search_path(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        (base / "card.nhr").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        assert gene_scanner._find_db("card") == base / "card"

    def test_finds_phr_protein_db(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        (base / "prokka_sprot.phr").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        assert gene_scanner._find_db("prokka_sprot") == base / "prokka_sprot"

    def test_finds_under_db_subdir_sequences(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        (base / "card").mkdir(parents=True)
        (base / "card" / "sequences.ndb").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        assert gene_scanner._find_db("card") == base / "card" / "sequences"

    def test_not_found_raises_filenotfound(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        with pytest.raises(FileNotFoundError, match="Database 'nope' not found"):
            gene_scanner._find_db("nope")

    def test_error_message_includes_setup_hint(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        with pytest.raises(FileNotFoundError) as ei:
            gene_scanner._find_db("missing_db")
        assert "setup_db('missing_db')" in str(ei.value)


class TestFindKmaIndex:
    def test_returns_path_when_name_marker_exists(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        kma_dir = base / "card_kma"
        kma_dir.mkdir()
        (kma_dir / "name").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        assert gene_scanner._find_kma_index("card") == kma_dir

    def test_returns_none_when_no_marker(self, tmp_path, monkeypatch):
        base = tmp_path / "ref"
        base.mkdir()
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])
        assert gene_scanner._find_kma_index("card") is None


def _build_hit(
    subject_id: str,
    identity: float,
    coverage: float,
    query_id: str = "ctg1",
    qstart: int = 100,
    qend: int = 500,
    strand: str = "+",
) -> Hit:
    return Hit(
        query_id=query_id,
        subject_id=subject_id,
        identity=identity,
        subject_coverage=coverage,
        query_coverage=coverage,
        query_start=qstart,
        query_end=qend,
        strand=strand,
    )


class TestScanAssembly:
    def test_filters_below_threshold_and_maps_fields(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref"
        ref.mkdir()
        (ref / "card_blastdb.ndb").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [ref])

        contigs = tmp_path / "ctgs.fasta"
        contigs.write_text(">ctg1\nACGT\n")

        hits = [
            _build_hit("card~~~blaTEM~~~A1~~~beta-lactamase", 99.0, 100.0),
            _build_hit("card~~~low~~~A2~~~low product", 70.0, 100.0),
            _build_hit("card~~~lowcov~~~A3~~~x", 99.0, 50.0),
        ]

        captured: dict = {}

        class FakeMatcher:
            @classmethod
            def match(cls, **kwargs):
                captured.update(kwargs)
                return hits

        monkeypatch.setattr("bacmap.core.engine.SequenceMatcher", FakeMatcher, raising=True)

        result = gene_scanner._scan_assembly(contigs, "card", 80.0, 80.0, 4)

        assert captured["mode"] == "blastn"
        assert captured["min_identity"] == 0.0
        assert captured["min_coverage"] == 0.0
        assert captured["evalue"] == gene_scanner._EVALUE
        assert captured["word_size"] == gene_scanner._WORD_SIZE
        assert captured["num_threads"] == 4

        assert len(result.genes) == 1
        gh = result.genes[0]
        assert gh.gene == "blaTEM"
        assert gh.accession == "A1"
        assert gh.product == "beta-lactamase"
        assert gh.database == "card"
        assert gh.identity == 99.0
        assert gh.coverage == 100.0
        assert gh.contig == "ctg1"
        assert gh.start == 100
        assert gh.end == 500
        assert gh.strand == "+"
        assert result.total_hits == 1
        assert result.unique_genes == ["blaTEM"]

    def test_genes_sorted_by_identity_desc_then_gene(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref"
        ref.mkdir()
        (ref / "card_blastdb.ndb").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [ref])

        contigs = tmp_path / "ctgs.fasta"
        contigs.write_text(">ctg1\nACGT\n")

        hits = [
            _build_hit("card~~~bbb~~~A1~~~p", 90.0, 100.0),
            _build_hit("card~~~aaa~~~A2~~~p", 99.0, 100.0),
            _build_hit("card~~~ccc~~~A3~~~p", 90.0, 100.0),
        ]

        class FakeMatcher:
            @classmethod
            def match(cls, **kwargs):
                return hits

        monkeypatch.setattr("bacmap.core.engine.SequenceMatcher", FakeMatcher)
        result = gene_scanner._scan_assembly(contigs, "card", 80.0, 80.0, 2)
        assert [g.gene for g in result.genes] == ["aaa", "bbb", "ccc"]

    def test_reverse_strand_coordinates_normalized(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref"
        ref.mkdir()
        (ref / "card_blastdb.ndb").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [ref])

        contigs = tmp_path / "ctgs.fasta"
        contigs.write_text(">ctg1\nACGT\n")

        hits = [
            _build_hit("card~~~rev~~~A1~~~p", 95.0, 95.0, qstart=500, qend=100, strand="-"),
        ]

        class FakeMatcher:
            @classmethod
            def match(cls, **kwargs):
                return hits

        monkeypatch.setattr("bacmap.core.engine.SequenceMatcher", FakeMatcher)
        result = gene_scanner._scan_assembly(contigs, "card", 80.0, 80.0, 1)
        gh = result.genes[0]
        assert gh.start == 100
        assert gh.end == 500
        assert gh.strand == "-"


class TestScanReads:
    def test_dedup_by_gene_keeps_highest_identity(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref"
        ref.mkdir()
        kma = ref / "card_kma"
        kma.mkdir()
        (kma / "name").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [ref])

        r1 = tmp_path / "reads.r1.fastq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")

        hits = [
            _build_hit("card~~~blaTEM~~~A1~~~p", 95.0, 100.0, query_id="reads"),
            _build_hit("card~~~blaTEM~~~A1~~~p", 99.0, 100.0, query_id="reads"),
            _build_hit("card~~~blaSHV~~~A2~~~p", 90.0, 99.0, query_id="reads"),
        ]

        class FakeKma:
            def __init__(self, *a, **kw):
                pass

            def find(self, **kwargs):
                return hits

        monkeypatch.setattr("bacmap.core.engine.backends.kma.KmaBackend", FakeKma, raising=True)
        result = gene_scanner._scan_reads(r1, None, "card", 80.0, 80.0, 4)

        assert len(result.genes) == 2
        by_gene = {g.gene: g for g in result.genes}
        assert by_gene["blaTEM"].identity == 99.0
        assert by_gene["blaSHV"].identity == 90.0
        assert by_gene["blaTEM"].start == 0
        assert by_gene["blaTEM"].end == 0
        assert by_gene["blaTEM"].strand == "+"
        assert result.total_hits == 2

    def test_skips_hits_with_empty_gene(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref"
        ref.mkdir()
        kma = ref / "card_kma"
        kma.mkdir()
        (kma / "name").write_text("")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [ref])

        r1 = tmp_path / "reads.r1.fastq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")

        hits = [
            _build_hit("card~~~~~~~~~p", 99.0, 100.0, query_id="reads"),
            _build_hit("card~~~blaTEM~~~A1~~~p", 95.0, 100.0, query_id="reads"),
        ]

        class FakeKma:
            def __init__(self, *a, **kw):
                pass

            def find(self, **kwargs):
                return hits

        monkeypatch.setattr("bacmap.core.engine.backends.kma.KmaBackend", FakeKma, raising=True)
        result = gene_scanner._scan_reads(r1, None, "card", 80.0, 80.0, 4)
        assert len(result.genes) == 1
        assert result.genes[0].gene == "blaTEM"

    def test_raises_when_no_kma_index(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref"
        ref.mkdir()
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [ref])
        r1 = tmp_path / "reads.r1.fastq"
        r1.write_text("@r\nACGT\n+\n!!!!\n")
        with pytest.raises(FileNotFoundError, match="KMA index"):
            gene_scanner._scan_reads(r1, None, "card", 80.0, 80.0, 4)


class TestScanRouting:
    def test_scan_raises_on_missing_query(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Query not found"):
            gene_scanner.scan(tmp_path / "nope.fasta")

    def test_scan_routes_fasta_to_scan_assembly(self, tmp_path, monkeypatch):
        q = tmp_path / "asm.fasta"
        q.write_text(">c\nACGT\n")
        called = {"assembly": 0, "reads": 0}

        def fake_assembly(*a, **kw):
            called["assembly"] += 1
            return ScanResult(
                database="card", input_file=str(q), min_identity=80.0, min_coverage=80.0
            )

        def fake_reads(*a, **kw):
            called["reads"] += 1
            return ScanResult(
                database="card", input_file=str(q), min_identity=80.0, min_coverage=80.0
            )

        monkeypatch.setattr(gene_scanner, "_scan_assembly", fake_assembly)
        monkeypatch.setattr(gene_scanner, "_scan_reads", fake_reads)
        gene_scanner.scan(q, db_name="card")
        assert called == {"assembly": 1, "reads": 0}

    @pytest.mark.parametrize("fname", ["reads.fastq", "reads.fq", "reads.fastq.gz", "reads.fq.gz"])
    def test_scan_routes_fastq_variants_to_reads(self, tmp_path, monkeypatch, fname):
        q = tmp_path / fname
        q.write_text("dummy")
        called = {"reads": 0}

        def fake_reads(*a, **kw):
            called["reads"] += 1
            return ScanResult(
                database="card", input_file=str(q), min_identity=80.0, min_coverage=80.0
            )

        monkeypatch.setattr(gene_scanner, "_scan_reads", fake_reads)
        gene_scanner.scan(q, db_name="card")
        assert called["reads"] == 1


class TestScanMulti:
    def test_scan_multi_returns_dict_per_db(self, tmp_path, monkeypatch):
        q = tmp_path / "asm.fasta"
        q.write_text(">c\nACGT\n")
        recorded = []

        def fake_scan(query, db_name=None, **kw):
            recorded.append(db_name)
            return ScanResult(
                database=db_name,
                input_file=str(query),
                min_identity=kw.get("min_identity", 80.0),
                min_coverage=kw.get("min_coverage", 80.0),
            )

        monkeypatch.setattr(gene_scanner, "scan", fake_scan)
        out = gene_scanner.scan_multi(q, ["card", "vfdb"], min_identity=85.0, min_coverage=90.0)
        assert set(out.keys()) == {"card", "vfdb"}
        assert recorded == ["card", "vfdb"]
        assert out["card"].min_identity == 85.0
        assert out["vfdb"].min_coverage == 90.0


class TestSetupDb:
    def test_setup_db_copies_fasta_and_calls_make_db(self, tmp_path, monkeypatch):
        src = tmp_path / "src.fasta"
        src.write_text(">g\nACGT\n")
        out_dir = tmp_path / "out"
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [tmp_path])

        calls: dict = {}

        class FakeBlast:
            def __init__(self, tool="blastn"):
                self.tool = tool

            def make_db(self, fasta, prefix, db_type="nucl"):
                calls["fasta"] = str(fasta)
                calls["prefix"] = str(prefix)
                calls["db_type"] = db_type

        monkeypatch.setattr(
            "bacmap.core.engine.backends.blast.BlastBackend", FakeBlast, raising=True
        )

        prefix = gene_scanner.setup_db("card", fasta_source=src, output_dir=out_dir)
        assert prefix == out_dir / "card_blastdb"
        assert (out_dir / "card_sequences.fasta").exists()
        assert calls["db_type"] == "nucl"
        assert calls["prefix"].endswith("card_blastdb")

    def test_setup_db_auto_resolves_source_from_db_module(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        fake_src = tmp_path / "db.fasta"
        fake_src.write_text(">g\nACGT\n")

        import bacmap.core.db as dbm

        monkeypatch.setattr(dbm, "DB_NAME_TO_SOURCE", {"card": fake_src})
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [tmp_path])

        class FakeBlast:
            def __init__(self, tool="blastn"):
                pass

            def make_db(self, *a, **kw):
                pass

        monkeypatch.setattr(
            "bacmap.core.engine.backends.blast.BlastBackend", FakeBlast, raising=True
        )
        prefix = gene_scanner.setup_db("card", output_dir=out_dir)
        assert prefix == out_dir / "card_blastdb"

    def test_setup_db_auto_resolves_from_search_paths(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        base = tmp_path / "ref"
        (base / "card").mkdir(parents=True)
        (base / "card" / "sequences").write_text(">g\nACGT\n")
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [base])

        import bacmap.core.db as dbm

        monkeypatch.setattr(dbm, "DB_NAME_TO_SOURCE", {})

        class FakeBlast:
            def __init__(self, tool="blastn"):
                pass

            def make_db(self, *a, **kw):
                pass

        monkeypatch.setattr(
            "bacmap.core.engine.backends.blast.BlastBackend", FakeBlast, raising=True
        )
        prefix = gene_scanner.setup_db("card", output_dir=out_dir)
        assert prefix == out_dir / "card_blastdb"

    def test_setup_db_raises_when_no_source_found(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [tmp_path])
        import bacmap.core.db as dbm

        monkeypatch.setattr(dbm, "DB_NAME_TO_SOURCE", {})
        with pytest.raises(FileNotFoundError, match="Source FASTA"):
            gene_scanner.setup_db("doesnotexist", output_dir=out_dir)


class TestSetupKmaIndex:
    def test_setup_kma_index_calls_backend_make_index(self, tmp_path, monkeypatch, capsys):
        src = tmp_path / "src.fasta"
        src.write_text(">g\nACGT\n")
        out_dir = tmp_path / "out"
        captured = {}

        class FakeKma:
            def __init__(self, *a, **kw):
                pass

            def make_index(self, fasta, prefix):
                captured["fasta"] = fasta
                captured["prefix"] = prefix

        monkeypatch.setattr("bacmap.core.engine.backends.kma.KmaBackend", FakeKma, raising=True)
        result = gene_scanner.setup_kma_index("card", fasta_source=src, output_dir=out_dir)
        assert result == out_dir / "card_kma"
        assert captured["prefix"] == out_dir / "card_kma"
        assert "KMA index 'card' created" in capsys.readouterr().out

    def test_setup_kma_index_swallows_runtime_error(self, tmp_path, monkeypatch, capsys):
        src = tmp_path / "src.fasta"
        src.write_text(">g\nACGT\n")
        out_dir = tmp_path / "out"

        class FakeKma:
            def __init__(self, *a, **kw):
                raise RuntimeError("kma not found in PATH")

            def make_index(self, fasta, prefix):
                raise RuntimeError("never")

        monkeypatch.setattr("bacmap.core.engine.backends.kma.KmaBackend", FakeKma, raising=True)
        result = gene_scanner.setup_kma_index("card", fasta_source=src, output_dir=out_dir)
        assert result == out_dir / "card_kma"
        assert "KMA not available" in capsys.readouterr().out

    def test_setup_kma_index_no_source_raises(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        import bacmap.core.db as dbm

        monkeypatch.setattr(dbm, "DB_NAME_TO_SOURCE", {})
        with pytest.raises(FileNotFoundError, match="Source FASTA"):
            gene_scanner.setup_kma_index("card", output_dir=out_dir)


class TestSetupAllDatabases:
    def test_iterates_abricate_dir(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        abricate = fake_home / ".pixi" / "envs" / "default" / "db"
        (abricate / "card").mkdir(parents=True)
        (abricate / "card" / "sequences").write_text(">g\nACGT\n")
        (abricate / "empty").mkdir(parents=True)
        (abricate / "junk.txt").write_text("skip me")

        monkeypatch.setattr(Path, "home", lambda: fake_home)

        created: list = []

        def fake_setup_db(name, src, output_dir):
            created.append((name, str(src)))

        monkeypatch.setattr(gene_scanner, "setup_db", fake_setup_db)

        result = gene_scanner.setup_all_databases()
        assert result == ["card"]
        assert created == [("card", str(abricate / "card" / "sequences"))]

    def test_missing_abricate_dir_raises(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        with pytest.raises(FileNotFoundError, match="abricate db directory"):
            gene_scanner.setup_all_databases()

    def test_setup_db_exception_is_caught(self, tmp_path, monkeypatch, capsys):
        fake_home = tmp_path / "home"
        abricate = fake_home / ".pixi" / "envs" / "default" / "db"
        (abricate / "card").mkdir(parents=True)
        (abricate / "card" / "sequences").write_text(">g\nACGT\n")
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        def boom(name, src, output_dir):
            raise RuntimeError("nope")

        monkeypatch.setattr(gene_scanner, "setup_db", boom)
        result = gene_scanner.setup_all_databases()
        assert result == []
        assert "card: nope" in capsys.readouterr().out


class TestMain:
    def test_main_setup_invokes_setup_db(self, monkeypatch):
        called = {}

        def fake_setup_db(name, fasta=None):
            called["name"] = name
            called["fasta"] = fasta
            return Path("/tmp/prefix")

        monkeypatch.setattr(gene_scanner, "setup_db", fake_setup_db)
        monkeypatch.setattr(
            sys, "argv", ["gene_scanner", "ignored.fasta", "--setup", "mydb,/path/to/x.fasta"]
        )
        gene_scanner.main()
        assert called == {"name": "mydb", "fasta": "/path/to/x.fasta"}

    def test_main_setup_all_invokes_setup_all(self, monkeypatch, capsys):
        monkeypatch.setattr(gene_scanner, "setup_all_databases", lambda *a, **kw: ["card", "vfdb"])
        monkeypatch.setattr(sys, "argv", ["gene_scanner", "ignored.fasta", "--setup-all"])
        gene_scanner.main()
        out = capsys.readouterr().out
        assert "Created 2 databases" in out
        assert "card, vfdb" in out

    def test_main_multi_json_output(self, monkeypatch, capsys):
        sr = ScanResult(database="card", input_file="x", min_identity=80.0, min_coverage=80.0)
        sr.genes = [GeneHit("a", 99.0, 100.0, "c", 1, 100, "+")]
        sr.total_hits = 1
        sr.build_summary()
        monkeypatch.setattr(
            gene_scanner,
            "scan_multi",
            lambda *a, **kw: {"card": sr},
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["gene_scanner", "ctgs.fasta", "--multi", "card", "--json"],
        )
        gene_scanner.main()
        out = capsys.readouterr().out
        assert '"card"' in out
        assert '"total_hits": 1' in out

    def test_main_multi_text_output(self, monkeypatch, capsys):
        sr = ScanResult(database="card", input_file="x", min_identity=80.0, min_coverage=80.0)
        sr.genes = [GeneHit("a", 99.0, 100.0, "c", 1, 100, "+")]
        sr.total_hits = 1
        sr.build_summary()
        monkeypatch.setattr(
            gene_scanner,
            "scan_multi",
            lambda *a, **kw: {"card": sr},
        )
        monkeypatch.setattr(sys, "argv", ["gene_scanner", "ctgs.fasta", "--multi", "card"])
        gene_scanner.main()
        out = capsys.readouterr().out
        assert "card: 1 hits" in out
        assert "a\t99.0" in out

    def test_main_single_json(self, monkeypatch, capsys):
        sr = ScanResult(database="card", input_file="x", min_identity=80.0, min_coverage=80.0)
        sr.genes = [GeneHit("a", 99.0, 100.0, "c", 1, 100, "+")]
        sr.total_hits = 1
        sr.build_summary()
        monkeypatch.setattr(gene_scanner, "scan", lambda *a, **kw: sr)
        monkeypatch.setattr(sys, "argv", ["gene_scanner", "ctgs.fasta", "--db", "card", "--json"])
        gene_scanner.main()
        out = capsys.readouterr().out
        assert '"database": "card"' in out

    def test_main_single_tsv(self, monkeypatch, capsys):
        sr = ScanResult(database="card", input_file="x", min_identity=80.0, min_coverage=80.0)
        sr.genes = [
            GeneHit(
                "a",
                99.0,
                100.0,
                "ctg1",
                10,
                200,
                "+",
                accession="ACC1",
            )
        ]
        sr.total_hits = 1
        sr.build_summary()
        monkeypatch.setattr(gene_scanner, "scan", lambda *a, **kw: sr)
        monkeypatch.setattr(sys, "argv", ["gene_scanner", "ctgs.fasta", "--db", "card"])
        gene_scanner.main()
        out = capsys.readouterr().out
        assert "Database: card" in out
        assert "Total hits: 1" in out
        assert "GENE\t%IDENTITY" in out
        assert "a\t99.0\t100.0\tctg1\t10\t200\tACC1" in out


class TestFindDbLazyRebuild:
    """P1-2（评审 B3 教训落地）：索引缺失时 _find_db 懒重建而非抛错。"""

    def test_missing_index_triggers_rebuild(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [tmp_path])

        def fake_setup(db_name: str) -> Path:
            prefix = tmp_path / f"{db_name}_blastdb"
            (tmp_path / f"{db_name}_blastdb.nhr").write_text("")
            return prefix

        monkeypatch.setattr(gene_scanner, "setup_db", fake_setup)
        assert gene_scanner._find_db("species_markers") == (tmp_path / "species_markers_blastdb")

    def test_rebuild_failure_raises_enriched_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gene_scanner, "_DB_SEARCH_PATHS", [tmp_path])

        def fake_setup(db_name: str) -> Path:
            raise FileNotFoundError("no source FASTA")

        monkeypatch.setattr(gene_scanner, "setup_db", fake_setup)
        with pytest.raises(FileNotFoundError, match="auto-rebuild failed"):
            gene_scanner._find_db("whatever")
