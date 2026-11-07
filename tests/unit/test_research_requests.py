"""Agent-proposed research requests: draft, inbox, human approval, rejection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.research.models import ResearchRequestStatus
from bacmap.research.service import ResearchRequestService, ResearchService
from bacmap.store import runs
from bacmap.store.genome_object_service import ensure_gom_schema
from bacmap.store.lab_results import LabResultService


def _build_home(home: Path) -> None:
    wf = home / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 2\niqu_tree_seed: 42\n")
    strains = [f"S{i:02d}" for i in range(10)]
    run = runs.create_run(
        "bacmap", wf, strains, db_path=home / "runs.sqlite", task_id="task-1"
    )
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute(
            "UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", ("run-1", run.run_id)
        )
    ensure_gom_schema(home / "gom.sqlite")
    with sqlite3.connect(home / "gom.sqlite") as conn:
        for i, sid in enumerate(strains):
            if i < 5:
                conn.execute(
                    "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                    " VALUES (?,?,?)",
                    (sid, "blaKPC-33", "card"),
                )
    with LabResultService(home / "data" / "bacmap.sqlite") as svc:
        for i, sid in enumerate(strains):
            svc.add(
                sid,
                "mic",
                "meropenem",
                "0.25",
                interpretation="R" if i < 4 else "S",
            )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    _build_home(tmp_path)
    return tmp_path


def test_propose_list_and_get(home: Path):
    svc = ResearchRequestService(home)
    request = svc.propose_request(
        "Does blaKPC-33 associate with meropenem?",
        pathogen_scope="KPN",
        run_ids=["run-1"],
        gene="blaKPC-33",
        test_name="meropenem",
        note="agent draft",
        actor="agent",
    )
    assert request.status is ResearchRequestStatus.PROPOSED
    assert request.request_id.startswith("rr-")
    items = svc.list_requests(status="proposed")
    assert [item.request_id for item in items] == [request.request_id]
    assert svc.get_request(request.request_id).question == request.question


def test_approve_creates_study_cohort_plan_and_session(home: Path):
    svc = ResearchRequestService(home)
    request = svc.propose_request(
        "Does blaKPC-33 associate with meropenem?",
        pathogen_scope="KPN",
        run_ids=["run-1"],
        gene="blaKPC-33",
        test_name="meropenem",
        note="agent draft",
        actor="agent",
    )
    reviewed = svc.approve_request(request.request_id, actor="web", note="approved")
    assert reviewed.status is ResearchRequestStatus.APPROVED
    assert reviewed.study_id
    assert reviewed.cohort_id
    assert reviewed.plan_id
    assert reviewed.session_id
    view = ResearchService(home).get_session(reviewed.session_id)
    assert view.session.study_id == reviewed.study_id
    assert view.session.cohort_id == reviewed.cohort_id
    assert view.session.plan_id == reviewed.plan_id
    assert view.session.payload["note"] == "agent draft"


def test_approve_with_explicit_members_and_spec(home: Path):
    svc = ResearchRequestService(home)
    request = svc.propose_request(
        "Phylogenetic question",
        run_ids=["run-1"],
        analysis="phylo",
        actor="agent",
    )
    reviewed = svc.approve_request(
        request.request_id,
        members=[{"isolate_id": "S00", "run_id": "run-1"}],
        plan_spec={"analysis": "phylo", "alignment": "/tmp/a.fasta"},
        actor="web",
    )
    assert reviewed.status is ResearchRequestStatus.APPROVED
    assert reviewed.cohort_id
    assert reviewed.plan_id
    assert not reviewed.session_id


def test_reject_request(home: Path):
    svc = ResearchRequestService(home)
    request = svc.propose_request("Reject me", actor="agent")
    rejected = svc.reject_request(request.request_id, actor="web", note="not needed")
    assert rejected.status is ResearchRequestStatus.REJECTED
    with pytest.raises(Exception, match="already rejected"):
        svc.approve_request(request.request_id, actor="web")


def test_unknown_run_is_rejected(home: Path):
    svc = ResearchRequestService(home)
    request = svc.propose_request(
        "Unknown run", run_ids=["nope"], gene="g", test_name="t", actor="agent"
    )
    with pytest.raises(Exception, match="no such run"):
        svc.approve_request(request.request_id, actor="web")


def test_mcp_request_tool_proposes_draft(home: Path):
    import asyncio
    import json

    from types import SimpleNamespace

    from bacmap.interfaces.mcp.profiles import McpProfile, ProfileSpec
    from bacmap.interfaces.mcp.server import build_server
    from bacmap.tools.spec import DataClass

    profile = ProfileSpec(
        profile=McpProfile.LOCAL_TRUSTED,
        max_data_class=DataClass.D4,
        actor="mcp-test",
    )
    engine = SimpleNamespace(home=home, db=home / "tasks.sqlite")
    server = build_server(engine, profile)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "bacmap_research_request" in names
    assert "bacmap_research_requests" in names
    result = asyncio.run(
        server.call_tool(
            "bacmap_research_request",
            {
                "question": "MCP proposed question",
                "run_ids": ["run-1"],
                "gene": "blaKPC-33",
                "test_name": "meropenem",
                "note": "from MCP",
            },
        )
    )
    payload = json.loads(result.content[0].text)
    assert payload["status"] == "proposed"
    assert payload["request_id"].startswith("rr-")
    listed = asyncio.run(server.call_tool("bacmap_research_requests", {}))
    items = json.loads(listed.content[0].text)
    assert items[0]["request_id"] == payload["request_id"]
