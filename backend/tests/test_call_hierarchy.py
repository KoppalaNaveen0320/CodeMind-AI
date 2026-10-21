import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge


def test_call_hierarchy_callers_and_callees(client: TestClient, db_session: Session):
    repo = Repository(name="call-repo", full_name="org/call-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="app/caller.py", language="python")
    f2 = IndexedFile(repository_id=repo.id, path="app/target.py", language="python")
    f3 = IndexedFile(repository_id=repo.id, path="app/callee.py", language="python")
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    sym_caller = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="invoke_service", kind="function", start_line=10, end_line=25)
    sym_target = CodeSymbol(repository_id=repo.id, file_id=f2.id, name="process_request", kind="function", start_line=50, end_line=85)
    sym_callee = CodeSymbol(repository_id=repo.id, file_id=f3.id, name="write_db", kind="function", start_line=100, end_line=120)
    db_session.add_all([sym_caller, sym_target, sym_callee])
    db_session.commit()

    node_caller = GraphNode(repository_id=repo.id, node_key="node:caller", node_type="function", name="invoke_service", file_path="app/caller.py", start_line=10, end_line=25)
    node_target = GraphNode(repository_id=repo.id, node_key="node:target", node_type="function", name="process_request", file_path="app/target.py", start_line=50, end_line=85)
    node_callee = GraphNode(repository_id=repo.id, node_key="node:callee", node_type="function", name="write_db", file_path="app/callee.py", start_line=100, end_line=120)
    db_session.add_all([node_caller, node_target, node_callee])
    db_session.commit()

    # caller -> target (CALLS)
    edge_in = GraphEdge(repository_id=repo.id, source_node_id=node_caller.id, target_node_id=node_target.id, edge_type="CALLS", is_verified=True, evidence="line 18")
    # target -> callee (CALLS)
    edge_out = GraphEdge(repository_id=repo.id, source_node_id=node_target.id, target_node_id=node_callee.id, edge_type="CALLS", is_verified=True, evidence="line 72")
    db_session.add_all([edge_in, edge_out])
    db_session.commit()

    # Query call hierarchy for process_request by symbol ID
    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/{sym_target.id}/call-hierarchy")
    assert resp.status_code == 200
    data = resp.json()

    assert data["target_symbol"]["name"] == "process_request"
    assert len(data["callers"]) == 1
    assert data["callers"][0]["caller_name"] == "invoke_service"
    assert data["callers"][0]["caller_file_path"] == "app/caller.py"
    assert data["callers"][0]["is_verified"] is True

    assert len(data["callees"]) == 1
    assert data["callees"][0]["callee_name"] == "write_db"
    assert data["callees"][0]["callee_file_path"] == "app/callee.py"
    assert data["callees"][0]["is_verified"] is True


def test_call_hierarchy_disambiguation_same_name_across_modules(client: TestClient, db_session: Session):
    repo = Repository(name="ambig-repo", full_name="org/ambig-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(repository_id=repo.id, path="app/api/auth.py", language="python")
    f2 = IndexedFile(repository_id=repo.id, path="app/services/auth.py", language="python")
    db_session.add_all([f1, f2])
    db_session.commit()

    s1 = CodeSymbol(repository_id=repo.id, file_id=f1.id, name="validate_token", kind="function", start_line=10, end_line=20)
    s2 = CodeSymbol(repository_id=repo.id, file_id=f2.id, name="validate_token", kind="function", start_line=30, end_line=50)
    db_session.add_all([s1, s2])
    db_session.commit()

    n1 = GraphNode(repository_id=repo.id, node_key="n1", node_type="function", name="validate_token", file_path="app/api/auth.py", start_line=10, end_line=20)
    n2 = GraphNode(repository_id=repo.id, node_key="n2", node_type="function", name="validate_token", file_path="app/services/auth.py", start_line=30, end_line=50)
    db_session.add_all([n1, n2])
    db_session.commit()

    # Query by name without file_path -> should be ambiguous
    resp_ambig = client.get(f"/api/v1/repositories/{repo.id}/calls/hierarchy?symbol_name=validate_token")
    assert resp_ambig.status_code == 200
    d_ambig = resp_ambig.json()
    assert d_ambig["is_ambiguous"] is True
    assert len(d_ambig["ambiguous_candidates"]) == 2

    # Query by name WITH file_path -> disambiguated
    resp_resolved = client.get(f"/api/v1/repositories/{repo.id}/calls/hierarchy?symbol_name=validate_token&file_path=app/services/auth.py")
    assert resp_resolved.status_code == 200
    d_resolved = resp_resolved.json()
    assert d_resolved["is_ambiguous"] is False
    assert d_resolved["target_symbol"]["file_path"] == "app/services/auth.py"


def test_call_hierarchy_cycle_and_recursion_safety(client: TestClient, db_session: Session):
    repo = Repository(name="recur-repo", full_name="org/recur-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app/math_algo.py", language="python")
    db_session.add(f)
    db_session.commit()

    sym_fib = CodeSymbol(repository_id=repo.id, file_id=f.id, name="fibonacci", kind="function", start_line=1, end_line=10)
    db_session.add(sym_fib)
    db_session.commit()

    node_fib = GraphNode(repository_id=repo.id, node_key="node:fib", node_type="function", name="fibonacci", file_path="app/math_algo.py", start_line=1, end_line=10)
    db_session.add(node_fib)
    db_session.commit()

    # Self-recursive edge: fibonacci -> fibonacci
    edge_self = GraphEdge(repository_id=repo.id, source_node_id=node_fib.id, target_node_id=node_fib.id, edge_type="CALLS", is_verified=True)
    db_session.add(edge_self)
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/{sym_fib.id}/call-hierarchy?max_depth=4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_cycles"] is True
    # Traversal should be bounded and not explode into infinite lists
    assert len(data["callees"]) <= 4


def test_call_hierarchy_unverified_and_heuristic_calls(client: TestClient, db_session: Session):
    repo = Repository(name="heuristic-repo", full_name="org/heuristic-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="app/dispatch.py", language="python")
    db_session.add(f)
    db_session.commit()

    sym_handler = CodeSymbol(repository_id=repo.id, file_id=f.id, name="dispatch_event", kind="function", start_line=1, end_line=20)
    sym_listener = CodeSymbol(repository_id=repo.id, file_id=f.id, name="on_event", kind="function", start_line=30, end_line=45)
    db_session.add_all([sym_handler, sym_listener])
    db_session.commit()

    node_handler = GraphNode(repository_id=repo.id, node_key="nh", node_type="function", name="dispatch_event", file_path="app/dispatch.py", start_line=1, end_line=20)
    node_listener = GraphNode(repository_id=repo.id, node_key="nl", node_type="function", name="on_event", file_path="app/dispatch.py", start_line=30, end_line=45)
    db_session.add_all([node_handler, node_listener])
    db_session.commit()

    # Mark call as unverified / dynamic dispatch
    e_dynamic = GraphEdge(repository_id=repo.id, source_node_id=node_handler.id, target_node_id=node_listener.id, edge_type="CALLS", is_verified=False, evidence="Dynamic string event dispatch")
    db_session.add(e_dynamic)
    db_session.commit()

    resp = client.get(f"/api/v1/repositories/{repo.id}/symbols/{sym_handler.id}/call-hierarchy")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["callees"]) == 1
    # Distinguishes statically verified calls from heuristic/dynamic matches
    assert data["callees"][0]["is_verified"] is False
    assert "Dynamic" in (data["callees"][0]["evidence"] or "")


def test_call_hierarchy_repository_isolation(client: TestClient, db_session: Session):
    repo1 = Repository(name="call-iso-1", full_name="org/call-iso-1", status="ready")
    repo2 = Repository(name="call-iso-2", full_name="org/call-iso-2", status="ready")
    db_session.add_all([repo1, repo2])
    db_session.commit()

    f1 = IndexedFile(repository_id=repo1.id, path="app/service.py", language="python")
    f2 = IndexedFile(repository_id=repo2.id, path="app/service.py", language="python")
    db_session.add_all([f1, f2])
    db_session.commit()

    s1 = CodeSymbol(repository_id=repo1.id, file_id=f1.id, name="shared_name", kind="function", start_line=1, end_line=10)
    s2 = CodeSymbol(repository_id=repo2.id, file_id=f2.id, name="shared_name", kind="function", start_line=1, end_line=10)
    db_session.add_all([s1, s2])
    db_session.commit()

    n1 = GraphNode(repository_id=repo1.id, node_key="r1_node", node_type="function", name="shared_name", file_path="app/service.py", start_line=1, end_line=10)
    n2 = GraphNode(repository_id=repo2.id, node_key="r2_node", node_type="function", name="shared_name", file_path="app/service.py", start_line=1, end_line=10)
    db_session.add_all([n1, n2])
    db_session.commit()

    # Querying repo1 cannot access symbol in repo2
    resp_cross = client.get(f"/api/v1/repositories/{repo1.id}/symbols/{s2.id}/call-hierarchy")
    assert resp_cross.status_code == 200
    assert "error" in resp_cross.json()["target_symbol"]
