import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.knowledge_graph import GraphNode, GraphEdge


def test_dependency_graph_direct_and_transitive_neighbors(client: TestClient, db_session: Session):
    repo = Repository(name="dep-repo", full_name="org/dep-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    # Create chain: Node A -> Node B -> Node C -> Node D
    node_a = GraphNode(repository_id=repo.id, node_key="node:a", node_type="function", name="func_a", file_path="app/a.py", start_line=1, end_line=10)
    node_b = GraphNode(repository_id=repo.id, node_key="node:b", node_type="function", name="func_b", file_path="app/b.py", start_line=1, end_line=10)
    node_c = GraphNode(repository_id=repo.id, node_key="node:c", node_type="function", name="func_c", file_path="app/c.py", start_line=1, end_line=10)
    node_d = GraphNode(repository_id=repo.id, node_key="node:d", node_type="function", name="func_d", file_path="app/d.py", start_line=1, end_line=10)

    db_session.add_all([node_a, node_b, node_c, node_d])
    db_session.commit()

    edge_ab = GraphEdge(repository_id=repo.id, source_node_id=node_a.id, target_node_id=node_b.id, edge_type="CALLS", is_verified=True)
    edge_bc = GraphEdge(repository_id=repo.id, source_node_id=node_b.id, target_node_id=node_c.id, edge_type="CALLS", is_verified=True)
    edge_cd = GraphEdge(repository_id=repo.id, source_node_id=node_c.id, target_node_id=node_d.id, edge_type="CALLS", is_verified=True)

    db_session.add_all([edge_ab, edge_bc, edge_cd])
    db_session.commit()

    # Test depth=1 for Node A
    resp_d1 = client.get(f"/api/v1/repositories/{repo.id}/graph/nodes/{node_a.id}/neighbors?depth=1")
    assert resp_d1.status_code == 200
    d1 = resp_d1.json()
    assert len(d1["direct_neighbors"]) == 1
    assert d1["direct_neighbors"][0]["node"]["name"] == "func_b"
    assert d1["direct_neighbors"][0]["direction"] == "outgoing"
    assert len(d1["transitive_neighbors"]) == 0

    # Test depth=2 for Node A: direct (func_b) + transitive (func_c at hop 2)
    resp_d2 = client.get(f"/api/v1/repositories/{repo.id}/graph/nodes/{node_a.id}/neighbors?depth=2")
    assert resp_d2.status_code == 200
    d2 = resp_d2.json()
    assert len(d2["direct_neighbors"]) == 1
    assert len(d2["transitive_neighbors"]) == 1
    assert d2["transitive_neighbors"][0]["node"]["name"] == "func_c"
    assert d2["transitive_neighbors"][0]["depth"] == 2

    # Test depth=3 for Node A: direct (func_b) + transitive (func_c at hop 2, func_d at hop 3)
    resp_d3 = client.get(f"/api/v1/repositories/{repo.id}/graph/nodes/{node_a.id}/neighbors?depth=3")
    assert resp_d3.status_code == 200
    d3 = resp_d3.json()
    assert len(d3["direct_neighbors"]) == 1
    assert len(d3["transitive_neighbors"]) == 2
    transitive_names = {t["node"]["name"] for t in d3["transitive_neighbors"]}
    assert transitive_names == {"func_c", "func_d"}


def test_dependency_graph_cycles_safe_traversal(client: TestClient, db_session: Session):
    repo = Repository(name="cycle-repo", full_name="org/cycle-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    # Cyclic graph: X -> Y -> Z -> X
    x = GraphNode(repository_id=repo.id, node_key="x", node_type="class", name="ClassX", file_path="app/x.py")
    y = GraphNode(repository_id=repo.id, node_key="y", node_type="class", name="ClassY", file_path="app/y.py")
    z = GraphNode(repository_id=repo.id, node_key="z", node_type="class", name="ClassZ", file_path="app/z.py")
    db_session.add_all([x, y, z])
    db_session.commit()

    e_xy = GraphEdge(repository_id=repo.id, source_node_id=x.id, target_node_id=y.id, edge_type="DEPENDS_ON", is_verified=True)
    e_yz = GraphEdge(repository_id=repo.id, source_node_id=y.id, target_node_id=z.id, edge_type="DEPENDS_ON", is_verified=True)
    e_zx = GraphEdge(repository_id=repo.id, source_node_id=z.id, target_node_id=x.id, edge_type="DEPENDS_ON", is_verified=True)
    db_session.add_all([e_xy, e_yz, e_zx])
    db_session.commit()

    # Should traverse with depth=4 without infinite loop
    resp = client.get(f"/api/v1/repositories/{repo.id}/graph/nodes/{x.id}/neighbors?depth=4")
    assert resp.status_code == 200
    data = resp.json()
    assert "direct_neighbors" in data
    # Nodes visited should be bounded and not duplicated infinitely
    visited_ids = {n["node"]["id"] for n in data["direct_neighbors"] + data["transitive_neighbors"]}
    assert len(visited_ids) <= 3


def test_dependency_graph_filtering_and_bounding(client: TestClient, db_session: Session):
    repo = Repository(name="filter-graph-repo", full_name="org/filter-graph-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    n1 = GraphNode(repository_id=repo.id, node_key="f1", node_type="function", name="fn_one", file_path="app/one.py")
    n2 = GraphNode(repository_id=repo.id, node_key="c1", node_type="class", name="ClsOne", file_path="app/one.py")
    n3 = GraphNode(repository_id=repo.id, node_key="s1", node_type="service", name="SvcOne", file_path="app/svc.py")
    db_session.add_all([n1, n2, n3])
    db_session.commit()

    e1 = GraphEdge(repository_id=repo.id, source_node_id=n1.id, target_node_id=n2.id, edge_type="DEFINES", is_verified=True)
    e2 = GraphEdge(repository_id=repo.id, source_node_id=n2.id, target_node_id=n3.id, edge_type="IMPORTS", is_verified=True)
    db_session.add_all([e1, e2])
    db_session.commit()

    # Filter by node_type=class
    resp_class = client.get(f"/api/v1/repositories/{repo.id}/graph?node_type=class")
    assert resp_class.status_code == 200
    nodes = resp_class.json()["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["name"] == "ClsOne"

    # Filter by edge_type=IMPORTS
    resp_edge = client.get(f"/api/v1/repositories/{repo.id}/graph?edge_type=IMPORTS")
    assert resp_edge.status_code == 200
    edges = resp_edge.json()["edges"]
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "IMPORTS"


def test_dependency_graph_repository_isolation(client: TestClient, db_session: Session):
    repo1 = Repository(name="repo-iso-g1", full_name="org/repo-iso-g1", status="ready")
    repo2 = Repository(name="repo-iso-g2", full_name="org/repo-iso-g2", status="ready")
    db_session.add_all([repo1, repo2])
    db_session.commit()

    n1 = GraphNode(repository_id=repo1.id, node_key="r1_node", node_type="function", name="repo1_fn", file_path="app/r1.py")
    n2 = GraphNode(repository_id=repo2.id, node_key="r2_node", node_type="function", name="repo2_fn", file_path="app/r2.py")
    db_session.add_all([n1, n2])
    db_session.commit()

    e1 = GraphEdge(repository_id=repo1.id, source_node_id=n1.id, target_node_id=n1.id, edge_type="CALLS", is_verified=True)
    e2 = GraphEdge(repository_id=repo2.id, source_node_id=n2.id, target_node_id=n2.id, edge_type="CALLS", is_verified=True)
    db_session.add_all([e1, e2])
    db_session.commit()

    resp1 = client.get(f"/api/v1/repositories/{repo1.id}/graph")
    assert resp1.status_code == 200
    r1_nodes = resp1.json()["nodes"]
    assert len(r1_nodes) == 1
    assert r1_nodes[0]["name"] == "repo1_fn"

    resp2 = client.get(f"/api/v1/repositories/{repo2.id}/graph")
    assert resp2.status_code == 200
    r2_nodes = resp2.json()["nodes"]
    assert len(r2_nodes) == 1
    assert r2_nodes[0]["name"] == "repo2_fn"
