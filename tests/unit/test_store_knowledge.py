"""本地文献知识库测试（引用门后端：暂存→人审→可引用；FTS 检索）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.store.knowledge import KnowledgeStore
from bacmap.tasks.gates import evaluate_citation


def _store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "data" / "knowledge.sqlite")


def _pmid_entry(identifier: str = "PMID:36626432") -> dict:
    return {
        "kind": "literature",
        "title": "Salmonella outbreak investigation via cgMLST",
        "authors": "Zhang et al.",
        "year": 2023,
        "source": "Emerging Infectious Diseases",
        "identifier": identifier,
        "content": "cgMLST 溯源在某省沙门氏菌暴发调查中的应用要点。",
    }


class TestKnowledgeStore:
    def test_import_then_approve_flow(self, tmp_path: Path):
        ks = _store(tmp_path)
        kid = ks.import_candidate(_pmid_entry(), imported_by="literature-agent")
        assert ks.get(kid)["approved_by"] is None
        assert ks.list_pending() and ks.list_pending()[0]["id"] == kid
        assert ks.known_citations() == []  # 未人审 → 不可引用

        ks.approve(kid, approver="curator-mark")
        assert ks.known_citations() == ["36626432"]  # PMID 前缀规范化为纯数字（与引用门对齐）
        assert ks.list_pending() == []

    def test_fts_search_by_keyword(self, tmp_path: Path):
        ks = _store(tmp_path)
        kid = ks.import_candidate(_pmid_entry(), imported_by="a")
        hits = ks.search("cgMLST")
        assert [h["id"] for h in hits] == [kid]
        assert ks.search("不存在的关键词") == []

    def test_title_required(self, tmp_path: Path):
        ks = _store(tmp_path)
        try:
            ks.import_candidate({"title": "  "}, imported_by="a")
            raise AssertionError("should reject empty title")
        except ValueError:
            pass

    def test_approve_missing_raises(self, tmp_path: Path):
        ks = _store(tmp_path)
        try:
            ks.approve(999, approver="a")
            raise AssertionError("should raise KeyError")
        except KeyError:
            pass

    def test_reopen_is_idempotent(self, tmp_path: Path):
        db = tmp_path / "data" / "knowledge.sqlite"
        ks1 = KnowledgeStore(db)
        kid = ks1.import_candidate(_pmid_entry(), imported_by="a")
        ks2 = KnowledgeStore(db)  # 重开 → DDL 幂等，数据仍在
        assert ks2.get(kid) is not None


class TestCitationGateBackend:
    def test_gate_pass_with_approved_entry(self, tmp_path: Path):
        ks = _store(tmp_path)
        kid = ks.import_candidate(_pmid_entry("PMID:11111111"), imported_by="a")
        ks.approve(kid, approver="m")
        draft = "结论见文献 [PMID:11111111]。"
        res = evaluate_citation(
            {"draft": draft, "known_citations": ks.known_citations()}
        )
        assert res.verdict.value == "pass"

    def test_gate_rejects_unapproved_only_entry(self, tmp_path: Path):
        ks = _store(tmp_path)
        ks.import_candidate(_pmid_entry("PMID:22222222"), imported_by="a")
        res = evaluate_citation(
            {"draft": "见 [PMID:22222222]", "known_citations": ks.known_citations()}
        )
        assert res.verdict.value == "reject"
        assert res.details["unknown"] == ["22222222"]


class TestSearchRobustness:
    """FTS5 查询健壮性：任意用户输入不得触发语法错误（修复前：AND/引号/括号直接抛异常）。"""

    def test_no_exception_on_fts_hostile_input(self, tmp_path: Path):
        ks = _store(tmp_path)
        kid = ks.import_candidate(_pmid_entry(), imported_by="a")
        for q in ("cgMLST AND", 'quote"unbalanced', "raw (paren", "*", ' NEAR ', ""):
            hits = ks.search(q)
            assert isinstance(hits, list)
        assert [h["id"] for h in ks.search("cgMLST")] == [kid]

    def test_doi_identifier_lowercased_in_known(self, tmp_path: Path):
        ks = _store(tmp_path)
        kid = ks.import_candidate(
            {"title": "t", "identifier": "10.1128/JCM.00123-23"}, imported_by="a"
        )
        ks.approve(kid, approver="m")
        assert ks.known_citations() == ["10.1128/jcm.00123-23"]


class TestGosSearchErrorPropagation:
    """深度审计循环 5：GOS search 不得吞掉 OperationalError（锁/IO 错误静默返回空结果）。"""

    def test_search_propagates_operational_errors(self, tmp_path: Path):
        import sqlite3

        from bacmap.store.genome_object_service import GenomeObjectService

        gos = GenomeObjectService(tmp_path / "gom.sqlite")

        class _BoomConn:
            def execute(self, *a, **k):
                raise sqlite3.OperationalError("database is locked")

            def close(self) -> None:
                return None

        gos._conn = _BoomConn()  # noqa: SLF001
        with pytest.raises(sqlite3.OperationalError):
            gos.search("anything")
        gos.close()


class TestFtsUpdateTrigger:
    """知识库 FTS 索引随 UPDATE 同步（此前缺 AU 触发器，更新后检索失真）。"""

    def test_updated_title_is_reindexed(self, tmp_path: Path):
        import sqlite3

        ks = _store(tmp_path)
        kid = ks.import_candidate(_pmid_entry(), imported_by="a")
        assert ks.search("cgMLST")

        conn = sqlite3.connect(ks.db)
        with conn:
            conn.execute(
                "UPDATE knowledge_entries SET title = ? WHERE id = ?",
                ("Vibrio parahaemolyticus surveillance", kid),
            )
        conn.close()

        assert [h["id"] for h in ks.search("parahaemolyticus")] == [kid]
        assert ks.search("Salmonella outbreak") == []
