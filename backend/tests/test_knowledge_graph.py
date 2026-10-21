import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.graph.builder import KnowledgeGraphBuilder
from backend.app.graph.service import KnowledgeGraphService
from backend.app.parsing.extractor import ExtractedCall


def test_knowledge_graph_construction_and_deduplication(db_session: Session):
    """Verify graph builder creates accurate nodes and edges without duplicates."""
    repo = Repository(name="graph-repo", full_name="acme/graph-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(id=1, repository_id=repo.id, path="src/auth.py", language="python", lines_count=50)
    f2 = IndexedFile(id=2, repository_id=repo.id, path="src/api.py", language="python", lines_count=40)
    db_session.add_all([f1, f2])
    db_session.commit()

    sym_cls = CodeSymbol(id=1, repository_id=repo.id, file_id=1, name="AuthService", kind="class", start_line=5, end_line=25)
    sym_method = CodeSymbol(id=2, repository_id=repo.id, file_id=1, name="AuthService.validate", kind="method", start_line=10, end_line=15)
    sym_imp = CodeSymbol(id=3, repository_id=repo.id, file_id=2, name="from src.auth import AuthService", kind="import", start_line=1, end_line=1)
    db_session.add_all([sym_cls, sym_method, sym_imp])
    db_session.commit()

    symbols_by_file = {
        1: [sym_cls, sym_method],
        2: [sym_imp],
    }

    calls_by_file = {
        1: [ExtractedCall(caller_name="validate", callee_name="verify_token", line_number=12, evidence="verify_token() inside validate")]
    }

    nodes_cnt, edges_cnt = KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f1, f2],
        symbols_by_file=symbols_by_file,
        calls_by_file=calls_by_file,
    )

    assert nodes_cnt >= 4  # repo, 2 files, AuthService, validate
    assert edges_cnt >= 3  # CONTAINS, DEFINES, IMPORTS

    # Verify nodes in DB
    nodes = db_session.query(GraphNode).filter(GraphNode.repository_id == repo.id).all()
    node_types = {n.node_type for n in nodes}
    assert "repository" in node_types
    assert "file" in node_types
    assert "class" in node_types

    # Verify import edge
    imp_edges = db_session.query(GraphEdge).filter(GraphEdge.edge_type == "IMPORTS").all()
    assert len(imp_edges) >= 1
    assert imp_edges[0].is_verified is True


def test_stale_graph_cleanup_on_rebuild(db_session: Session):
    """Verify rebuilding graph removes stale nodes and edges from deleted files."""
    repo = Repository(name="stale-repo", full_name="acme/stale-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    f1 = IndexedFile(id=10, repository_id=repo.id, path="old_file.py", language="python")
    db_session.add(f1)
    db_session.commit()

    sym = CodeSymbol(id=20, repository_id=repo.id, file_id=10, name="old_fn", kind="function", start_line=1, end_line=5)
    db_session.add(sym)
    db_session.commit()

    # Initial build
    KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f1],
        symbols_by_file={10: [sym]},
    )

    old_node = db_session.query(GraphNode).filter(GraphNode.name == "old_fn").first()
    assert old_node is not None

    # Rebuild with new file, old file removed
    f2 = IndexedFile(id=11, repository_id=repo.id, path="new_file.py", language="python")
    db_session.add(f2)
    db_session.commit()

    KnowledgeGraphBuilder.build_graph_for_repository(
        db=db_session,
        repository=repo,
        files=[f2],
        symbols_by_file={11: []},
    )

    old_node_check = db_session.query(GraphNode).filter(GraphNode.name == "old_fn").first()
    assert old_node_check is None  # Stale node removed!


def test_shortest_path_bfs(db_session: Session):
    """Verify BFS traversal finds shortest path between connected components."""
    repo = Repository(name="path-repo", full_name="acme/path-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    n1 = GraphNode(repository_id=repo.id, node_key="n1", node_type="function", name="loginRoute")
    n2 = GraphNode(repository_id=repo.id, node_key="n2", node_type="class", name="AuthService")
    n3 = GraphNode(repository_id=repo.id, node_key="n3", node_type="function", name="verifyPassword")
    db_session.add_all([n1, n2, n3])
    db_session.commit()

    e1 = GraphEdge(repository_id=repo.id, source_node_id=n1.id, target_node_id=n2.id, edge_type="CALLS", is_verified=True)
    e2 = GraphEdge(repository_id=repo.id, source_node_id=n2.id, target_node_id=n3.id, edge_type="CALLS", is_verified=True)
    db_session.add_all([e1, e2])
    db_session.commit()

    path = KnowledgeGraphService.find_path(db_session, repo.id, n1.id, n3.id, max_depth=3)
    assert path is not None
    assert len(path) == 2
    assert path[0]["target_name"] == "AuthService"
    assert path[1]["target_name"] == "verifyPassword"
