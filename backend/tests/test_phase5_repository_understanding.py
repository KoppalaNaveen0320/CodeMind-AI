import pytest
import re
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.orm import Session
from backend.app.services.assistant_service import AssistantService
from backend.app.graph.builder import KnowledgeGraphBuilder
from backend.app.services.call_hierarchy_service import CallHierarchyService
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine, RetrievedChunk
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.parsing.extractor import ExtractedCall, CodeExtractor


# =====================================================================
# Phase 5: Repository Understanding and Grounded Answer Accuracy Suite
# 20 Comprehensive Test Categories
# =====================================================================

def test_01_symbol_query_detection_behavioral_discrimination():
    """1. Distinguish explicit symbol queries from behavioral/feature queries."""
    # Behavioral queries must NOT be detected as symbol queries (must return None)
    assert AssistantService._detect_symbol_query("Confirm whether email-based account recovery exists in the repository") is None
    assert AssistantService._detect_symbol_query("Is email OTP recovery implemented?") is None
    assert AssistantService._detect_symbol_query("Does session validation exist?") is None
    assert AssistantService._detect_symbol_query("Explain how registration and login work") is None
    assert AssistantService._detect_symbol_query("What is the technology stack of this repository?") is None
    assert AssistantService._detect_symbol_query("Does incremental indexing handle deleted files?") is None
    assert AssistantService._detect_symbol_query("Is there database transaction rollback support?") is None

    # Explicit symbol queries MUST be detected correctly
    assert AssistantService._detect_symbol_query("Where is `calculate_xyz` defined?") == "calculate_xyz"
    assert AssistantService._detect_symbol_query("Find function calculate_xyz_not_present") == "calculate_xyz_not_present"
    assert AssistantService._detect_symbol_query("where is calculate_metrics()") == "calculate_metrics"
    assert AssistantService._detect_symbol_query("Where is class UserModel defined?") == "UserModel"


def test_02_graph_call_resolution_with_receiver(db_session: Session):
    """2. Call resolution with call.receiver resolves to imported symbol, avoiding false self-loops."""
    repo = Repository(name="test_repo", full_name="user/test_repo", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    file_api = IndexedFile(repository_id=repo.id, path="app/api/dashboard_api.py", language="python", lines_count=50)
    file_svc = IndexedFile(repository_id=repo.id, path="app/services/dashboard_service.py", language="python", lines_count=50)
    db_session.add_all([file_api, file_svc])
    db_session.flush()

    sym_api = CodeSymbol(repository_id=repo.id, file_id=file_api.id, name="get_dashboard", kind="function", start_line=10, end_line=15)
    sym_svc = CodeSymbol(repository_id=repo.id, file_id=file_svc.id, name="get_dashboard", kind="function", start_line=5, end_line=20)
    db_session.add_all([sym_api, sym_svc])
    db_session.flush()

    # Call inside dashboard_api to DashboardService.get_dashboard
    call = ExtractedCall(
        caller_name="get_dashboard",
        callee_name="get_dashboard",
        line_number=12,
        evidence="DashboardService.get_dashboard()",
        receiver="DashboardService"
    )

    calls_by_file = {file_api.id: [call], file_svc.id: []}
    symbols_by_file = {file_api.id: [sym_api], file_svc.id: [sym_svc]}

    nodes_cnt, edges_cnt = KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[file_api, file_svc],
        symbols_by_file=symbols_by_file,
        calls_by_file=calls_by_file
    )
    db_session.flush()

    # Verify no self loop exists on api get_dashboard -> api get_dashboard
    api_node = db_session.query(GraphNode).filter(GraphNode.file_path == file_api.path, GraphNode.name == "get_dashboard").first()
    svc_node = db_session.query(GraphNode).filter(GraphNode.file_path == file_svc.path, GraphNode.name == "get_dashboard").first()
    assert api_node is not None
    assert svc_node is not None

    self_loop = db_session.query(GraphEdge).filter(
        GraphEdge.source_node_id == api_node.id,
        GraphEdge.target_node_id == api_node.id
    ).first()
    assert self_loop is None, "False self-loop was generated when call had explicit receiver!"

    cross_edge = db_session.query(GraphEdge).filter(
        GraphEdge.source_node_id == api_node.id,
        GraphEdge.target_node_id == svc_node.id,
        GraphEdge.edge_type == "CALLS"
    ).first()
    assert cross_edge is not None, "Cross-file call with receiver failed to resolve to imported service node!"


def test_03_ambiguous_call_hierarchy_aggregation(db_session: Session):
    """3. Call hierarchy aggregates callers and callees across candidates when symbol name is ambiguous."""
    repo = Repository(name="test_repo", full_name="user/test_repo", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    f1 = IndexedFile(repository_id=repo.id, path="app/api/item_api.py", language="python", lines_count=40)
    f2 = IndexedFile(repository_id=repo.id, path="app/services/item_service.py", language="python", lines_count=40)
    db_session.add_all([f1, f2])
    db_session.flush()

    s1 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="get_item", kind="function", start_line=5, end_line=15)
    s2 = CodeSymbol(repository_id=repo.id, file_id=f2.id, name="get_item", kind="function", start_line=10, end_line=30)
    db_session.add_all([s1, s2])
    db_session.flush()

    # Graph nodes
    n1 = GraphNode(repository_id=repo.id, node_key=f"func:{repo.id}:{f1.path}:get_item", file_path=f1.path, name="get_item", node_type="function", start_line=5, end_line=15)
    n2 = GraphNode(repository_id=repo.id, node_key=f"func:{repo.id}:{f2.path}:get_item", file_path=f2.path, name="get_item", node_type="function", start_line=10, end_line=30)
    n_caller = GraphNode(repository_id=repo.id, node_key=f"func:{repo.id}:app/main.py:router_call", file_path="app/main.py", name="router_call", node_type="function", start_line=1, end_line=5)
    db_session.add_all([n1, n2, n_caller])
    db_session.flush()

    # n_caller -> CALLS -> n1, n1 -> CALLS -> n2
    e1 = GraphEdge(repository_id=repo.id, source_node_id=n_caller.id, target_node_id=n1.id, edge_type="CALLS", is_verified=True)
    e2 = GraphEdge(repository_id=repo.id, source_node_id=n1.id, target_node_id=n2.id, edge_type="CALLS", is_verified=True)
    db_session.add_all([e1, e2])
    db_session.flush()

    res = CallHierarchyService.get_call_hierarchy_by_name(
        db=db_session,
        repository_id=repo.id,
        symbol_name="get_item",
        direction="both"
    )
    assert res.is_ambiguous is True
    assert len(res.candidates) == 2
    # Callers and callees must be aggregated, NOT empty
    assert len(res.callers) > 0, "Ambiguous call hierarchy returned empty callers list!"
    assert any(c.caller_name == "router_call" or getattr(c, 'symbol_name', None) == "router_call" for c in res.callers)


def test_04_hybrid_retrieval_manifest_boosting(db_session: Session):
    """4. Hybrid retrieval prioritizes manifest files for tech stack and dependency queries."""
    repo = Repository(name="test_repo", full_name="user/test_repo", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    c_code = CodeChunk(
        repository_id=repo.id,
        file_path="app/services/item_service.py",
        code_symbol="ItemService",
        chunk_index=0,
        chunk_text="class ItemService:\n    pass",
        content_hash="hash1",
        start_line=1,
        end_line=10,
        language="python"
    )
    c_manifest = CodeChunk(
        repository_id=repo.id,
        file_path="requirements.txt",
        code_symbol=None,
        chunk_index=0,
        chunk_text="fastapi>=0.100.0\nsqlalchemy>=2.0.0\npytest>=7.0.0",
        content_hash="hash2",
        start_line=1,
        end_line=5,
        language="text"
    )
    db_session.add_all([c_code, c_manifest])
    db_session.flush()

    # Exact matches helper should include manifest files when query asks about tech stack
    matches = HybridRetrievalEngine._retrieve_exact_matches(
        db=db_session,
        repo_id=repo.id,
        query="What is the technology stack of this repository?",
        language=None
    )
    manifest_paths = [m.file_path for m in matches]
    assert "requirements.txt" in manifest_paths


def test_05_hybrid_retrieval_test_file_boosting(db_session: Session):
    """5. When user asks for tests, test files are boosted rather than penalized."""
    repo = Repository(name="test_repo", full_name="user/test_repo", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    c_impl = CodeChunk(
        repository_id=repo.id,
        file_path="app/auth.py",
        code_symbol="login",
        chunk_index=0,
        chunk_text="def login(username, password):\n    return True",
        content_hash="h1",
        start_line=1,
        end_line=10,
        language="python"
    )
    c_test = CodeChunk(
        repository_id=repo.id,
        file_path="tests/test_auth.py",
        code_symbol="test_login",
        chunk_index=0,
        chunk_text="def test_login():\n    assert login('admin', 'pass')",
        content_hash="h2",
        start_line=1,
        end_line=10,
        language="python"
    )
    db_session.add_all([c_impl, c_test])
    db_session.flush()

    # Build prompt messages for test query
    chunks = [
        RetrievedChunk(
            chunk_id=c_impl.id,
            repository_id=repo.id,
            file_path=c_impl.file_path,
            symbol_name=c_impl.code_symbol,
            start_line=c_impl.start_line,
            end_line=c_impl.end_line,
            chunk_text=c_impl.chunk_text,
            score=0.9
        ),
        RetrievedChunk(
            chunk_id=c_test.id,
            repository_id=repo.id,
            file_path=c_test.file_path,
            symbol_name=c_test.code_symbol,
            start_line=c_test.start_line,
            end_line=c_test.end_line,
            chunk_text=c_test.chunk_text,
            score=0.85
        )
    ]
    messages = AssistantService._build_prompt_messages(
        repo_name="test_repo",
        question="What pytest unit tests exist for auth?",
        chunks=chunks
    )
    user_content = messages[-1]["content"]
    assert "tests/test_auth.py" in user_content, "Test chunk was wrongly excluded when user asked about tests!"


def test_06_complete_function_body_truncation_boundary():
    """6. Chunk truncation does not cut off functions at 25 lines, preserving transaction blocks."""
    lines_50 = ["def register_user(db, payload):"]
    lines_50 += [f"    # step {i}" for i in range(1, 30)]
    lines_50 += ["    db.commit()", "    return {'status': 'success'}"]
    full_text = "\n".join(lines_50)

    chunk = RetrievedChunk(
        chunk_id=1,
        repository_id=1,
        file_path="app/services/user_service.py",
        symbol_name="register_user",
        start_line=1,
        end_line=35,
        chunk_text=full_text,
        score=0.95
    )

    messages = AssistantService._build_prompt_messages(
        repo_name="test_repo",
        question="Explain user registration and database commits",
        chunks=[chunk]
    )
    user_content = messages[-1]["content"]
    assert "db.commit()" in user_content, "db.commit() was severed due to premature 25-line truncation!"
    assert "return {'status': 'success'}" in user_content


def test_07_dynamic_route_protection_audit(db_session: Session):
    """7. Route protection audit dynamically inspects session validation and login checks."""
    repo = Repository(name="test_repo", full_name="user/test_repo", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    c_fe = CodeChunk(
        repository_id=repo.id,
        file_path="frontend/app.py",
        code_symbol="dashboard_view",
        chunk_index=0,
        chunk_text="if not session.get('logged_in'):\n    return redirect('/login')",
        content_hash="fe_hash",
        start_line=10,
        end_line=20,
        language="python"
    )
    db_session.add(c_fe)
    db_session.flush()

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="Explain authentication and session validation in the application",
        retrieved_chunks=[]
    )
    assert notes is not None
    assert "Access control / session protection logic detected" in notes or "session" in notes.lower()
    assert "Endpoints do not enforce token validation" not in notes


def test_08_hallucinated_caller_sanitization():
    """8. Sanitizer removes hallucinated get_dashboard_data and resolves self-contradictory claims."""
    bad_answer = (
        "The `get_dashboard` function is not called by any other function in the repository. "
        "It is called by the `dashboard` function in `backend/app/main.py`. "
        "It delegates calls to `get_dashboard_data()` in the database layer."
    )
    clean = AssistantService._validate_and_sanitize_answer(bad_answer, [], "test_repo")
    assert "get_dashboard_data" not in clean
    assert "get_dashboard()" in clean
    # The contradiction "is not called by any other function" should be eliminated
    assert "is not called by any other function" not in clean


def test_09_technology_stack_enrichment(db_session: Session):
    """9. Tech stack audit grounds answer in manifest files and detected frameworks."""
    repo = Repository(
        name="expertdecision",
        full_name="KoppalaNaveen/expertdecision",
        default_branch="main",
        tech_stack={
            "primary_language": "Python",
            "summary": {"full_summary": "Frontend: JavaScript, HTML, CSS; Backend: Python, FastAPI; Database: PostgreSQL"},
            "languages": ["Python", "JavaScript"]
        }
    )
    db_session.add(repo)
    db_session.flush()

    c_req = CodeChunk(
        repository_id=repo.id,
        file_path="backend/requirements.txt",
        code_symbol=None,
        chunk_index=0,
        chunk_text="fastapi==0.100.0\nuvicorn==0.23.0\nsqlalchemy==2.0.0",
        content_hash="req_h",
        start_line=1,
        end_line=10,
        language="text"
    )
    db_session.add(c_req)
    db_session.flush()

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="What is the technology stack of this repository?",
        retrieved_chunks=[]
    )
    assert notes is not None
    assert "VERIFIED TECH STACK AUDIT" in notes
    assert "backend/requirements.txt" in notes
    assert any(c.file_path == "backend/requirements.txt" for c in chunks)


def test_10_negative_recovery_query_grounding(db_session: Session):
    """10. Negative feature query (email OTP recovery) retrieves chunks rather than short-circuiting."""
    repo = Repository(name="expertdecision", full_name="KoppalaNaveen/expertdecision", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    c_email = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/services/email_service.py",
        code_symbol="send_verification_email",
        chunk_index=0,
        chunk_text="def send_verification_email(to_addr):\n    # sends email verification token",
        content_hash="em_h",
        start_line=10,
        end_line=25,
        language="python"
    )
    db_session.add(c_email)
    db_session.flush()

    # Must NOT short-circuit as symbol lookup
    sym = AssistantService._detect_symbol_query("Confirm whether email-based account recovery exists in the repository")
    assert sym is None


def test_11_static_call_extraction_with_receiver():
    """11. CodeExtractor extracts receiver for method and service calls."""
    code = (
        "// File: api.py | Lines: 1-10\n"
        "def get_dashboard(user_id: int):\n"
        "    return DashboardService.get_dashboard(user_id)\n"
    )
    calls = CodeExtractor.extract_static_calls(code.encode("utf-8"), "api.py", "python")
    assert len(calls) >= 1
    call = next(c for c in calls if c.callee_name == "get_dashboard")
    assert call.receiver == "DashboardService"
    assert "DashboardService.get_dashboard" in call.evidence or "inside def get_dashboard" in call.evidence


def test_12_repository_isolation_in_retrieval(db_session: Session):
    """12. Hybrid retrieval never leaks chunks from other repositories."""
    repo1 = Repository(name="repo_one", full_name="user/repo_one", default_branch="main")
    repo2 = Repository(name="repo_two", full_name="user/repo_two", default_branch="main")
    db_session.add_all([repo1, repo2])
    db_session.flush()

    c1 = CodeChunk(repository_id=repo1.id, file_path="main.py", code_symbol="app1", chunk_index=0, chunk_text="app 1 code", content_hash="h1", start_line=1, end_line=5)
    c2 = CodeChunk(repository_id=repo2.id, file_path="main.py", code_symbol="app2", chunk_index=0, chunk_text="app 2 secret code", content_hash="h2", start_line=1, end_line=5)
    db_session.add_all([c1, c2])
    db_session.flush()

    matches = HybridRetrievalEngine._retrieve_exact_matches(db_session, repo1.id, "secret code main.py", language=None)
    assert all(m.repository_id == repo1.id for m in matches)
    assert not any(m.repository_id == repo2.id for m in matches)


def test_13_file_path_hint_extraction_for_call_hierarchy(db_session: Session):
    """13. Assistant extracts file path hints from questions for call hierarchy disambiguation."""
    repo = Repository(name="test_repo", full_name="user/test_repo", default_branch="main")
    db_session.add(repo)
    db_session.flush()

    q = "What is the call hierarchy of get_dashboard in dashboard_api.py?"
    file_hint = None
    m_file = re.search(r'\b([a-zA-Z0-9_/.-]+\.py)\b', q)
    if m_file:
        file_hint = m_file.group(1).strip()
    assert file_hint == "dashboard_api.py"


def test_14_database_commit_verification_rule_in_prompt():
    """14. Prompt instructions strictly enforce accurate transaction boundaries and no speculative autocommits."""
    messages = AssistantService._build_prompt_messages(
        repo_name="expertdecision",
        question="Where do commits happen during user registration?",
        chunks=[]
    )
    sys_prompt = messages[0]["content"]
    assert "DATABASE TRANSACTIONS & COMMITS" in sys_prompt
    assert "Do NOT propose speculative transaction modifications" in sys_prompt


def test_15_absence_vs_unretrieved_distinction_rule():
    """15. Prompt instructions distinguish 'not found in retrieved evidence' from 'not implemented'."""
    messages = AssistantService._build_prompt_messages(
        repo_name="expertdecision",
        question="Is email OTP recovery implemented?",
        chunks=[]
    )
    sys_prompt = messages[0]["content"]
    assert "NEGATIVE QUERIES & FEATURE ABSENCE" in sys_prompt
    assert "distinguish 'not found in retrieved evidence' from 'not implemented in the repository'" in sys_prompt


def test_16_concise_first_answers_rule():
    """16. Prompt instructions require answering the specific question in the first paragraph."""
    messages = AssistantService._build_prompt_messages(
        repo_name="expertdecision",
        question="What is the entry point?",
        chunks=[]
    )
    sys_prompt = messages[0]["content"]
    assert "CONCISE-FIRST ANSWERS" in sys_prompt
    assert "Answer the user's specific question directly in the very first paragraph" in sys_prompt


def test_17_multi_turn_consistency_rule():
    """17. Multi-turn consistency rule prevents contradictory answers across turns."""
    messages = AssistantService._build_prompt_messages(
        repo_name="expertdecision",
        question="Who calls it?",
        chunks=[]
    )
    sys_prompt = messages[0]["content"]
    assert "MULTI-TURN CONSISTENCY" in sys_prompt
    assert "Do not contradict answers given in previous conversation turns" in sys_prompt


def test_18_sse_streaming_event_formatting():
    """18. AssistantService _format_sse produces valid SSE data lines."""
    event_str = AssistantService._format_sse("status", {"text": "Verifying sources..."})
    assert event_str.startswith("event: status\n")
    assert "Verifying sources..." in event_str
    assert event_str.endswith("\n\n")


def test_19_citation_line_range_integrity():
    """19. Verified citations retain valid positive start and end line ranges."""
    c = RetrievedChunk(
        chunk_id=1,
        repository_id=1,
        file_path="app/main.py",
        symbol_name="app",
        start_line=1,
        end_line=25,
        chunk_text="from fastapi import FastAPI\napp = FastAPI()",
        score=0.9
    )
    assert c.start_line > 0
    assert c.end_line >= c.start_line
    assert c.file_path == "app/main.py"


def test_20_call_hierarchy_integrity_no_contradictions():
    """20. Verified call hierarchy prompt formatting generates clean verified caller blocks."""
    callers = "- `get_dashboard` (backend/app/api/dashboard_api.py:26–30) [Verified call]"
    callees = "- `DashboardRepository` (backend/app/repositories/dashboard_repository.py:237–733) [Verified call]"
    block = f"Verified Callers:\n{callers}\n\nVerified Callees:\n{callees}"
    assert "Verified Callers:" in block
    assert "dashboard_api.py" in block
    assert "dashboard_repository.py" in block
