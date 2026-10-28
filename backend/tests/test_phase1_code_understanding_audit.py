import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.security import create_session_token, create_user_session_record
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.graph.builder import KnowledgeGraphBuilder
from backend.app.graph.service import KnowledgeGraphService
from backend.app.services.symbol_service import SymbolService
from backend.app.services.call_hierarchy_service import CallHierarchyService
from backend.app.parsing.extractor import CodeExtractor, ExtractedCall


# ============================================================================
# 1. Symbol Search & Workspace Isolation Tests
# ============================================================================

def test_symbol_search_cross_workspace_isolation(client: TestClient, db_session: Session):
    """
    Verifies that symbol search strictly isolates workspaces:
    User A in Workspace A cannot find or access symbols from private repositories in Workspace B.
    """
    user_a = User(email="usera@workspacea.dev", full_name="User A", workspace_name="Workspace Alpha", is_active=True)
    user_b = User(email="userb@workspaceb.dev", full_name="User B", workspace_name="Workspace Beta", is_active=True)
    db_session.add_all([user_a, user_b])
    db_session.commit()

    repo_a = Repository(name="alpha-repo", full_name="alpha/alpha-repo", user_id=user_a.id, is_private=True, status="ready")
    repo_b = Repository(name="beta-repo", full_name="beta/beta-repo", user_id=user_b.id, is_private=True, status="ready")
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    fa = IndexedFile(repository_id=repo_a.id, path="src/alpha_logic.py", language="python")
    fb = IndexedFile(repository_id=repo_b.id, path="src/beta_secret.py", language="python")
    db_session.add_all([fa, fb])
    db_session.commit()

    sa = CodeSymbol(repository_id=repo_a.id, file_id=fa.id, name="shared_kernel_init", kind="function", start_line=10, end_line=20)
    sb = CodeSymbol(repository_id=repo_b.id, file_id=fb.id, name="shared_kernel_init", kind="function", start_line=15, end_line=30)
    db_session.add_all([sa, sb])
    db_session.commit()

    token_a = create_session_token(user_a.id)
    create_user_session_record(db_session, user_a, token_a, initial_path="/dashboard")

    # 1. User A searches globally: must ONLY return symbol from alpha_repo
    resp_global = client.get(
        "/api/v1/symbols/search?query=shared_kernel_init",
        cookies={"codemind_session": token_a}
    )
    assert resp_global.status_code == 200
    res = resp_global.json()
    assert res["total_count"] == 1
    assert res["symbols"][0]["repository_id"] == repo_a.id
    assert res["symbols"][0]["file_path"] == "src/alpha_logic.py"

    # 2. User A attempts to search within repo_b: rejected with 403 Forbidden
    resp_forbidden = client.get(
        f"/api/v1/repositories/{repo_b.id}/symbols/search?query=shared_kernel_init",
        cookies={"codemind_session": token_a}
    )
    assert resp_forbidden.status_code == 403


def test_symbol_search_edge_cases_and_empty_queries(client: TestClient, db_session: Session):
    """
    Verifies symbol search handles empty queries, whitespace, special characters,
    nonexistent symbols, and unsupported file extensions safely without exceptions.
    """
    repo = Repository(name="edge-symbols", full_name="test/edge-symbols", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="README.md", language="markdown")
    f2 = IndexedFile(repository_id=repo.id, path="assets/logo.png", language="binary")
    f3 = IndexedFile(repository_id=repo.id, path="lib/core.py", language="python")
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    sym = CodeSymbol(repository_id=repo.id, file_id=f3.id, name="execute_pipeline", kind="function", start_line=1, end_line=25)
    db_session.add(sym)
    db_session.commit()

    # Empty query string
    resp_empty = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=")
    assert resp_empty.status_code == 200
    assert resp_empty.json()["total_count"] == 1  # Returns indexed symbols in alphabetical order

    # Nonexistent query
    resp_none = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=no_such_symbol_12345")
    assert resp_none.status_code == 200
    assert resp_none.json()["total_count"] == 0
    assert len(resp_none.json()["symbols"]) == 0

    # Special characters and SQL injection probe
    resp_sql = client.get(f"/api/v1/repositories/{repo.id}/symbols/search?query=' OR 1=1 --")
    assert resp_sql.status_code == 200
    assert resp_sql.json()["total_count"] == 0


# ============================================================================
# 2. Call Hierarchy Precision & False-Positive Elimination Tests
# ============================================================================

def test_call_hierarchy_eliminates_false_positives_without_imports(db_session: Session):
    """
    Verifies that calling a function (such as `create_user`) does NOT create
    a CALLS edge to an unrelated function in another file when no import exists.
    """
    repo = Repository(name="fp-repo", full_name="test/fp-repo", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    # file1 has order_processing calling create_user() but DOES NOT import user_service
    f1 = IndexedFile(id=101, repository_id=repo.id, path="services/order_service.py", language="python")
    # file2 defines create_user()
    f2 = IndexedFile(id=102, repository_id=repo.id, path="services/user_service.py", language="python")
    # file3 is a test file that defines a local helper create_user()
    f3 = IndexedFile(id=103, repository_id=repo.id, path="tests/test_helpers.py", language="python")
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    sym_order = CodeSymbol(id=201, repository_id=repo.id, file_id=101, name="process_order", kind="function", start_line=10, end_line=30)
    sym_user = CodeSymbol(id=202, repository_id=repo.id, file_id=102, name="create_user", kind="function", start_line=5, end_line=25)
    sym_test_user = CodeSymbol(id=203, repository_id=repo.id, file_id=103, name="create_user", kind="function", start_line=1, end_line=15)
    db_session.add_all([sym_order, sym_user, sym_test_user])
    db_session.commit()

    # Call in order_service: calls "create_user" without importing user_service
    calls = {
        101: [ExtractedCall(caller_name="process_order", callee_name="create_user", line_number=18, evidence="Call to create_user() at line 18")]
    }

    KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f1, f2, f3],
        symbols_by_file={101: [sym_order], 102: [sym_user], 103: [sym_test_user]},
        calls_by_file=calls
    )

    # Verify that NO verified CALLS edge was created from process_order to create_user!
    calls_edges = db_session.query(GraphEdge).filter(
        GraphEdge.repository_id == repo.id,
        GraphEdge.edge_type == "CALLS"
    ).all()
    assert len(calls_edges) == 0, "Unrelated function must not be linked without an import statement!"


def test_call_hierarchy_resolves_verified_imported_call(db_session: Session):
    """
    Verifies that when file1 explicitly imports file2, static calls between them
    ARE verified and correctly linked with precise file and line numbers.
    """
    repo = Repository(name="import-call-repo", full_name="test/import-call-repo", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(id=301, repository_id=repo.id, path="app/controller.py", language="python")
    f2 = IndexedFile(id=302, repository_id=repo.id, path="app/auth_service.py", language="python")
    db_session.add_all([f1, f2])
    db_session.commit()

    sym_import = CodeSymbol(id=401, repository_id=repo.id, file_id=301, name="from app.auth_service import login", kind="import", start_line=1, end_line=1)
    sym_handle = CodeSymbol(id=402, repository_id=repo.id, file_id=301, name="handle_request", kind="function", start_line=10, end_line=25)
    sym_login = CodeSymbol(id=403, repository_id=repo.id, file_id=302, name="login", kind="function", start_line=5, end_line=30)
    db_session.add_all([sym_import, sym_handle, sym_login])
    db_session.commit()

    calls = {
        301: [ExtractedCall(caller_name="handle_request", callee_name="login", line_number=18, evidence="Call to login() inside def handle_request at line 18")]
    }

    KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f1, f2],
        symbols_by_file={301: [sym_import, sym_handle], 302: [sym_login]},
        calls_by_file=calls
    )

    # Query call hierarchy for handle_request
    resp = CallHierarchyService.get_call_hierarchy_by_id(
        db=db_session,
        repository_id=repo.id,
        symbol_id=sym_handle.id,
        direction="callees"
    )

    assert resp.total_callees == 1
    callee = resp.callees[0]
    assert callee.symbol_name == "login"
    assert callee.callee_file_path == "app/auth_service.py"
    assert callee.call_site_line == 18
    assert callee.is_verified is True


def test_call_hierarchy_extracts_and_traverses_self_recursion(db_session: Session):
    """
    Verifies that self-recursive functions (e.g. factorial) are accurately extracted,
    stored as self-referential CALLS edges, and bounded without infinite loops.
    """
    code = b"def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)\n"
    calls = CodeExtractor.extract_static_calls(code, "math_utils.py", language="python")

    # Verify extractor identified factorial calling factorial
    assert len(calls) == 1
    assert calls[0].caller_name == "factorial"
    assert calls[0].callee_name == "factorial"
    assert calls[0].line_number == 4

    # Now verify builder stores it in the graph
    repo = Repository(name="recur-build-repo", full_name="test/recur-build", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(id=501, repository_id=repo.id, path="math_utils.py", language="python")
    db_session.add(f)
    db_session.commit()

    sym = CodeSymbol(id=601, repository_id=repo.id, file_id=501, name="factorial", kind="function", start_line=1, end_line=5)
    db_session.add(sym)
    db_session.commit()

    KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f],
        symbols_by_file={501: [sym]},
        calls_by_file={501: calls}
    )

    # Edge must exist in DB
    self_edges = db_session.query(GraphEdge).filter(
        GraphEdge.repository_id == repo.id,
        GraphEdge.edge_type == "CALLS"
    ).all()
    assert len(self_edges) == 1
    assert self_edges[0].source_node_id == self_edges[0].target_node_id

    # Query call hierarchy: must detect cycle and remain bounded
    resp = CallHierarchyService.get_call_hierarchy_by_id(
        db=db_session,
        repository_id=repo.id,
        symbol_id=sym.id,
        direction="both",
        max_depth=3
    )
    assert resp.has_cycles is True
    assert len(resp.callees) == 1
    assert resp.callees[0].symbol_name == "factorial"


def test_call_hierarchy_same_named_functions_disambiguation(client: TestClient, db_session: Session):
    """
    Verifies that two same-named functions in different files have their respective
    callers and callees mapped to the correct source file rather than swapped.
    """
    repo = Repository(name="same-name-repo", full_name="test/same-name", is_private=False, status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(id=701, repository_id=repo.id, path="pkg_a/worker.py", language="python")
    f2 = IndexedFile(id=702, repository_id=repo.id, path="pkg_b/worker.py", language="python")
    db_session.add_all([f1, f2])
    db_session.commit()

    # pkg_a worker run calls run_a_step
    sym_a = CodeSymbol(id=801, repository_id=repo.id, file_id=701, name="run", kind="function", start_line=10, end_line=30)
    sym_step_a = CodeSymbol(id=802, repository_id=repo.id, file_id=701, name="run_a_step", kind="function", start_line=35, end_line=50)

    # pkg_b worker run calls run_b_step
    sym_b = CodeSymbol(id=803, repository_id=repo.id, file_id=702, name="run", kind="function", start_line=10, end_line=30)
    sym_step_b = CodeSymbol(id=804, repository_id=repo.id, file_id=702, name="run_b_step", kind="function", start_line=35, end_line=50)
    db_session.add_all([sym_a, sym_step_a, sym_b, sym_step_b])
    db_session.commit()

    calls = {
        701: [ExtractedCall(caller_name="run", callee_name="run_a_step", line_number=20, evidence="Call to run_a_step() at line 20")],
        702: [ExtractedCall(caller_name="run", callee_name="run_b_step", line_number=22, evidence="Call to run_b_step() at line 22")],
    }

    KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f1, f2],
        symbols_by_file={701: [sym_a, sym_step_a], 702: [sym_b, sym_step_b]},
        calls_by_file=calls
    )

    # Query call hierarchy for pkg_a run
    resp_a = CallHierarchyService.get_call_hierarchy_by_id(db=db_session, repository_id=repo.id, symbol_id=sym_a.id)
    assert len(resp_a.callees) == 1
    assert resp_a.callees[0].symbol_name == "run_a_step"
    assert resp_a.callees[0].callee_file_path == "pkg_a/worker.py"

    # Query call hierarchy for pkg_b run
    resp_b = CallHierarchyService.get_call_hierarchy_by_id(db=db_session, repository_id=repo.id, symbol_id=sym_b.id)
    assert len(resp_b.callees) == 1
    assert resp_b.callees[0].symbol_name == "run_b_step"
    assert resp_b.callees[0].callee_file_path == "pkg_b/worker.py"


# ============================================================================
# 3. Dependency Graph & Navigation Tests
# ============================================================================

def test_dependency_graph_empty_repository_safe(client: TestClient, db_session: Session):
    """
    Verifies that querying the dependency graph for an empty or newly registered
    repository does not crash and returns a valid empty graph response.
    """
    empty_repo = Repository(name="empty-repo", full_name="acme/empty-repo", is_private=False, status="pending")
    db_session.add(empty_repo)
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{empty_repo.id}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repository_id"] == empty_repo.id
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["summary"]["total_nodes"] == 0
    assert data["summary"]["total_edges"] == 0


def test_dependency_graph_node_neighbors_cross_tenant_rejected(client: TestClient, db_session: Session):
    """
    Verifies that a user cannot explore graph node neighbors from another user's private repository.
    """
    user1 = User(email="tenant1@acme.dev", full_name="Tenant One", workspace_name="Workspace 1", is_active=True)
    user2 = User(email="tenant2@other.dev", full_name="Tenant Two", workspace_name="Workspace 2", is_active=True)
    db_session.add_all([user1, user2])
    db_session.commit()

    repo1 = Repository(name="secret-graph", full_name="t1/secret-graph", user_id=user1.id, is_private=True, status="ready")
    db_session.add(repo1)
    db_session.commit()

    n = GraphNode(repository_id=repo1.id, node_key="node:t1", node_type="class", name="SecretClass", file_path="secret.py")
    db_session.add(n)
    db_session.commit()

    token2 = create_session_token(user2.id)
    create_user_session_record(db_session, user2, token2, initial_path="/dashboard")

    # User 2 tries to access node neighbors in user 1's repo
    resp = client.get(
        f"/api/v1/repositories/{repo1.id}/graph/nodes/{n.id}/neighbors",
        cookies={"codemind_session": token2}
    )
    assert resp.status_code == 403
