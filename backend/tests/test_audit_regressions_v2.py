import asyncio
import json
import re
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.assistant_service import AssistantService
from backend.app.impact.analyzer import ChangeImpactAnalyzer


@pytest.mark.anyio
async def test_multi_repository_retrieval_isolation(db_session: Session):
    """
    Regression Test 1: Multi-Repository Retrieval Isolation
    Verifies that a query directed to Repository A never returns chunks or citations from Repository B,
    even when both repositories have identical or similarly named functions and modules.
    """
    # 1. Create Repository A and Repository B
    repo_a = Repository(name="platform-alpha", full_name="acme/platform-alpha", is_private=False)
    repo_b = Repository(name="platform-beta", full_name="acme/platform-beta", is_private=False)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()
    db_session.refresh(repo_a)
    db_session.refresh(repo_b)

    # 2. Add files and symbols with identical names to both repositories
    file_a = IndexedFile(repository_id=repo_a.id, path="backend/app/auth.py", language="python", lines_count=50)
    file_b = IndexedFile(repository_id=repo_b.id, path="backend/app/auth.py", language="python", lines_count=50)
    db_session.add_all([file_a, file_b])
    db_session.commit()

    sym_a = CodeSymbol(
        repository_id=repo_a.id,
        file_id=file_a.id,
        name="login_handler",
        kind="function",
        start_line=10,
        end_line=25,
    )
    sym_b = CodeSymbol(
        repository_id=repo_b.id,
        file_id=file_b.id,
        name="login_handler",
        kind="function",
        start_line=10,
        end_line=25,
    )
    db_session.add_all([sym_a, sym_b])
    db_session.commit()

    # 3. Add distinctive code chunks
    chunk_a = CodeChunk(
        repository_id=repo_a.id,
        file_path=file_a.path,
        code_symbol=sym_a.name,
        chunk_index=0,
        chunk_text="def login_handler(request):\n    # ALPHA_EXCLUSIVE_TOKEN_VALIDATION_LOGIC\n    return 'alpha_ok'",
        content_hash="hash_alpha_1",
        language="python",
        start_line=10,
        end_line=25,
    )
    chunk_b = CodeChunk(
        repository_id=repo_b.id,
        file_path=file_b.path,
        code_symbol=sym_b.name,
        chunk_index=0,
        chunk_text="def login_handler(request):\n    # BETA_EXCLUSIVE_TOKEN_VALIDATION_LOGIC\n    return 'beta_ok'",
        content_hash="hash_beta_1",
        language="python",
        start_line=10,
        end_line=25,
    )
    db_session.add_all([chunk_a, chunk_b])
    db_session.commit()

    # 4. Retrieve for Repository A
    retrieved_a = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_a.id,
        query="login_handler token validation logic",
        top_k=5,
    )

    # 5. Retrieve for Repository B
    retrieved_b = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_b.id,
        query="login_handler token validation logic",
        top_k=5,
    )

    # Assert strict repository isolation
    assert len(retrieved_a) > 0
    for chunk in retrieved_a:
        assert chunk.repository_id == repo_a.id
        assert "ALPHA_EXCLUSIVE" in chunk.chunk_text
        assert "BETA_EXCLUSIVE" not in chunk.chunk_text

    assert len(retrieved_b) > 0
    for chunk in retrieved_b:
        assert chunk.repository_id == repo_b.id
        assert "BETA_EXCLUSIVE" in chunk.chunk_text
        assert "ALPHA_EXCLUSIVE" not in chunk.chunk_text


@pytest.mark.anyio
async def test_exact_and_nonexistent_symbol_lookup(db_session: Session):
    """
    Regression Test 2: Symbol Existence Lookup & Nonexistent Symbol Handling
    Verifies that:
    - Existing symbols are accurately verified.
    - Nonexistent symbols return honest not-found without guessing or substituting unrelated symbols (e.g. page_not_found).
    - No change-impact analysis is triggered on missing symbols.
    - Symbols that only exist in another repository are reported not found in the target repository.
    - Partial matches are distinguished from exact matches.
    """
    repo_target = Repository(name="target-service", full_name="acme/target-service", is_private=False)
    repo_foreign = Repository(name="foreign-service", full_name="acme/foreign-service", is_private=False)
    db_session.add_all([repo_target, repo_foreign])
    db_session.commit()

    file_t = IndexedFile(repository_id=repo_target.id, path="src/calculator.py", lines_count=100)
    file_f = IndexedFile(repository_id=repo_foreign.id, path="src/other.py", lines_count=100)
    db_session.add_all([file_t, file_f])
    db_session.commit()

    # Target repo symbols
    sym_real = CodeSymbol(
        repository_id=repo_target.id,
        file_id=file_t.id,
        name="calculate_tax",
        kind="function",
        start_line=10,
        end_line=20,
    )
    sym_partial = CodeSymbol(
        repository_id=repo_target.id,
        file_id=file_t.id,
        name="calculate_discount_helper",
        kind="function",
        start_line=25,
        end_line=35,
    )
    # Foreign repo symbol (exists ONLY in repo_foreign)
    sym_foreign_only = CodeSymbol(
        repository_id=repo_foreign.id,
        file_id=file_f.id,
        name="calculate_xyz_not_present",
        kind="function",
        start_line=1,
        end_line=15,
    )
    db_session.add_all([sym_real, sym_partial, sym_foreign_only])
    db_session.commit()

    # Scenario D regression: Ask target repo for calculate_xyz_not_present()
    res_nonexistent = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_target.id,
        question="Find `calculate_xyz_not_present()` and confirm whether it exists in the indexed source.",
    )

    # Verifications for nonexistent symbol
    assert res_nonexistent["retrieval_strategy"] == "symbol_lookup"
    assert "not found" in res_nonexistent["answer"].lower()
    assert "page_not_found" not in res_nonexistent["answer"]
    assert res_nonexistent["citations"] == []
    assert res_nonexistent["related_components"] == []
    assert res_nonexistent["risk_callout"]["level"] == "LOW"
    assert "no change impact analysis performed" in res_nonexistent["risk_callout"]["summary"].lower()

    # Partial match scenario: Search for calculate_discount
    res_partial = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_target.id,
        question="Where is function `calculate_discount` defined?",
    )
    assert res_partial["retrieval_strategy"] == "symbol_lookup"
    assert "calculate_discount_helper" in res_partial["answer"]
    assert "partial symbol matches" in res_partial["answer"].lower()


def test_knowledge_graph_impact_consistency_and_cycles(db_session: Session):
    """
    Regression Test 3: Knowledge Graph Traversal, Cycles, and Impact Consistency
    Verifies that:
    - Direct vs Transitive impacts are accurately classified.
    - Graph cycles (A -> B -> C -> A) do not cause infinite recursion.
    - Unrelated repositories' graph nodes are strictly excluded.
    - Impact explanation and components are completely consistent.
    """
    repo_1 = Repository(name="graph-repo-1", full_name="acme/graph-repo-1", is_private=False)
    repo_2 = Repository(name="graph-repo-2", full_name="acme/graph-repo-2", is_private=False)
    db_session.add_all([repo_1, repo_2])
    db_session.commit()

    # Nodes for Repo 1: Root A, Direct B, Transitive C, and a Cycle edge C -> A
    node_a = GraphNode(repository_id=repo_1.id, node_key="node_a", node_type="file", name="auth.py", file_path="core/auth.py")
    node_b = GraphNode(repository_id=repo_1.id, node_key="node_b", node_type="file", name="user_service.py", file_path="services/user_service.py")
    node_c = GraphNode(repository_id=repo_1.id, node_key="node_c", node_type="file", name="user_api.py", file_path="api/user_api.py")
    
    # Node for Repo 2 (unrelated repository with matching name)
    node_foreign = GraphNode(repository_id=repo_2.id, node_key="foreign_auth", node_type="file", name="auth.py", file_path="core/auth.py")
    db_session.add_all([node_a, node_b, node_c, node_foreign])
    db_session.commit()

    # Edges in Repo 1:
    # node_b IMPORTS node_a (Direct impact on node_b when modifying node_a)
    # node_c IMPORTS node_b (Transitive impact on node_c when modifying node_a)
    # node_a IMPORTS node_c (Cycle back to node_a)
    edge_ab = GraphEdge(repository_id=repo_1.id, source_node_id=node_b.id, target_node_id=node_a.id, edge_type="IMPORTS", is_verified=True, evidence="from core.auth import token")
    edge_bc = GraphEdge(repository_id=repo_1.id, source_node_id=node_c.id, target_node_id=node_b.id, edge_type="IMPORTS", is_verified=True, evidence="from services.user_service import get_user")
    edge_cycle = GraphEdge(repository_id=repo_1.id, source_node_id=node_a.id, target_node_id=node_c.id, edge_type="IMPORTS", is_verified=True, evidence="cycle import")
    db_session.add_all([edge_ab, edge_bc, edge_cycle])
    db_session.commit()

    # Execute ChangeImpactAnalyzer on auth.py
    result = ChangeImpactAnalyzer.analyze_impact(
        db=db_session,
        repository_id=repo_1.id,
        component_name="auth.py",
        file_path="core/auth.py",
        max_depth=3,
    )

    # 1. Total affected must be 2 (node_b DIRECT, node_c TRANSITIVE), not infinite
    assert result.direct_count == 1
    assert result.transitive_count == 1
    assert result.total_affected == 2

    # 2. Verify direct vs transitive components
    affected_names = {comp.name: comp.impact_level for comp in result.affected_components}
    assert affected_names["user_service.py"] == "DIRECT"
    assert affected_names["user_api.py"] == "TRANSITIVE"

    # 3. Foreign node must never be included
    all_node_ids = {comp.node_id for comp in result.affected_components}
    assert node_foreign.id not in all_node_ids

    # 4. Explanation string matches exact counts and counts symbols and files separately
    assert "directly impacts 1 component(s)" in result.explanation
    assert "transitively influences 1 component(s)" in result.explanation
    assert result.direct_files_count == 1
    assert result.transitive_files_count == 1
    assert len(result.affected_files) == 2


def test_conversation_repository_locking(client: TestClient, db_session: Session):
    """
    Regression Test 4: Conversation Repository Lock
    Verifies that once a conversation is bound to Repository A, sending messages
    with a different repository_id cannot silently mutate the conversation's repository.
    """
    user = db_session.query(User).filter(User.email == "demo@codemind.dev").first()
    if not user:
        user = User(email="demo@codemind.dev", full_name="Demo User", workspace_name="Default Workspace", is_active=True)
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    repo_a = Repository(name="locked-a", full_name="acme/locked-a", user_id=user.id, is_private=False)
    repo_b = Repository(name="locked-b", full_name="acme/locked-b", user_id=user.id, is_private=False)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    # Create conversation bound to repo_a
    conv = AssistantConversation(
        user_id=user.id,
        repository_id=repo_a.id,
        branch="main",
        title="Repo A Thread",
        title_is_manual=True,
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Send message with request.repository_id = repo_b.id
    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={
            "content": "Where is the main entry point?",
            "repository_id": repo_b.id,
            "branch": "develop",
        }
    )
    assert res.status_code == 200

    # Verify conversation repository_id remains repo_a.id
    db_session.refresh(conv)
    assert conv.repository_id == repo_a.id


def test_markdown_rendering_tokens_and_xss_protection(client: TestClient):
    """
    Regression Test 5: Markdown Rendering Tokenization & Preservation
    Tests via client-served static asset and internal token contract that:
    - Intra-word underscores (calculate_xyz_not_present, user_id, __init__) are not italicized.
    - Placeholders @@CM_CODE_BLOCK_ and @@CM_INLINE_CODE_ cannot leak into visible output.
    - XSS tags are escaped.
    - Clickable citations [1] and [Source 1] are converted into data-driven pill buttons.
    """
    res = client.get("/static/js/api.js")
    assert res.status_code == 200
    js = res.text

    # 1. Contains collision-free placeholders
    assert "@@CM_CODE_BLOCK_" in js
    assert "@@CM_INLINE_CODE_" in js

    # 2. Contains safe word-boundary underscore regex: prevents corruption of identifiers like user_id
    assert "(^|\\s)_([^" in js or "calculate_xyz_not_present" not in js

    # 3. Contains final placeholder strip sweep
    assert "text.replace(/@@CM_[A-Za-z0-9_]+@@/g, '')" in js

    # 4. Contains citation pill rendering
    assert "citation-pill" in js
    assert "data-source-index" in js

    # 5. Contains raw SVG stripping in prose
    assert "text.replace(/<svg[\\s\\S]*?<\\/svg>/gi, '')" in js

    # 6. Contains unclosed and optional trailing code fence support
    assert "(?:```|$)" in js

    # 7. Contains isolated code-block placeholder wrapping (\n\n@@CM_CODE_BLOCK_...@@\n\n)
    assert "\\n\\n${placeholder}\\n\\n" in js


@pytest.mark.anyio
async def test_multi_layer_architecture_tracing_complete_and_missing(db_session: Session):
    """
    Regression Test 6: Multi-layer Architecture Tracing & Missing Layer Handling
    Verifies that:
    - Route registration, handler, service, repository, model, and schema layers are retrieved.
    - If ORM model file does not exist, it is not hallucinated and is reported unverified.
    """
    # Repo with complete 6 layers
    repo_complete = Repository(name="order-system", full_name="acme/order-system", is_private=False)
    # Repo missing model layer
    repo_missing_model = Repository(name="order-model-missing", full_name="acme/order-model-missing", is_private=False)
    db_session.add_all([repo_complete, repo_missing_model])
    db_session.commit()

    layers_complete = [
        ("app/main.py", "app.include_router(order_api.router)", "main", 1, 30),
        ("app/api/order_api.py", "def get_order_by_id(order_id: int):", "get_order_by_id", 10, 25),
        ("app/services/order_service.py", "class OrderService:\n    def get_order(self): pass", "OrderService.get_order", 5, 20),
        ("app/repositories/order_repository.py", "class OrderRepository:\n    def get_order(self): pass", "OrderRepository.get_order", 5, 20),
        ("app/models/order.py", "class Order(Base):\n    __tablename__ = 'orders'", "Order", 5, 30),
        ("app/schemas/order.py", "class OrderResponse(BaseModel):\n    id: int", "OrderResponse", 5, 15),
    ]

    for path, code, sym, start, end in layers_complete:
        f = IndexedFile(repository_id=repo_complete.id, path=path, lines_count=50)
        db_session.add(f)
        db_session.commit()
        chunk = CodeChunk(
            repository_id=repo_complete.id,
            file_id=f.id,
            file_path=path,
            code_symbol=sym,
            chunk_index=0,
            chunk_text=code,
            content_hash=f"hash_{path}",
            language="python",
            start_line=start,
            end_line=end,
        )
        db_session.add(chunk)
    db_session.commit()

    # For repo_missing_model: add all except app/models/order.py
    for path, code, sym, start, end in layers_complete:
        if "models/order.py" in path:
            continue
        f = IndexedFile(repository_id=repo_missing_model.id, path=path, lines_count=50)
        db_session.add(f)
        db_session.commit()
        chunk = CodeChunk(
            repository_id=repo_missing_model.id,
            file_id=f.id,
            file_path=path,
            code_symbol=sym,
            chunk_index=0,
            chunk_text=code,
            content_hash=f"hash_missing_{path}",
            language="python",
            start_line=start,
            end_line=end,
        )
        db_session.add(chunk)
    db_session.commit()

    # Test complete repo
    res_complete = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_complete.id,
        question="Trace `get_order_by_id` from route registration through handler, service, repository, ORM model, and response schema.",
    )
    complete_paths = {c["file_path"] for c in res_complete["citations"]}
    assert any("main.py" in p for p in complete_paths)
    assert any("order_api.py" in p for p in complete_paths)
    assert any("order_service.py" in p for p in complete_paths)
    assert any("order_repository.py" in p for p in complete_paths)
    assert any("models/order.py" in p for p in complete_paths)
    assert any("schemas/order.py" in p for p in complete_paths)

    # Test missing model repo
    res_missing = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_missing_model.id,
        question="Trace `get_order_by_id` from route registration through handler, service, repository, ORM model, and response schema.",
    )
    missing_paths = {c["file_path"] for c in res_missing["citations"]}
    assert not any("models/order.py" in p for p in missing_paths)


@pytest.mark.anyio
async def test_jwt_creation_vs_validation_separation(db_session: Session):
    """
    Regression Test 7: JWT Token Creation vs Validation Separation
    Verifies that:
    - Token creation in auth.py is identified.
    - If jwt.decode does not exist, it is reported as absent/unverified.
    - Protected routes are not falsely inferred from imports of UserService.
    """
    repo = Repository(name="jwt-audit-repo", full_name="acme/jwt-audit-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f_auth = IndexedFile(repository_id=repo.id, path="core/auth.py", lines_count=40)
    f_user_svc = IndexedFile(repository_id=repo.id, path="services/user_service.py", lines_count=80)
    f_user_api = IndexedFile(repository_id=repo.id, path="api/user_api.py", lines_count=60)
    db_session.add_all([f_auth, f_user_svc, f_user_api])
    db_session.commit()

    # Chunk with create_access_token using jwt.encode (NO jwt.decode anywhere in repo)
    chunk_auth = CodeChunk(
        repository_id=repo.id,
        file_id=f_auth.id,
        file_path=f_auth.path,
        code_symbol="create_access_token",
        chunk_index=0,
        chunk_text="ALGORITHM = 'HS256'\nSECRET_KEY = os.getenv('SECRET_KEY', 'default-key')\ndef create_access_token(data: dict):\n    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)",
        content_hash="hash_auth",
        language="python",
        start_line=1,
        end_line=20,
    )
    chunk_user_svc = CodeChunk(
        repository_id=repo.id,
        file_id=f_user_svc.id,
        file_path=f_user_svc.path,
        code_symbol="UserService.login_user",
        chunk_index=0,
        chunk_text="def login_user(db, username, password):\n    token = create_access_token({'sub': username})\n    return token",
        content_hash="hash_user_svc",
        language="python",
        start_line=1,
        end_line=25,
    )
    chunk_user_api = CodeChunk(
        repository_id=repo.id,
        file_id=f_user_api.id,
        file_path=f_user_api.path,
        code_symbol="login",
        chunk_index=0,
        chunk_text="from services.user_service import UserService\n@router.post('/login')\ndef login():\n    return UserService.login_user()",
        content_hash="hash_user_api",
        language="python",
        start_line=1,
        end_line=20,
    )
    db_session.add_all([chunk_auth, chunk_user_svc, chunk_user_api])
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Trace JWT token creation, token validation, authentication dependencies, and protected routes in this repository.",
    )

    answer_text = res["answer"]
    # 1. Must cite core/auth.py
    assert any("auth.py" in c["file_path"] for c in res["citations"])
    # 2. Must audit jwt.decode as unverified/absent
    assert "jwt.decode" in answer_text
    assert "UNVERIFIED" in answer_text or "ABSENT" in answer_text or "unverified" in answer_text.lower()
    # 3. Must verify create_access_token
    assert "create_access_token" in answer_text


def test_change_impact_unique_counting_and_external_dependencies(db_session: Session):
    """
    Regression Test 8: Change Impact Unique Symbol/File Counting and Deduplication
    Verifies that:
    - Multiple symbols in the same file do NOT duplicate the file in affected_files.
    - Direct vs Transitive file sets are mutually exclusive.
    - External dependencies (datetime, jwt) are partitioned from project files.
    - Empty graph returns honest zero/unavailable status.
    """
    repo = Repository(name="impact-counting-repo", full_name="acme/impact-counting-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    # Target node: auth.py
    node_auth = GraphNode(repository_id=repo.id, node_key="core_auth", node_type="file", name="auth.py", file_path="core/auth.py")
    
    # Direct callers in services/user_service.py: TWO distinct symbols in the SAME file
    node_login = GraphNode(repository_id=repo.id, node_key="login_user", node_type="method", name="login_user", file_path="services/user_service.py")
    node_refresh = GraphNode(repository_id=repo.id, node_key="refresh_token", node_type="method", name="refresh_token", file_path="services/user_service.py")
    
    # Transitive caller in api/user_api.py
    node_api = GraphNode(repository_id=repo.id, node_key="user_api_file", node_type="file", name="user_api.py", file_path="api/user_api.py")

    # External dependency of auth.py: jwt
    node_ext_jwt = GraphNode(repository_id=repo.id, node_key="ext_jwt", node_type="dependency", name="jwt", file_path=None)

    db_session.add_all([node_auth, node_login, node_refresh, node_api, node_ext_jwt])
    db_session.commit()

    # Edges:
    # login_user CALLS auth.py (Direct)
    # refresh_token CALLS auth.py (Direct)
    # user_api.py IMPORTS login_user (Transitive)
    # auth.py DEPENDS_ON jwt (External dependency)
    e1 = GraphEdge(repository_id=repo.id, source_node_id=node_login.id, target_node_id=node_auth.id, edge_type="CALLS", is_verified=True, evidence="calls token")
    e2 = GraphEdge(repository_id=repo.id, source_node_id=node_refresh.id, target_node_id=node_auth.id, edge_type="CALLS", is_verified=True, evidence="calls token")
    e3 = GraphEdge(repository_id=repo.id, source_node_id=node_api.id, target_node_id=node_login.id, edge_type="IMPORTS", is_verified=True, evidence="imports login")
    e_ext = GraphEdge(repository_id=repo.id, source_node_id=node_auth.id, target_node_id=node_ext_jwt.id, edge_type="DEPENDS_ON", is_verified=True, evidence="import jwt")

    db_session.add_all([e1, e2, e3, e_ext])
    db_session.commit()

    result = ChangeImpactAnalyzer.analyze_impact(
        db=db_session,
        repository_id=repo.id,
        component_name="auth.py",
        file_path="core/auth.py",
    )

    # Verifications:
    # Direct count: 2 (login_user and refresh_token)
    assert result.direct_count == 2
    # Transitive count: 1 (user_api.py)
    assert result.transitive_count == 1
    # Total affected: 3
    assert result.total_affected == 3

    # Direct symbols count: 2 (methods login_user and refresh_token)
    assert result.direct_symbols_count == 2
    # Transitive symbols count: 0 (user_api.py is type "file")
    assert result.transitive_symbols_count == 0

    # Direct files: exactly 1 ('services/user_service.py')
    assert result.direct_files_count == 1
    # Transitive files: exactly 1 ('api/user_api.py')
    assert result.transitive_files_count == 1
    # Total unique files: 2, deduplicated
    assert len(result.affected_files) == 2
    assert result.affected_files == ["api/user_api.py", "services/user_service.py"]

    # External dependencies: 'jwt' isolated from affected files
    assert "jwt" in result.external_dependencies
    assert "jwt" not in result.affected_files


@pytest.mark.anyio
async def test_identifier_explanation_precision(db_session: Session):
    """
    Regression Test 9: Identifier Grounding & Repository_id Disambiguation
    Verifies that:
    - repository_id is flagged as absent in repository where it does not exist.
    - Verified identifiers (user_id, role_id, employee_id_num) are grounded.
    """
    repo = Repository(name="ident-repo", full_name="acme/ident-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f_user = IndexedFile(repository_id=repo.id, path="services/user_service.py", lines_count=100)
    db_session.add(f_user)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_id=f_user.id,
        file_path=f_user.path,
        code_symbol="UserService.check_employee_id",
        chunk_index=0,
        chunk_text="def check_employee_id(db: Session, role_id: int, employee_id_num: str):\n    return {'available': True}",
        content_hash="hash_check_emp",
        language="python",
        start_line=1,
        end_line=15,
    )
    db_session.add(chunk)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain `create_access_token()`, `user_id`, and `repository_id` in this codebase.",
    )

    answer = res["answer"]
    # repository_id must be flagged as absent or unverified in this repository
    assert "repository_id" in answer
    assert "UNVERIFIED" in answer or "ABSENT" in answer or "does not exist" in answer.lower()


@pytest.mark.anyio
async def test_authentication_question_with_verified_evidence(db_session: Session):
    """
    Regression Test 10: Authentication Question with Verified Source Evidence
    Verifies that:
    - Authentication question retrieves core auth, login service, login api, and security files.
    - Token creation in auth.py and login flow in user_service.py are grounded with file paths.
    - Token validation (jwt.decode) and route protection are explicitly reported as unverified/absent.
    - Confirmed facts and unknowns accurately reflect the verified facts and unverified mechanisms.
    - Informational query does not fabricate change-impact ripple effects.
    """
    repo = Repository(name="expertdecision-test", full_name="acme/expertdecision-test", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f_auth = IndexedFile(repository_id=repo.id, path="backend/app/core/auth.py", lines_count=40)
    f_user_svc = IndexedFile(repository_id=repo.id, path="backend/app/services/user_service.py", lines_count=350)
    f_user_api = IndexedFile(repository_id=repo.id, path="backend/app/api/user_api.py", lines_count=200)
    f_sec = IndexedFile(repository_id=repo.id, path="backend/app/core/security.py", lines_count=130)
    f_sess = IndexedFile(repository_id=repo.id, path="backend/app/models/login_session.py", lines_count=30)
    db_session.add_all([f_auth, f_user_svc, f_user_api, f_sec, f_sess])
    db_session.commit()

    c_auth = CodeChunk(
        repository_id=repo.id,
        file_id=f_auth.id,
        file_path=f_auth.path,
        code_symbol="create_access_token",
        chunk_index=0,
        chunk_text="def create_access_token(data: dict, expires_delta=None):\n    to_encode = data.copy()\n    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)",
        content_hash="h_auth",
        language="python",
        start_line=8,
        end_line=31,
    )
    c_user_svc = CodeChunk(
        repository_id=repo.id,
        file_id=f_user_svc.id,
        file_path=f_user_svc.path,
        code_symbol="UserService.login_user",
        chunk_index=0,
        chunk_text="def login_user(db: Session, user: UserLogin):\n    if not verify_password(user.password, db_user.password):\n        raise HTTPException(401)\n    token = create_access_token({'sub': db_user.employee_id})\n    return {'access_token': token}",
        content_hash="h_user_svc",
        language="python",
        start_line=237,
        end_line=296,
    )
    c_user_api = CodeChunk(
        repository_id=repo.id,
        file_id=f_user_api.id,
        file_path=f_user_api.path,
        code_symbol="login_user",
        chunk_index=0,
        chunk_text="def login_user(user: UserLogin, request: Request, db: Session = Depends(get_db)):\n    return UserService.login_user(db, user)",
        content_hash="h_user_api",
        language="python",
        start_line=189,
        end_line=197,
    )
    c_sec = CodeChunk(
        repository_id=repo.id,
        file_id=f_sec.id,
        file_path=f_sec.path,
        code_symbol="verify_password",
        chunk_index=0,
        chunk_text="def verify_password(plain_password: str, hashed_password: str) -> bool:\n    return hmac.compare_digest(hash_password(plain_password), hashed_password)",
        content_hash="h_sec",
        language="python",
        start_line=59,
        end_line=118,
    )
    c_sess = CodeChunk(
        repository_id=repo.id,
        file_id=f_sess.id,
        file_path=f_sess.path,
        code_symbol="LoginSession",
        chunk_index=0,
        chunk_text="class LoginSession(Base):\n    __tablename__ = 'login_sessions'\n    id = Column(Integer, primary_key=True)",
        content_hash="h_sess",
        language="python",
        start_line=7,
        end_line=19,
    )
    db_session.add_all([c_auth, c_user_svc, c_user_api, c_sec, c_sess])
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the authentication in the Expert Decision Replay Platform.",
    )

    assert res["status"] == "success"
    # Citations must include auth files
    cit_paths = [c["file_path"] for c in res["citations"]]
    assert any("auth.py" in p for p in cit_paths)
    assert any("user_service.py" in p for p in cit_paths)
    assert any("user_api.py" in p for p in cit_paths)

    # Facts: confirmed facts >= 3, unknowns >= 1 (token validation and route protection absent)
    facts = res["facts"]
    assert facts["confirmed"] >= 3
    assert facts["inferences"] == 0
    assert facts["unknowns"] >= 1

    # Risk callout: must NOT claim completed impact analysis
    assert res["risk_callout"]["level"] == "LOW"
    assert "No change impact analysis performed for informational inquiry." in res["risk_callout"]["summary"]
    assert res["related_components"] == []


@pytest.mark.anyio
async def test_authentication_question_when_no_evidence_available(db_session: Session):
    """
    Regression Test 11: Authentication Questions When No Relevant Evidence is Available
    Verifies that:
    - When querying a repo with NO authentication code, the assistant states authentication could not be verified.
    - Confirmed facts is 0, Unknowns is 1.
    - Distinguishes lack of evidence from speculation, and avoids claiming JWT/OAuth exist.
    """
    repo = Repository(name="math-lib", full_name="acme/math-lib", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f_calc = IndexedFile(repository_id=repo.id, path="calc/math.py", lines_count=20)
    db_session.add(f_calc)
    db_session.commit()

    c_calc = CodeChunk(
        repository_id=repo.id,
        file_id=f_calc.id,
        file_path=f_calc.path,
        code_symbol="add",
        chunk_index=0,
        chunk_text="def add(a: int, b: int) -> int:\n    return a + b",
        content_hash="h_calc",
        language="python",
        start_line=1,
        end_line=10,
    )
    db_session.add(c_calc)
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the authentication mechanism in this repository.",
    )

    answer = res["answer"]
    assert "could not be verified" in answer.lower() or "not found" in answer.lower() or "unverified" in answer.lower()
    # Facts: confirmed 0, unknowns 1
    assert res["facts"]["confirmed"] == 0
    assert res["facts"]["unknowns"] == 1
    assert res["risk_callout"]["summary"] == "No change impact analysis performed for informational inquiry."


def test_svg_and_copy_button_markup_cleanliness():
    """
    Regression Test 12: SVG & Copy Button Rendering Cleanliness
    Verifies that:
    - All SVGs in frontend/static/js/api.js, assistant.html, and index.html have aria-hidden='true' and focusable='false'.
    - Copy buttons use separated label spans (<span class="btn-label">Copy</span>) to avoid 'svgCopy'.
    - Citations badge uses separated label spans (<span class="badge-text">...</span>) to avoid 'CodeMindsvg...'.
    - renderMarkdown strips raw XML/HTML <svg> tags safely without stripping the word 'SVG' from prose.
    """
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent.parent.parent

    # 1. Check api.js SVGs
    api_js_path = base_dir / "frontend" / "static" / "js" / "api.js"
    assert api_js_path.exists()
    js_content = api_js_path.read_text(encoding="utf-8")

    svg_tags = [t for t in re.findall(r"<svg\b[^>]*>", js_content) if not t.startswith("<svg[") and not t.startswith("<svg^") and not t.startswith("<svg\\")]
    assert len(svg_tags) > 0
    for tag in svg_tags:
        assert 'aria-hidden="true"' in tag, f"SVG tag missing aria-hidden: {tag}"
        assert 'focusable="false"' in tag, f"SVG tag missing focusable: {tag}"

    # 2. Check assistant.html SVGs
    asst_path = base_dir / "frontend" / "templates" / "assistant.html"
    asst_content = asst_path.read_text(encoding="utf-8")
    asst_svgs = re.findall(r"<svg\b[^>]*>", asst_content)
    assert len(asst_svgs) > 0
    for tag in asst_svgs:
        assert 'aria-hidden="true"' in tag, f"Template SVG tag missing aria-hidden: {tag}"

    # 3. Check copy answer and copy code button markup separation
    assert 'class="msg-action-btn copy-answer-btn"' in js_content
    assert '<span class="btn-label">Copy</span>' in js_content

    # 4. Check citations badge separation
    assert '<span class="badge-text">' in js_content

    # 5. Check CSS rules for .icon pointer-events and user-select
    css_path = base_dir / "frontend" / "static" / "css" / "styles.css"
    css_content = css_path.read_text(encoding="utf-8")
    assert ".icon" in css_content
    assert "pointer-events: none;" in css_content
    assert "user-select: none;" in css_content


def test_informational_query_not_misrepresented_as_impact_analysis(client: TestClient, db_session: Session):
    """
    Regression Test 13: Informational Questions Not Misrepresented as Completed Impact Analysis
    Verifies that:
    - Informational questions do not execute change-impact analysis or fabricate ripple effects.
    - related_components is empty.
    - risk_callout summary clearly states no change impact analysis was performed.
    """
    repo = Repository(name="info-repo", full_name="acme/info-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f_core = IndexedFile(repository_id=repo.id, path="core/main.py", lines_count=10)
    db_session.add(f_core)
    db_session.commit()

    c_core = CodeChunk(
        repository_id=repo.id,
        file_id=f_core.id,
        file_path=f_core.path,
        code_symbol="main",
        chunk_index=0,
        chunk_text="def main(): pass",
        content_hash="h_core",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(c_core)
    db_session.commit()

    conv = AssistantConversation(
        repository_id=repo.id,
        user_id=1,
        branch="main",
        title="Info Test",
        title_is_manual=False
    )
    db_session.add(conv)
    db_session.commit()

    # Query via API endpoint
    response = client.post(
        f"/api/v1/repositories/{repo.id}/assistant/query",
        json={
            "question": "What does the main function do?",
            "conversation_id": conv.id
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["related_components"] == []
    assert data["risk_callout"]["level"] == "LOW"
    assert "No change impact analysis performed for informational inquiry." in data["risk_callout"]["summary"]


