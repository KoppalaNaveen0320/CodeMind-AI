from collections import deque
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.core.config import settings
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.repository import Repository

logger = logging.getLogger(__name__)


@dataclass
class AffectedComponent:
    node_id: int
    name: str
    component_type: str  # function, class, file, method
    file_path: Optional[str]
    impact_level: str  # "DIRECT" or "TRANSITIVE"
    distance: int
    confidence_score: float
    evidence: Optional[str]
    dependency_path: List[str] = field(default_factory=list)


@dataclass
class ImpactAnalysisResult:
    target_component: str
    target_type: str
    file_path: Optional[str]
    proposed_change: Optional[str]
    total_affected: int
    direct_count: int
    transitive_count: int
    risk_level: str  # "LOW", "MEDIUM", "HIGH"
    affected_components: List[AffectedComponent]
    affected_files: List[str]
    dependency_paths: List[Dict[str, Any]]
    limitations: str
    explanation: str
    direct_symbols_count: int = 0
    transitive_symbols_count: int = 0
    direct_files_count: int = 0
    transitive_files_count: int = 0
    external_dependencies: List[str] = field(default_factory=list)


class ChangeImpactAnalyzer:
    """
    Graph-backed Change-Impact Analysis Engine.
    Traverses verified static relationships (CALLS, IMPORTS, DEPENDS_ON) to predict
    which repository components may be affected by a proposed code modification.
    """

    LIMITATIONS_NOTICE = (
        "Static graph analysis reflects declared imports, AST-defined symbols, and verified call expressions. "
        "Dynamic imports, reflection, eval(), runtime dependency injection, and unindexed external libraries "
        "cannot be fully verified at static analysis time. Confidence scores are heuristic scores based on graph "
        "topological distance (1.0 for direct 1-hop, decayed by 0.25 per transitive hop), NOT calibrated statistical "
        "probabilities. This analysis does not guarantee runtime behavior."
    )

    @classmethod
    def analyze_impact(
        cls,
        db: Session,
        repository_id: int,
        component_name: Optional[str] = None,
        file_path: Optional[str] = None,
        proposed_change: Optional[str] = None,
        max_depth: Optional[int] = None,
    ) -> ImpactAnalysisResult:
        """
        Analyzes the impact of modifying a component or file.
        """
        depth_limit = max_depth or settings.IMPACT_MAX_DEPTH
        clean_file = file_path.strip() if file_path else None
        clean_comp = component_name.strip() if component_name else None

        # 1. Locate Target Root Node(s) strictly scoped to repository_id
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        repo_name = repo.name if repo else f"repo-{repository_id}"

        root_nodes: List[GraphNode] = []
        if clean_comp:
            # 1a. Exact symbol or node name match
            root_nodes = (
                db.query(GraphNode)
                .filter(
                    GraphNode.repository_id == repository_id,
                    or_(
                        GraphNode.name == clean_comp,
                        GraphNode.symbol_name == clean_comp,
                    ),
                )
                .all()
            )

            # 1b. If not found, try exact file path match or filename match
            if not root_nodes:
                norm_comp = clean_comp.replace("\\", "/")
                root_nodes = (
                    db.query(GraphNode)
                    .filter(
                        GraphNode.repository_id == repository_id,
                        or_(
                            GraphNode.file_path == norm_comp,
                            GraphNode.file_path.endswith("/" + norm_comp),
                            GraphNode.name == norm_comp.split("/")[-1],
                        ),
                    )
                    .all()
                )

            # 1c. If clean_comp has dots (e.g. UserService.login_user or app.core.auth)
            if not root_nodes and "." in clean_comp:
                parts = clean_comp.split(".")
                last_part = parts[-1]
                root_nodes = (
                    db.query(GraphNode)
                    .filter(
                        GraphNode.repository_id == repository_id,
                        or_(
                            GraphNode.name == last_part,
                            GraphNode.symbol_name == last_part,
                            GraphNode.symbol_name == clean_comp,
                        ),
                    )
                    .all()
                )

            # 1d. Case-insensitive exact match
            if not root_nodes:
                root_nodes = (
                    db.query(GraphNode)
                    .filter(
                        GraphNode.repository_id == repository_id,
                        or_(
                            GraphNode.name.ilike(clean_comp),
                            GraphNode.symbol_name.ilike(clean_comp),
                        ),
                    )
                    .all()
                )

        if not root_nodes and clean_file:
            norm_file = clean_file.replace("\\", "/")
            root_nodes = (
                db.query(GraphNode)
                .filter(
                    GraphNode.repository_id == repository_id,
                    or_(
                        GraphNode.file_path == norm_file,
                        GraphNode.file_path.endswith("/" + norm_file),
                        GraphNode.name == norm_file.split("/")[-1],
                    ),
                )
                .all()
            )

        if not root_nodes and proposed_change and not clean_comp and not clean_file:
            import re
            candidate_words = [w.strip("(),.:;\"'`{}[]") for w in proposed_change.split() if len(w.strip("(),.:;\"'`{}[]")) >= 3]
            # Prioritize terms that look like identifiers
            code_words = [w for w in candidate_words if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", w)]
            search_words = code_words if code_words else candidate_words
            if search_words:
                root_nodes = (
                    db.query(GraphNode)
                    .filter(
                        GraphNode.repository_id == repository_id,
                        GraphNode.name.in_(search_words[:15]),
                    )
                    .all()
                )

        # Check total graph nodes in repository to distinguish empty repo vs missing symbol
        total_repo_nodes = db.query(GraphNode).filter(GraphNode.repository_id == repository_id).count()

        if not root_nodes:
            if total_repo_nodes == 0:
                explanation = f"Knowledge graph data is unavailable for repository '{repo_name}'. Please complete indexing to synthesize the graph."
                limitations = "Knowledge graph data is not yet generated or available for this repository."
            else:
                target_str = clean_comp or clean_file or "specified component"
                explanation = f"No indexed graph node matched '{target_str}' in repository '{repo_name}'."
                limitations = cls.LIMITATIONS_NOTICE

            return ImpactAnalysisResult(
                target_component=clean_comp or clean_file or "Unknown",
                target_type="unresolved",
                file_path=clean_file,
                proposed_change=proposed_change,
                total_affected=0,
                direct_count=0,
                transitive_count=0,
                risk_level="LOW",
                affected_components=[],
                affected_files=[],
                dependency_paths=[],
                limitations=limitations,
                explanation=explanation,
                direct_symbols_count=0,
                transitive_symbols_count=0,
                direct_files_count=0,
                transitive_files_count=0,
                external_dependencies=[],
            )

        primary_target = root_nodes[0]
        root_ids = {n.id for n in root_nodes}

        # Query outgoing external dependencies (e.g. datetime, jwt, fastapi)
        external_deps_set: Set[str] = set()
        for rid in root_ids:
            outgoing_deps = (
                db.query(GraphNode)
                .join(GraphEdge, GraphEdge.target_node_id == GraphNode.id)
                .filter(
                    GraphEdge.repository_id == repository_id,
                    GraphEdge.source_node_id == rid,
                    GraphEdge.edge_type.in_(["DEPENDS_ON", "IMPORTS"]),
                )
                .all()
            )
            for dep_node in outgoing_deps:
                if dep_node.node_type == "dependency" or not dep_node.file_path:
                    external_deps_set.add(dep_node.name)

        # 2. BFS Traversal with Cycle Detection for Incoming Dependencies
        # Direction: target is CALLED by or IMPORTED by other components (who depends on target)
        visited_nodes: Dict[int, AffectedComponent] = {}
        visited_ids: Set[int] = set(root_ids)
        all_paths: List[Dict[str, Any]] = []

        # Queue contains: (node_id, current_distance, path_names)
        queue = deque([(nid, 0, [primary_target.name]) for nid in root_ids])

        while queue:
            current_id, dist, path = queue.popleft()
            if dist >= depth_limit:
                continue

            # Query incoming dependencies/calls (who calls/imports current_id)
            incoming_edges = (
                db.query(GraphEdge, GraphNode)
                .join(GraphNode, GraphEdge.source_node_id == GraphNode.id)
                .filter(
                    GraphEdge.repository_id == repository_id,
                    GraphEdge.target_node_id == current_id,
                    GraphEdge.edge_type.in_(["CALLS", "IMPORTS", "DEPENDS_ON"]),
                )
                .all()
            )

            # If current node is a symbol in a file, also check importers of its containing file at distance 1
            if dist == 0:
                curr_node_rec = next((n for n in root_nodes if n.id == current_id), None)
                if curr_node_rec and curr_node_rec.file_path:
                    file_node = (
                        db.query(GraphNode)
                        .filter(
                            GraphNode.repository_id == repository_id,
                            GraphNode.node_type == "file",
                            GraphNode.file_path == curr_node_rec.file_path,
                        )
                        .first()
                    )
                    if file_node and file_node.id not in root_ids:
                        file_importers = (
                            db.query(GraphEdge, GraphNode)
                            .join(GraphNode, GraphEdge.source_node_id == GraphNode.id)
                            .filter(
                                GraphEdge.repository_id == repository_id,
                                GraphEdge.target_node_id == file_node.id,
                                GraphEdge.edge_type.in_(["IMPORTS", "DEPENDS_ON"]),
                            )
                            .all()
                        )
                        incoming_edges.extend(file_importers)

            for edge, source_node in incoming_edges:
                if source_node.id in visited_ids:
                    continue
                visited_ids.add(source_node.id)

                new_dist = dist + 1
                new_path = path + [f"--({edge.edge_type})--> {source_node.name}"]
                confidence = max(0.2, round(1.0 - (new_dist - 1) * 0.25, 2))
                level = "DIRECT" if new_dist == 1 else "TRANSITIVE"

                visited_nodes[source_node.id] = AffectedComponent(
                    node_id=source_node.id,
                    name=source_node.name,
                    component_type=source_node.node_type,
                    file_path=source_node.file_path,
                    impact_level=level,
                    distance=new_dist,
                    confidence_score=confidence,
                    evidence=edge.evidence,
                    dependency_path=new_path,
                )
                all_paths.append({
                    "source": source_node.name,
                    "source_file": source_node.file_path,
                    "relationship": edge.edge_type,
                    "target": path[-1].split("--> ")[-1],
                    "distance": new_dist,
                    "evidence": edge.evidence,
                })

                queue.append((source_node.id, new_dist, new_path))

        affected_list = list(visited_nodes.values())
        # Sort affected list: direct first, then by distance ascending, then by name
        affected_list.sort(key=lambda x: (0 if x.impact_level == "DIRECT" else 1, x.distance, x.name))

        direct_components = [a for a in affected_list if a.impact_level == "DIRECT"]
        transitive_components = [a for a in affected_list if a.impact_level == "TRANSITIVE"]
        direct_count = len(direct_components)
        transitive_count = len(transitive_components)
        total_affected = len(affected_list)

        # Count unique symbols separately from unique files
        direct_symbols = [a for a in direct_components if a.component_type != "file"]
        transitive_symbols = [a for a in transitive_components if a.component_type != "file"]
        direct_symbols_count = len(direct_symbols)
        transitive_symbols_count = len(transitive_symbols)

        # Mutually exclusive file sets: direct vs transitive-only
        direct_files = sorted(list({a.file_path for a in direct_components if a.file_path}))
        transitive_files = sorted(list({a.file_path for a in transitive_components if a.file_path and a.file_path not in direct_files}))
        affected_files = sorted(list(set(direct_files + transitive_files)))
        direct_files_count = len(direct_files)
        transitive_files_count = len(transitive_files)

        # Assess Risk Level
        if direct_count >= 5 or total_affected >= 10:
            risk = "HIGH"
        elif direct_count >= 2 or total_affected >= 4:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        ext_deps_list = sorted(list(external_deps_set))

        # Generate consistent explanation
        if total_affected == 0:
            explanation = (
                f"Modifying '{primary_target.name}' has 0 verified callers or dependent components "
                f"in the indexed knowledge graph for repository '{repo_name}'."
            )
        else:
            explanation = (
                f"Modifying '{primary_target.name}' directly impacts {direct_count} component(s) "
                f"({direct_symbols_count} symbol(s) in {direct_files_count} file(s)) and transitively influences "
                f"{transitive_count} component(s) ({transitive_symbols_count} symbol(s) in {transitive_files_count} file(s)) "
                f"across {len(affected_files)} unique project file(s). "
                f"Relationships are traced via verified static AST edges (CALLS, IMPORTS)."
            )
        if ext_deps_list:
            explanation += f" External dependencies: {', '.join(ext_deps_list)}."

        return ImpactAnalysisResult(
            target_component=primary_target.name,
            target_type=primary_target.node_type,
            file_path=primary_target.file_path,
            proposed_change=proposed_change,
            total_affected=total_affected,
            direct_count=direct_count,
            transitive_count=transitive_count,
            risk_level=risk,
            affected_components=affected_list,
            affected_files=affected_files,
            dependency_paths=all_paths,
            limitations=cls.LIMITATIONS_NOTICE,
            explanation=explanation,
            direct_symbols_count=direct_symbols_count,
            transitive_symbols_count=transitive_symbols_count,
            direct_files_count=direct_files_count,
            transitive_files_count=transitive_files_count,
            external_dependencies=ext_deps_list,
        )

