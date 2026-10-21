from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.impact.analyzer import ChangeImpactAnalyzer


def test_change_impact_direct_and_transitive(db_session: Session):
    """Verify change impact analyzer traces callers and separates direct vs transitive impact."""
    repo = Repository(name="impact-repo", full_name="acme/impact-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    # Target: validateSession
    n_target = GraphNode(repository_id=repo.id, node_key="target", node_type="function", name="validateSession", file_path="src/auth.ts")
    # Direct caller: authMiddleware
    n_direct = GraphNode(repository_id=repo.id, node_key="direct", node_type="function", name="authMiddleware", file_path="src/middleware.ts")
    # Transitive caller: apiGateway
    n_transitive = GraphNode(repository_id=repo.id, node_key="trans", node_type="class", name="ApiGateway", file_path="src/gateway.ts")
    db_session.add_all([n_target, n_direct, n_transitive])
    db_session.commit()

    # Edges: authMiddleware CALLS validateSession; ApiGateway CALLS authMiddleware
    e1 = GraphEdge(repository_id=repo.id, source_node_id=n_direct.id, target_node_id=n_target.id, edge_type="CALLS", is_verified=True, evidence="validateSession() in middleware")
    e2 = GraphEdge(repository_id=repo.id, source_node_id=n_transitive.id, target_node_id=n_direct.id, edge_type="CALLS", is_verified=True, evidence="authMiddleware() in gateway")
    db_session.add_all([e1, e2])
    db_session.commit()

    result = ChangeImpactAnalyzer.analyze_impact(
        db=db_session,
        repository_id=repo.id,
        component_name="validateSession",
        max_depth=3,
    )

    assert result.target_component == "validateSession"
    assert result.total_affected == 2
    assert result.direct_count == 1
    assert result.transitive_count == 1

    comp_names = {c.name: c for c in result.affected_components}
    assert "authMiddleware" in comp_names
    assert comp_names["authMiddleware"].impact_level == "DIRECT"
    assert comp_names["authMiddleware"].distance == 1
    assert comp_names["authMiddleware"].confidence_score >= 0.9

    assert "ApiGateway" in comp_names
    assert comp_names["ApiGateway"].impact_level == "TRANSITIVE"
    assert comp_names["ApiGateway"].distance == 2
    assert comp_names["ApiGateway"].confidence_score < comp_names["authMiddleware"].confidence_score

    # Check limitations statement
    assert "Static graph analysis reflects declared imports" in result.limitations
    assert len(result.dependency_paths) == 2
