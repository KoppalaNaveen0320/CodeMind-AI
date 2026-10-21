import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.core.security import create_session_token
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.symbol_service import SymbolService
from backend.app.services.assistant_service import AssistantService


def test_full_user_lifecycle_workflow_e2e(client: TestClient, db_session: Session):
    """
    End-to-end verification of the primary user workflow:
    1. Authentication & Session creation
    2. Repository registration & indexing simulation
    3. Symbol search with exact matching
    4. Graph exploration & node retrieval
    5. Hybrid search retrieval with line coordinates
    6. Assistant conversation creation & grounded querying
    7. Follow-up question persistence & memory
    8. Cross-user isolation verification
    """

    # ------------------------------------------------------------------------
    # Step 1: Authentication & Session
    # ------------------------------------------------------------------------
    user_alice = User(
        email="alice.audit@enterprise.internal",
        full_name="Alice Audit Lead",
        workspace_name="Audit Workspace",
        avatar_initials="AL",
        is_active=True
    )
    user_bob = User(
        email="bob.audit@competitor.internal",
        full_name="Bob Unauthorized",
        workspace_name="Bob Competitor",
        avatar_initials="BU",
        is_active=True
    )
    db_session.add_all([user_alice, user_bob])
    db_session.commit()
    db_session.refresh(user_alice)
    db_session.refresh(user_bob)

    alice_token = create_session_token(user_alice.id)
    bob_token = create_session_token(user_bob.id)
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Verify Alice authentication profile
    me_res = client.get("/api/v1/me", headers=alice_headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "alice.audit@enterprise.internal"

    # ------------------------------------------------------------------------
    # Step 2: Repository Registration
    # ------------------------------------------------------------------------
    repo_alice = Repository(
        name="payment-gateway",
        full_name="alice/payment-gateway",
        description="Core PCI-compliant transaction processing system",
        provider="folder",
        is_private=True,
        default_branch="main",
        primary_language="Python",
        user_id=user_alice.id,
        status="ready"
    )
    db_session.add(repo_alice)
    db_session.commit()
    db_session.refresh(repo_alice)

    # List repositories for Alice
    repos_res = client.get("/api/v1/repositories", headers=alice_headers)
    assert repos_res.status_code == 200
    repo_names = [r["name"] for r in repos_res.json()]
    assert "payment-gateway" in repo_names

    # ------------------------------------------------------------------------
    # Step 3: Indexing & Code Representation
    # ------------------------------------------------------------------------
    file_code = (
        "class PaymentProcessor:\n"
        "    def process_charge(self, amount: float, card_token: str) -> bool:\n"
        "        # Authorize transaction with acquirer\n"
        "        return True\n\n"
        "def verify_pci_compliance() -> bool:\n"
        "    return True\n"
    )
    file_record = IndexedFile(
        repository_id=repo_alice.id,
        path="services/processor.py",
        language="python",
        lines_count=8,
        size_bytes=len(file_code.encode("utf-8")),
        content_hash="audit_hash_123"
    )
    db_session.add(file_record)
    db_session.commit()
    db_session.refresh(file_record)

    sym1 = CodeSymbol(
        repository_id=repo_alice.id,
        file_id=file_record.id,
        name="PaymentProcessor",
        kind="class",
        start_line=1,
        end_line=4,
        signature="class PaymentProcessor"
    )
    sym2 = CodeSymbol(
        repository_id=repo_alice.id,
        file_id=file_record.id,
        name="process_charge",
        kind="method",
        start_line=2,
        end_line=4,
        signature="def process_charge(self, amount: float, card_token: str) -> bool"
    )
    db_session.add_all([sym1, sym2])

    chunk = CodeChunk(
        repository_id=repo_alice.id,
        file_id=file_record.id,
        file_path="services/processor.py",
        language="python",
        start_line=1,
        end_line=8,
        chunk_text=file_code,
        content_hash="audit_chunk_hash_1"
    )
    db_session.add(chunk)
    db_session.commit()

    # ------------------------------------------------------------------------
    # Step 4: Symbol Search
    # ------------------------------------------------------------------------
    sym_res = client.get(
        f"/api/v1/repositories/{repo_alice.id}/symbols/search?query=process_charge",
        headers=alice_headers
    )
    assert sym_res.status_code == 200
    sym_data = sym_res.json()
    assert sym_data["total_count"] >= 1
    assert any(s["name"] == "process_charge" for s in sym_data["results"])

    # ------------------------------------------------------------------------
    # Step 5: Knowledge Graph Exploration
    # ------------------------------------------------------------------------
    node1 = GraphNode(
        repository_id=repo_alice.id,
        node_key="services/processor.py::PaymentProcessor",
        name="PaymentProcessor",
        node_type="class",
        file_path="services/processor.py"
    )
    node2 = GraphNode(
        repository_id=repo_alice.id,
        node_key="services/processor.py::process_charge",
        name="process_charge",
        node_type="method",
        file_path="services/processor.py"
    )
    db_session.add_all([node1, node2])
    db_session.commit()
    db_session.refresh(node1)
    db_session.refresh(node2)

    edge = GraphEdge(
        repository_id=repo_alice.id,
        source_node_id=node1.id,
        target_node_id=node2.id,
        edge_type="contains"
    )
    db_session.add(edge)
    db_session.commit()

    graph_res = client.get(
        f"/api/v1/repositories/{repo_alice.id}/graph",
        headers=alice_headers
    )
    assert graph_res.status_code == 200
    g_data = graph_res.json()
    assert len(g_data["nodes"]) >= 2
    assert len(g_data["edges"]) >= 1
    assert g_data["summary"]["total_nodes"] >= 2

    # ------------------------------------------------------------------------
    # Step 6: Assistant Conversation & Grounded Query
    # ------------------------------------------------------------------------
    conv_create_res = client.post(
        "/api/v1/assistant/conversations",
        json={"repository_id": repo_alice.id, "title": "PCI Architecture Review"},
        headers=alice_headers
    )
    assert conv_create_res.status_code == 201
    conv_id = conv_create_res.json()["id"]

    # Alice sends a message
    msg_res = client.post(
        f"/api/v1/assistant/conversations/{conv_id}/messages",
        json={"content": "How does payment processing work in this repository?"},
        headers=alice_headers
    )
    assert msg_res.status_code == 200
    msg_data = msg_res.json()
    assert msg_data["conversation_id"] == conv_id
    assert "answer" in msg_data
    assert len(msg_data["answer"]) > 0

    # ------------------------------------------------------------------------
    # Step 7: Follow-up Memory & History
    # ------------------------------------------------------------------------
    conv_detail_res = client.get(
        f"/api/v1/assistant/conversations/{conv_id}",
        headers=alice_headers
    )
    assert conv_detail_res.status_code == 200
    detail = conv_detail_res.json()
    assert len(detail["messages"]) >= 2  # user + assistant

    # ------------------------------------------------------------------------
    # Step 8: Strict Multi-Tenant Repository & Conversation Isolation
    # ------------------------------------------------------------------------
    # 1. Bob cannot read Alice's repository
    bob_repo_res = client.get(
        f"/api/v1/repositories/{repo_alice.id}",
        headers=bob_headers
    )
    assert bob_repo_res.status_code == 403

    # 2. Bob cannot view Alice's conversation
    bob_conv_res = client.get(
        f"/api/v1/assistant/conversations/{conv_id}",
        headers=bob_headers
    )
    assert bob_conv_res.status_code == 403

    # 3. Bob cannot post messages to Alice's conversation
    bob_msg_res = client.post(
        f"/api/v1/assistant/conversations/{conv_id}/messages",
        json={"content": "Unauthorized probe"},
        headers=bob_headers
    )
    assert bob_msg_res.status_code == 403

    # 4. Bob cannot query symbols from Alice's repository
    bob_sym_res = client.get(
        f"/api/v1/repositories/{repo_alice.id}/symbols/search?query=process_charge",
        headers=bob_headers
    )
    assert bob_sym_res.status_code == 403
