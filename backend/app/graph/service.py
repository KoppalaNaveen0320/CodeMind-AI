from collections import deque
import json
import logging
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.repository import Repository

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    @classmethod
    def get_repository_graph(
        cls,
        db: Session,
        repository_id: int,
        node_limit: int = 150,
        node_type: Optional[str] = None,
        edge_type: Optional[str] = None,
        file_path: Optional[str] = None,
        limit: Optional[int] = None,
        max_nodes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves graph nodes and edges for repository visualization with optional filtering.
        """
        effective_limit = limit if limit is not None else (max_nodes if max_nodes is not None else node_limit)
        node_limit = effective_limit
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            return {
                "repository_id": repository_id,
                "nodes": [],
                "edges": [],
                "summary": {
                    "total_nodes": 0,
                    "total_edges": 0,
                    "displayed_nodes": 0,
                    "displayed_edges": 0,
                    "node_types": {},
                    "edge_types": {},
                },
            }

        node_query = db.query(GraphNode).filter(GraphNode.repository_id == repository_id)

        if node_type:
            types = [t.strip().lower() for t in node_type.split(",") if t.strip()]
            if types:
                node_query = node_query.filter(func.lower(GraphNode.node_type).in_(types))

        if file_path:
            clean_fp = file_path.strip().replace("\\", "/")
            node_query = node_query.filter(GraphNode.file_path.ilike(f"%{clean_fp}%"))

        nodes = node_query.limit(min(max(1, node_limit), 300)).all()
        node_ids = {n.id for n in nodes}
        node_name_map = {n.id: n.name for n in nodes}

        edges = []
        if node_ids:
            edge_query = db.query(GraphEdge).filter(
                GraphEdge.repository_id == repository_id,
                GraphEdge.source_node_id.in_(node_ids),
                GraphEdge.target_node_id.in_(node_ids),
            )
            if edge_type:
                etypes = [e.strip().upper() for e in edge_type.split(",") if e.strip()]
                if etypes:
                    edge_query = edge_query.filter(GraphEdge.edge_type.in_(etypes))

            edges = edge_query.all()

        serialized_nodes = []
        for n in nodes:
            props = {}
            try:
                props = json.loads(n.properties) if n.properties else {}
            except Exception:
                pass
            serialized_nodes.append({
                "id": n.id,
                "key": n.node_key,
                "type": n.node_type,
                "name": n.name,
                "file_path": n.file_path,
                "symbol_name": n.symbol_name,
                "signature": n.signature,
                "start_line": n.start_line,
                "end_line": n.end_line,
                "language": n.language,
                "properties": props,
            })

        serialized_edges = [
            {
                "id": e.id,
                "source": e.source_node_id,
                "target": e.target_node_id,
                "source_node_id": e.source_node_id,
                "target_node_id": e.target_node_id,
                "type": e.edge_type,
                "edge_type": e.edge_type,
                "is_verified": e.is_verified,
                "evidence": e.evidence,
                "source_name": node_name_map.get(e.source_node_id, f"Node {e.source_node_id}"),
                "target_name": node_name_map.get(e.target_node_id, f"Node {e.target_node_id}"),
            }
            for e in edges
        ]

        total_nodes = db.query(GraphNode).filter(GraphNode.repository_id == repository_id).count()
        total_edges = db.query(GraphEdge).filter(GraphEdge.repository_id == repository_id).count()

        # Breakdown stats
        node_type_counts = dict(
            db.query(GraphNode.node_type, func.count(GraphNode.id))
            .filter(GraphNode.repository_id == repository_id)
            .group_by(GraphNode.node_type)
            .all()
        )
        edge_type_counts = dict(
            db.query(GraphEdge.edge_type, func.count(GraphEdge.id))
            .filter(GraphEdge.repository_id == repository_id)
            .group_by(GraphEdge.edge_type)
            .all()
        )

        return {
            "repository_id": repository_id,
            "nodes": serialized_nodes,
            "edges": serialized_edges,
            "summary": {
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "displayed_nodes": len(serialized_nodes),
                "displayed_edges": len(serialized_edges),
                "node_types": node_type_counts,
                "edge_types": edge_type_counts,
            },
        }

    @classmethod
    def get_node_neighbors(
        cls,
        db: Session,
        repository_id: int,
        node_id: int,
        depth: int = 1,
        relationship_type: Optional[str] = None,
        direction: str = "both",
    ) -> Dict[str, Any]:
        """
        Retrieves 1-hop and multi-hop incoming and outgoing connections for a specific node.
        Clearly categorizes direct (depth 1) from transitive (depth > 1) relationships.
        Detects cycles to guarantee bounded traversal.
        """
        depth = min(max(1, depth), 4)
        target_node = (
            db.query(GraphNode)
            .filter(GraphNode.repository_id == repository_id, GraphNode.id == node_id)
            .first()
        )
        if not target_node:
            return {
                "node": None,
                "incoming": [],
                "outgoing": [],
                "direct_incoming": [],
                "direct_outgoing": [],
                "transitive_incoming": [],
                "transitive_outgoing": [],
                "depth": depth,
                "has_cycles": False,
            }

        rel_filter = None
        if relationship_type and relationship_type.strip().upper() != "ALL":
            rel_filter = [r.strip().upper() for r in relationship_type.split(",") if r.strip()]

        direct_outgoing: List[Dict[str, Any]] = []
        transitive_outgoing: List[Dict[str, Any]] = []
        direct_incoming: List[Dict[str, Any]] = []
        transitive_incoming: List[Dict[str, Any]] = []
        has_cycles = False

        # --- OUTGOING TRAVERSAL (current -> target) ---
        if direction.lower() in ("both", "outgoing"):
            out_queue = deque([(node_id, 1, [node_id])])
            visited_out: Set[int] = {node_id}

            while out_queue:
                curr_id, curr_depth, path = out_queue.popleft()
                if curr_depth > depth:
                    continue

                q = (
                    db.query(GraphEdge, GraphNode)
                    .join(GraphNode, GraphEdge.target_node_id == GraphNode.id)
                    .filter(
                        GraphEdge.repository_id == repository_id,
                        GraphEdge.source_node_id == curr_id,
                    )
                )
                if rel_filter:
                    q = q.filter(GraphEdge.edge_type.in_(rel_filter))

                edges = q.all()

                for edge, node in edges:
                    item = {
                        "id": node.id,
                        "name": node.name,
                        "type": node.node_type,
                        "file_path": node.file_path,
                        "symbol_name": node.symbol_name,
                        "start_line": node.start_line,
                        "end_line": node.end_line,
                        "edge_type": edge.edge_type,
                        "is_verified": edge.is_verified,
                        "evidence": edge.evidence,
                        "depth": curr_depth,
                        "source_id": edge.source_node_id,
                    }

                    if node.id in path:
                        has_cycles = True

                    if curr_depth == 1:
                        if not any(d["id"] == node.id and d["edge_type"] == edge.edge_type for d in direct_outgoing):
                            direct_outgoing.append(item)
                    else:
                        if not any(d["id"] == node.id and d["edge_type"] == edge.edge_type for d in transitive_outgoing):
                            transitive_outgoing.append(item)

                    if node.id not in visited_out and curr_depth < depth:
                        visited_out.add(node.id)
                        out_queue.append((node.id, curr_depth + 1, path + [node.id]))

        # --- INCOMING TRAVERSAL (source -> current) ---
        if direction.lower() in ("both", "incoming"):
            in_queue = deque([(node_id, 1, [node_id])])
            visited_in: Set[int] = {node_id}

            while in_queue:
                curr_id, curr_depth, path = in_queue.popleft()
                if curr_depth > depth:
                    continue

                q = (
                    db.query(GraphEdge, GraphNode)
                    .join(GraphNode, GraphEdge.source_node_id == GraphNode.id)
                    .filter(
                        GraphEdge.repository_id == repository_id,
                        GraphEdge.target_node_id == curr_id,
                    )
                )
                if rel_filter:
                    q = q.filter(GraphEdge.edge_type.in_(rel_filter))

                edges = q.all()

                for edge, node in edges:
                    item = {
                        "id": node.id,
                        "name": node.name,
                        "type": node.node_type,
                        "file_path": node.file_path,
                        "symbol_name": node.symbol_name,
                        "start_line": node.start_line,
                        "end_line": node.end_line,
                        "edge_type": edge.edge_type,
                        "is_verified": edge.is_verified,
                        "evidence": edge.evidence,
                        "depth": curr_depth,
                        "target_id": edge.target_node_id,
                    }

                    if node.id in path:
                        has_cycles = True

                    if curr_depth == 1:
                        if not any(d["id"] == node.id and d["edge_type"] == edge.edge_type for d in direct_incoming):
                            direct_incoming.append(item)
                    else:
                        if not any(d["id"] == node.id and d["edge_type"] == edge.edge_type for d in transitive_incoming):
                            transitive_incoming.append(item)

                    if node.id not in visited_in and curr_depth < depth:
                        visited_in.add(node.id)
                        in_queue.append((node.id, curr_depth + 1, path + [node.id]))

        # Combine into legacy format for backward compatibility
        incoming_legacy = [
            {
                "edge_type": d["edge_type"],
                "is_verified": d["is_verified"],
                "evidence": d["evidence"],
                "source": {
                    "id": d["id"],
                    "name": d["name"],
                    "type": d["type"],
                    "file_path": d["file_path"],
                },
            }
            for d in direct_incoming
        ]

        outgoing_legacy = [
            {
                "edge_type": d["edge_type"],
                "is_verified": d["is_verified"],
                "evidence": d["evidence"],
                "target": {
                    "id": d["id"],
                    "name": d["name"],
                    "type": d["type"],
                    "file_path": d["file_path"],
                },
            }
            for d in direct_outgoing
        ]

        direct_neighbors = [
            {**d, "node": d, "direction": "outgoing"} for d in direct_outgoing
        ] + [
            {**d, "node": d, "direction": "incoming"} for d in direct_incoming
        ]

        transitive_neighbors = [
            {**t, "node": t, "direction": "outgoing"} for t in transitive_outgoing
        ] + [
            {**t, "node": t, "direction": "incoming"} for t in transitive_incoming
        ]

        return {
            "node": {
                "id": target_node.id,
                "key": target_node.node_key,
                "name": target_node.name,
                "type": target_node.node_type,
                "file_path": target_node.file_path,
                "symbol_name": target_node.symbol_name,
                "signature": target_node.signature,
                "start_line": target_node.start_line,
                "end_line": target_node.end_line,
                "language": target_node.language,
            },
            "incoming": incoming_legacy,
            "outgoing": outgoing_legacy,
            "direct_incoming": direct_incoming,
            "direct_outgoing": direct_outgoing,
            "transitive_incoming": transitive_incoming,
            "transitive_outgoing": transitive_outgoing,
            "direct_neighbors": direct_neighbors,
            "transitive_neighbors": transitive_neighbors,
            "depth": depth,
            "has_cycles": has_cycles,
        }

    @classmethod
    def find_path(
        cls,
        db: Session,
        repository_id: int,
        start_node_id: int,
        end_node_id: int,
        max_depth: int = 4,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Finds the shortest dependency/call path between two components using BFS traversal.
        """
        if start_node_id == end_node_id:
            return []

        queue = deque([(start_node_id, [])])
        visited: Set[int] = {start_node_id}

        while queue:
            current_id, path = queue.popleft()
            if len(path) >= max_depth:
                continue

            edges = (
                db.query(GraphEdge, GraphNode)
                .join(GraphNode, GraphEdge.target_node_id == GraphNode.id)
                .filter(
                    GraphEdge.repository_id == repository_id,
                    GraphEdge.source_node_id == current_id,
                )
                .all()
            )

            for edge, target_node in edges:
                new_path = path + [
                    {
                        "source_id": edge.source_node_id,
                        "target_id": edge.target_node_id,
                        "edge_type": edge.edge_type,
                        "evidence": edge.evidence,
                        "target_name": target_node.name,
                        "target_type": target_node.node_type,
                    }
                ]
                if edge.target_node_id == end_node_id:
                    return new_path

                if edge.target_node_id not in visited:
                    visited.add(edge.target_node_id)
                    queue.append((edge.target_node_id, new_path))

        return None
