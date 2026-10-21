import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.indexed_file import IndexedFile
from backend.app.core.config import settings


@pytest.fixture
def test_repo_data(db_session: Session):
    user = db_session.query(User).filter(User.is_active == True).first()
    if not user:
        user = User(email="alex@acme.dev", full_name="Alex Kim", workspace_name="Acme", is_active=True)
        db_session.add(user)
        db_session.commit()

    repo = Repository(
        name="test-platform",
        full_name="acme/test-platform",
        user_id=user.id,
        is_private=True,
        default_branch="main",
        status="ready",
    )
    db_session.add(repo)
    db_session.commit()

    # Add a file and chunk
    f = IndexedFile(id=101, repository_id=repo.id, path="src/auth.ts", language="typescript", lines_count=20)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=101,
        file_path="src/auth.ts",
        code_symbol="validateSession",
        chunk_index=0,
        chunk_text="export function validateSession() { return true; }",
        content_hash="ts_chunk_1",
        language="typescript",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)

    # Add graph nodes and edge
    n1 = GraphNode(repository_id=repo.id, node_key="node_1", node_type="file", name="auth.ts", file_path="src/auth.ts")
    n2 = GraphNode(repository_id=repo.id, node_key="node_2", node_type="function", name="validateSession", file_path="src/auth.ts")
    db_session.add_all([n1, n2])
    db_session.commit()

    e1 = GraphEdge(repository_id=repo.id, source_node_id=n1.id, target_node_id=n2.id, edge_type="CONTAINS", is_verified=True)
    db_session.add(e1)
    db_session.commit()

    return {"user": user, "repo": repo, "node1": n1, "node2": n2, "file": f}


def test_embedding_status_api(client: TestClient):
    """Verify system embedding-status endpoint returns truthful diagnostic details."""
    response = client.get("/api/v1/system/embedding-status")
    assert response.status_code == 200
    data = response.json()
    assert "provider" in data
    assert "configured" in data
    assert "dimension" in data
    assert "total_chunks" in data


def test_retrieval_search_api(client: TestClient, test_repo_data):
    """Verify hybrid search endpoint returns matched chunks with coordinates."""
    repo = test_repo_data["repo"]
    payload = {
        "query": "validateSession",
        "top_k": 5,
        "expand_graph": True,
    }
    response = client.post(f"/api/v1/repositories/{repo.id}/retrieval/search", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["results_count"] >= 1
    chunk = data["results"][0]
    assert chunk["file_path"] == "src/auth.ts"
    assert chunk["symbol_name"] == "validateSession"
    assert chunk["start_line"] == 1
    assert chunk["end_line"] == 5


def test_assistant_query_api(client: TestClient, test_repo_data):
    """Verify assistant query returns grounded answer with citations."""
    repo = test_repo_data["repo"]
    payload = {
        "question": "Where is validateSession defined?",
    }
    response = client.post(f"/api/v1/repositories/{repo.id}/assistant/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["citations"]) >= 1
    citation = data["citations"][0]
    assert citation["file_path"] == "src/auth.ts"
    assert "similarity_percent" in citation


def test_graph_endpoints(client: TestClient, test_repo_data):
    """Verify knowledge graph retrieval, node neighbors, and path endpoints."""
    repo = test_repo_data["repo"]
    n1 = test_repo_data["node1"]
    n2 = test_repo_data["node2"]

    # Graph retrieval
    res_graph = client.get(f"/api/v1/repositories/{repo.id}/graph")
    assert res_graph.status_code == 200
    g_data = res_graph.json()
    assert len(g_data["nodes"]) >= 2
    assert len(g_data["edges"]) >= 1

    # Node neighbors
    res_neighbors = client.get(f"/api/v1/repositories/{repo.id}/graph/nodes/{n1.id}/neighbors")
    assert res_neighbors.status_code == 200
    nbr_data = res_neighbors.json()
    assert len(nbr_data["outgoing"]) >= 1

    # Path finding
    res_path = client.get(f"/api/v1/repositories/{repo.id}/graph/paths?start_id={n1.id}&end_id={n2.id}")
    assert res_path.status_code == 200
    path_data = res_path.json()
    assert path_data["path"] is not None
    assert len(path_data["path"]) == 1


def test_impact_analysis_api(client: TestClient, test_repo_data):
    """Verify change-impact prediction endpoint."""
    repo = test_repo_data["repo"]
    payload = {
        "component_name": "auth.ts",
        "proposed_change": "Refactor auth middleware logic",
        "max_depth": 3,
    }
    response = client.post(f"/api/v1/repositories/{repo.id}/impact/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["target_component"] == "auth.ts"
    assert "limitations" in data
    assert "explanation" in data


def test_file_tree_and_content_endpoints(client: TestClient, test_repo_data):
    """Verify code viewer tree and file content endpoints."""
    repo = test_repo_data["repo"]

    # File tree
    res_tree = client.get(f"/api/v1/repositories/{repo.id}/files/tree")
    assert res_tree.status_code == 200
    tree_data = res_tree.json()
    assert len(tree_data) >= 1
    assert tree_data[0]["path"] == "src/auth.ts"

    # File content
    res_content = client.get(f"/api/v1/repositories/{repo.id}/files/content?file_path=src/auth.ts&highlight_start=1&highlight_end=5")
    assert res_content.status_code == 200
    content_data = res_content.json()
    assert content_data["file_path"] == "src/auth.ts"
    assert "export function validateSession" in content_data["content"]
    assert content_data["highlight_start"] == 1


def test_unauthorized_repository_access(client: TestClient, db_session: Session):
    """Verify 403 Forbidden is returned when attempting to access another user's repository."""
    # Logged-in user
    alex = User(email="alex@acme.dev", full_name="Alex Kim", workspace_name="Acme", is_active=True)
    db_session.add(alex)
    db_session.commit()

    # Another user who owns the private repo
    other_user = User(email="other_owner@acme.dev", full_name="Other Owner", is_active=True)
    db_session.add(other_user)
    db_session.commit()

    other_repo = Repository(
        name="private-vault",
        full_name="acme/private-vault",
        user_id=other_user.id,
        is_private=True,
    )
    db_session.add(other_repo)
    db_session.commit()

    # Current user (Alex Kim) tries to access other_repo
    res = client.post(f"/api/v1/repositories/{other_repo.id}/retrieval/search", json={"query": "secret"})
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]
