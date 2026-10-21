import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.parsing.extractor import ExtractedCall
from backend.app.graph.builder import KnowledgeGraphBuilder
from backend.app.services.indexing_service import IndexingService


def test_repo_authorization_cross_user_isolation(client: TestClient, db_session: Session):
    """
    Regression Test: Verifies cross-user repository isolation.
    An active user cannot view, delete, or trigger indexing on another user's repository.
    """
    # Create another user and their private repository
    other_user = User(
        email="other@example.dev",
        full_name="Other User",
        workspace_name="Other Org",
        avatar_initials="OU",
        is_active=False,
    )
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    foreign_repo = Repository(
        name="secret-backend",
        full_name="other-org/secret-backend",
        user_id=other_user.id,
        status="ready",
    )
    db_session.add(foreign_repo)
    db_session.commit()
    db_session.refresh(foreign_repo)

    # Attempt to retrieve repository details
    res_get = client.get(f"/api/v1/repositories/{foreign_repo.id}")
    assert res_get.status_code == 403
    assert "Access denied" in res_get.json()["detail"]

    # Attempt to delete repository
    res_del = client.delete(f"/api/v1/repositories/{foreign_repo.id}")
    assert res_del.status_code == 403
    assert "Access denied" in res_del.json()["detail"]

    # Attempt to trigger indexing
    res_index = client.post(f"/api/v1/repositories/{foreign_repo.id}/index", json={"branch": "main"})
    assert res_index.status_code == 403
    assert "Access denied" in res_index.json()["detail"]


@pytest.mark.anyio
async def test_indexing_stage_failure_sets_failed_status(db_session: Session):
    """
    Regression Test: Verifies that an unhandled exception in graph construction
    marks the job as FAILED with stage and error_message rather than COMPLETED.
    """
    repo = Repository(
        name="fail-repo",
        full_name="acme/fail-repo",
        status="indexing",
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    job = IndexingJob(
        repository_id=repo.id,
        status="QUEUED",
        stage="QUEUED",
        branch="main",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    # Patch KnowledgeGraphBuilder to simulate unexpected database/build failure
    with patch.object(KnowledgeGraphBuilder, "build_graph_for_repository", side_effect=RuntimeError("Graph node DB corruption")):
        await IndexingService.run_indexing_pipeline(
            job_id=job.id,
            repository_id=repo.id,
            branch="main",
            db_session=db_session,
        )

    db_session.refresh(job)
    db_session.refresh(repo)
    assert job.status == "FAILED"
    assert job.stage == "GRAPH_CONSTRUCTION"
    assert "Graph node DB corruption" in (job.error_message or "")
    assert repo.status == "failed"


def test_cross_file_static_calls_resolved_in_knowledge_graph(db_session: Session):
    """
    Regression Test: Verifies that a function in file A calling a function in file B
    correctly resolves the callee node and builds a verified CALLS edge, even when
    file B appears in the list after file A.
    """
    repo = Repository(
        name="multi-file-repo",
        full_name="acme/multi-file-repo",
        status="ready",
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    file_a = IndexedFile(
        repository_id=repo.id,
        path="src/caller.py",
        language="python",
        lines_count=10,
    )
    file_b = IndexedFile(
        repository_id=repo.id,
        path="src/callee.py",
        language="python",
        lines_count=10,
    )
    db_session.add_all([file_a, file_b])
    db_session.commit()
    db_session.refresh(file_a)
    db_session.refresh(file_b)

    sym_caller = CodeSymbol(
        repository_id=repo.id,
        file_id=file_a.id,
        name="handle_request",
        kind="function",
        start_line=1,
        end_line=5,
    )
    sym_callee = CodeSymbol(
        repository_id=repo.id,
        file_id=file_b.id,
        name="process_payment",
        kind="function",
        start_line=1,
        end_line=5,
    )
    db_session.add_all([sym_caller, sym_callee])
    db_session.commit()
    db_session.refresh(sym_caller)
    db_session.refresh(sym_callee)

    call = ExtractedCall(
        caller_name="handle_request",
        callee_name="process_payment",
        line_number=3,
        evidence="process_payment(req.amount)",
    )

    # Note: file_a is first, file_b is second
    nodes_cnt, edges_cnt = KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[file_a, file_b],
        symbols_by_file={
            file_a.id: [sym_caller],
            file_b.id: [sym_callee],
        },
        calls_by_file={
            file_a.id: [call],
        },
    )

    assert nodes_cnt > 0
    assert edges_cnt > 0

    # Verify that a CALLS edge exists between handle_request and process_payment
    calls_edge = (
        db_session.query(GraphEdge)
        .filter(
            GraphEdge.repository_id == repo.id,
            GraphEdge.edge_type == "CALLS",
        )
        .first()
    )
    assert calls_edge is not None
    assert calls_edge.is_verified is True
    assert "process_payment" in calls_edge.evidence

    source_node = db_session.query(GraphNode).filter(GraphNode.id == calls_edge.source_node_id).first()
    target_node = db_session.query(GraphNode).filter(GraphNode.id == calls_edge.target_node_id).first()
    assert source_node.name == "handle_request"
    assert target_node.name == "process_payment"
