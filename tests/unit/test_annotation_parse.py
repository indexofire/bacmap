"""Bakta + eggNOG-mapper 注释解析与合并测试（v1.10.14）。"""

from __future__ import annotations

from bacmap.core.annotation_parse import merge_annotation, parse_bakta, parse_eggnog

BAKTA = {
    "stats": {
        "size": 5_000_000,
        "gc": 0.51,
        "coding_density": 0.88,
        "cds": {"count": 4},
        "rrna": {"count": 3},
        "trna": {"count": 20},
        "tmrna": {"count": 1},
        "ncrna": {"count": 2},
        "crispr": {"count": 1},
        "orfs": {"count": 5},
        "pseudogenes": {"count": 0},
    },
    "features": [
        {
            "type": "cds",
            "contig": "c1",
            "start": 10,
            "stop": 100,
            "strand": "+",
            "gene": "gyrA",
            "locus": "S1_0001",
            "product": "DNA gyrase subunit A",
        },
        {
            "type": "cds",
            "contig": "c1",
            "start": 200,
            "stop": 300,
            "strand": "-",
            "gene": "unknown",
            "locus": "S1_0002",
            "product": "hypothetical protein",
        },
        {
            "type": "cds",
            "contig": "c1",
            "start": 400,
            "stop": 500,
            "strand": "+",
            "gene": "blaCTX-M-15",
            "locus": "S1_0003",
            "product": "beta-lactamase CTX-M-15",
        },
        {
            "type": "cds",
            "contig": "c1",
            "start": 600,
            "stop": 700,
            "strand": "+",
            "gene": "tetA",
            "locus": "S1_0004",
            "product": "tetracycline resistance protein TetA",
        },
        {
            "type": "trna",
            "contig": "c1",
            "start": 800,
            "stop": 880,
            "strand": "+",
            "gene": "tRNA-Ala",
            "product": "tRNA-Ala",
        },
    ],
}

EGGNOG = """## emapper-2.1.12
#query\tseed_ortholog\tevalue\tscore\teggNOG_OGs\tmax_annot_lvl\tCOG_category\tDescription\tPreferred_name\tGOs\tEC\tKEGG_ko\tKEGG_Pathway\tKEGG_Module\tKEGG_Reaction\tKEGG_rclass\tBRITE\tKEGG_TC\tCAZy\tBiGG_Reaction\tPFAMs
S1_0001\t1.abc\t1e-90\t500\tCOG0187@1|root\tBacteria\tJ\tDNA gyrase subunit A\tgyrA\tGO:0003918\t5.99.1.3\tK00006\tmap00240\t-\t-\t-\t-\t-\t-\t-\tPF00001
S1_0002\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-
S1_0003\t2.def\t1e-80\t450\tCOG1680@1|root\tBacteria\tV\tbeta-lactamase CTX-M-15\tblaCTX-M-15\t-\t3.5.2.6\tK18698\t-\t-\t-\t-\t-\t-\t-\t-\tPF00002
S1_0004\t3.ghi\t1e-70\t400\tCOG0694@1|root\tBacteria\tV\tTetracycline resistance protein\tTetA\t-\t-\tK08151\t-\t-\t-\t-\t-\t-\t-\t-\tPF00003
"""


def test_parse_bakta_counts_and_features():
    parsed = parse_bakta(BAKTA)
    assert parsed["total_cds"] == 4
    assert parsed["annotated_cds"] == 3
    assert parsed["stats"]["rrna"] == 3
    assert parsed["stats"]["orfs"] == 5
    assert [f["gene"] for f in parsed["features"]] == [
        "gyrA",
        "unknown",
        "blaCTX-M-15",
        "tetA",
    ]
    assert parsed["features"][1]["hypothetical"] is True


def test_parse_eggnog_skips_comments_and_normalises_dash():
    rows = parse_eggnog(EGGNOG)
    assert len(rows) == 4
    assert rows[0]["query"] == "S1_0001"
    assert rows[0]["COG_category"] == "J"
    assert rows[1]["seed_ortholog"] == ""
    assert rows[1]["COG_category"] == ""


def test_merge_annotation_summary_and_attachment():
    result = merge_annotation(BAKTA, parse_eggnog(EGGNOG), sample="S1")
    assert result["schema"] == "bacmap.annotation/1"
    assert result["status"] == "ok"
    summary = result["summary"]
    assert summary["total_CDS"] == 4
    assert summary["annotated_CDS"] == 3
    assert summary["annotation_rate"] == 0.75
    assert summary["bakta"]["trna"] == 20
    egg = summary["eggnog"]
    assert egg["queries"] == 4
    assert egg["annotated"] == 3
    assert egg["cog_category_counts"] == {"J": 1, "V": 2}
    assert egg["go_term_count"] == 1
    assert egg["kegg_ko_count"] == 3
    assert egg["pfam_count"] == 3

    gyra = next(f for f in result["features"] if f["gene"] == "gyrA")
    assert gyra["eggnog"]["cog_category"] == "J"
    assert gyra["eggnog"]["preferred_name"] == "gyrA"
    assert gyra["eggnog"]["gos"] == ["GO:0003918"]


def test_annotation_rate_zero_without_cds():
    result = merge_annotation({"stats": {"cds": {"count": 0}}, "features": []}, [], sample="S0")
    assert result["summary"]["annotation_rate"] == 0.0
    assert result["features"] == []
