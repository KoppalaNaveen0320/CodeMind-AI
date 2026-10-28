import logging
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.knowledge_graph import GraphEdge, GraphNode
from backend.app.models.repository import Repository
from backend.app.schemas.graph import CallHierarchyItem, CallHierarchyResponse

logger = logging.getLogger(__name__)


class CallHierarchyService:
    """
    Verified Function and Method Call Hierarchy Service.
    Traces incoming callers and outgoing callees with cycle detection,
    bounded depth traversal, ambiguity flagging, and source-grounded coordinates.
    """

    @classmethod
    def get_call_hierarchy_by_id(
        cls,
        db: Session,
        repository_id: int,
        symbol_id: int,
        direction: str = "both",
        max_depth: int = 2,
    ) -> CallHierarchyResponse:
        """
        Builds call hierarchy for a specific CodeSymbol ID.
        """
        max_depth = min(max(1, max_depth), 5)

        sym_row = (
            db.query(CodeSymbol, IndexedFile, Repository)
            .join(IndexedFile, CodeSymbol.file_id == IndexedFile.id)
            .join(Repository, CodeSymbol.repository_id == Repository.id)
            .filter(
                CodeSymbol.id == symbol_id,
                CodeSymbol.repository_id == repository_id,
            )
            .first()
        )
        if not sym_row:
            return CallHierarchyResponse(
                repository_id=repository_id,
                target_symbol={"id": symbol_id, "error": "Symbol not found in repository"},
                direction=direction,
                max_depth=max_depth,
                is_ambiguous=False,
                explanation="Symbol not found in repository index.",
            )

        sym, ifile, repo = sym_row
        target_info = {
            "symbol_id": sym.id,
            "name": sym.name,
            "kind": sym.kind,
            "file_path": ifile.path,
            "start_line": sym.start_line,
            "end_line": sym.end_line,
            "signature": sym.signature,
            "language": ifile.language,
        }

        # Find corresponding graph node (prefer matching start_line to disambiguate same-named symbols)
        node_query = db.query(GraphNode).filter(
            GraphNode.repository_id == repository_id,
            GraphNode.file_path == ifile.path,
            or_(
                GraphNode.name == sym.name,
                GraphNode.symbol_name == sym.name,
                GraphNode.name == sym.name.split(".")[-1],
            ),
        )
        node = None
        if sym.start_line is not None:
            node = node_query.filter(GraphNode.start_line == sym.start_line).first()
        if not node:
            node = node_query.first()

        if not node:
            return CallHierarchyResponse(
                repository_id=repository_id,
                repository_name=repo.name,
                target_symbol=target_info,
                direction=direction,
                max_depth=max_depth,
                is_ambiguous=False,
                callers=[],
                callees=[],
                explanation="No graph node exists for this symbol. No callers or callees mapped.",
            )

        return cls._build_hierarchy(
            db=db,
            repository=repo,
            root_node=node,
            target_info=target_info,
            direction=direction,
            max_depth=max_depth,
        )

    @classmethod
    def get_call_hierarchy_by_name(
        cls,
        db: Session,
        repository_id: int,
        symbol_name: str,
        file_path: Optional[str] = None,
        direction: str = "both",
        max_depth: int = 2,
    ) -> CallHierarchyResponse:
        """
        Builds call hierarchy by symbol name, with ambiguity detection when multiple
        candidates exist across different files.
        """
        max_depth = min(max(1, max_depth), 5)
        clean_name = symbol_name.strip()
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            return CallHierarchyResponse(
                repository_id=repository_id,
                target_symbol={"name": clean_name, "error": "Repository not found"},
                direction=direction,
                max_depth=max_depth,
                explanation="Repository not found.",
            )

        query = (
            db.query(CodeSymbol, IndexedFile)
            .join(IndexedFile, CodeSymbol.file_id == IndexedFile.id)
            .filter(
                CodeSymbol.repository_id == repository_id,
                or_(
                    CodeSymbol.name == clean_name,
                    CodeSymbol.name.endswith(f".{clean_name}"),
                ),
                CodeSymbol.kind.in_(["function", "method", "class"]),
            )
        )

        if file_path:
            clean_fp = file_path.strip().replace("\\", "/")
            query = query.filter(IndexedFile.path.ilike(f"%{clean_fp}%"))

        candidates = query.all()

        if not candidates:
            # Check graph nodes directly as fallback
            node_q = db.query(GraphNode).filter(
                GraphNode.repository_id == repository_id,
                or_(
                    GraphNode.name == clean_name,
                    GraphNode.symbol_name == clean_name,
                ),
                GraphNode.node_type.in_(["function", "method", "class"]),
            )
            if file_path:
                node_q = node_q.filter(GraphNode.file_path.ilike(f"%{file_path}%"))
            direct_nodes = node_q.all()

            if not direct_nodes:
                return CallHierarchyResponse(
                    repository_id=repository_id,
                    repository_name=repo.name,
                    target_symbol={"name": clean_name, "file_path": file_path},
                    direction=direction,
                    max_depth=max_depth,
                    is_ambiguous=False,
                    explanation=f"Function or method '{clean_name}' was not found in the indexed repository source.",
                )

            if len(direct_nodes) > 1 and not file_path:
                cand_list = [
                    {
                        "node_id": n.id,
                        "name": n.name,
                        "kind": n.node_type,
                        "file_path": n.file_path,
                        "start_line": n.start_line,
                        "end_line": n.end_line,
                    }
                    for n in direct_nodes
                ]
                all_callers = []
                all_callees = []
                seen_callers = set()
                seen_callees = set()
                for cand_node in direct_nodes:
                    cand_info = {
                        "name": cand_node.name,
                        "kind": cand_node.node_type,
                        "file_path": cand_node.file_path,
                        "start_line": cand_node.start_line,
                        "end_line": cand_node.end_line,
                        "signature": cand_node.signature,
                    }
                    sub_h = cls._build_hierarchy(
                        db=db,
                        repository=repo,
                        root_node=cand_node,
                        target_info=cand_info,
                        direction=direction,
                        max_depth=max_depth,
                    )
                    for item in sub_h.callers:
                        c_key = (item.caller_name or item.symbol_name, item.caller_file_path or item.file_path, item.caller_start_line or item.start_line)
                        if c_key not in seen_callers:
                            seen_callers.add(c_key)
                            all_callers.append(item)
                    for item in sub_h.callees:
                        c_key = (item.callee_name or item.symbol_name, item.callee_file_path or item.file_path, item.callee_start_line or item.start_line)
                        if c_key not in seen_callees:
                            seen_callees.add(c_key)
                            all_callees.append(item)

                return CallHierarchyResponse(
                    repository_id=repository_id,
                    repository_name=repo.name,
                    target_symbol={"name": clean_name},
                    direction=direction,
                    max_depth=max_depth,
                    is_ambiguous=True,
                    candidates=cand_list,
                    ambiguous_candidates=cand_list,
                    callers=all_callers,
                    callees=all_callees,
                    total_callers=len(all_callers),
                    total_callees=len(all_callees),
                    explanation=f"Ambiguous symbol: Found {len(direct_nodes)} candidates named '{clean_name}' across different files. Aggregated verified call relationships from all candidates.",
                )

            chosen_node = direct_nodes[0]
            target_info = {
                "name": chosen_node.name,
                "kind": chosen_node.node_type,
                "file_path": chosen_node.file_path,
                "start_line": chosen_node.start_line,
                "end_line": chosen_node.end_line,
                "signature": chosen_node.signature,
            }
            return cls._build_hierarchy(
                db=db,
                repository=repo,
                root_node=chosen_node,
                target_info=target_info,
                direction=direction,
                max_depth=max_depth,
            )

        if len(candidates) > 1 and not file_path:
            cand_list = [
                {
                    "symbol_id": s.id,
                    "name": s.name,
                    "kind": s.kind,
                    "file_path": f.path,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s, f in candidates
            ]
            all_callers = []
            all_callees = []
            seen_callers = set()
            seen_callees = set()
            for s, f in candidates:
                try:
                    sub_h = cls.get_call_hierarchy_by_id(
                        db=db,
                        repository_id=repository_id,
                        symbol_id=s.id,
                        direction=direction,
                        max_depth=max_depth,
                    )
                    for item in sub_h.callers:
                        c_key = (item.caller_name or item.symbol_name, item.caller_file_path or item.file_path, item.caller_start_line or item.start_line)
                        if c_key not in seen_callers:
                            seen_callers.add(c_key)
                            all_callers.append(item)
                    for item in sub_h.callees:
                        c_key = (item.callee_name or item.symbol_name, item.callee_file_path or item.file_path, item.callee_start_line or item.start_line)
                        if c_key not in seen_callees:
                            seen_callees.add(c_key)
                            all_callees.append(item)
                except Exception:
                    pass

            return CallHierarchyResponse(
                repository_id=repository_id,
                repository_name=repo.name,
                target_symbol={"name": clean_name},
                direction=direction,
                max_depth=max_depth,
                is_ambiguous=True,
                candidates=cand_list,
                ambiguous_candidates=cand_list,
                callers=all_callers,
                callees=all_callees,
                total_callers=len(all_callers),
                total_callees=len(all_callees),
                explanation=f"Ambiguous symbol: Found {len(candidates)} candidates named '{clean_name}' across different files. Aggregated verified call relationships from all candidates.",
            )

        sym, ifile = candidates[0]
        return cls.get_call_hierarchy_by_id(
            db=db,
            repository_id=repository_id,
            symbol_id=sym.id,
            direction=direction,
            max_depth=max_depth,
        )

    @classmethod
    def _build_hierarchy(
        cls,
        db: Session,
        repository: Repository,
        root_node: GraphNode,
        target_info: Dict[str, Any],
        direction: str,
        max_depth: int,
    ) -> CallHierarchyResponse:
        """
        Traverses callers (incoming) and callees (outgoing) with cycle prevention.
        """
        has_cycles = False
        callers: List[CallHierarchyItem] = []
        callees: List[CallHierarchyItem] = []

        # 1. Trace Callers (Incoming CALLS edges)
        if direction in ("both", "callers"):
            callers_tree, cycle_found = cls._trace_callers(
                db=db,
                repository_id=repository.id,
                current_node_id=root_node.id,
                current_depth=1,
                max_depth=max_depth,
                visited_path={root_node.id},
            )
            callers = callers_tree
            if cycle_found:
                has_cycles = True

        # 2. Trace Callees (Outgoing CALLS edges)
        if direction in ("both", "callees"):
            callees_tree, cycle_found = cls._trace_callees(
                db=db,
                repository_id=repository.id,
                current_node_id=root_node.id,
                current_depth=1,
                max_depth=max_depth,
                visited_path={root_node.id},
            )
            callees = callees_tree
            if cycle_found:
                has_cycles = True

        def count_tree(items: List[CallHierarchyItem]) -> int:
            total = len(items)
            for it in items:
                if it.calls:
                    total += len(it.calls)
            return total

        return CallHierarchyResponse(
            repository_id=repository.id,
            repository_name=repository.name,
            target_symbol=target_info,
            direction=direction,
            max_depth=max_depth,
            has_cycles=has_cycles,
            callers=callers,
            callees=callees,
            total_callers=count_tree(callers),
            total_callees=count_tree(callees),
            is_ambiguous=False,
            candidates=[],
            explanation="Call hierarchy successfully resolved from verified static call analysis.",
        )

    @classmethod
    def _trace_callers(
        cls,
        db: Session,
        repository_id: int,
        current_node_id: int,
        current_depth: int,
        max_depth: int,
        visited_path: Set[int],
    ) -> (List[CallHierarchyItem], bool):
        if current_depth > max_depth:
            return [], False

        incoming_edges = (
            db.query(GraphEdge, GraphNode)
            .join(GraphNode, GraphEdge.source_node_id == GraphNode.id)
            .filter(
                GraphEdge.repository_id == repository_id,
                GraphEdge.target_node_id == current_node_id,
                GraphEdge.edge_type == "CALLS",
            )
            .limit(25)
            .all()
        )

        items: List[CallHierarchyItem] = []
        cycle_detected = False

        for edge, caller_node in incoming_edges:
            is_cycle = caller_node.id in visited_path
            if is_cycle:
                cycle_detected = True

            sym = None
            if caller_node.file_path:
                sq = (
                    db.query(CodeSymbol)
                    .join(IndexedFile, CodeSymbol.file_id == IndexedFile.id)
                    .filter(
                        CodeSymbol.repository_id == repository_id,
                        IndexedFile.path == caller_node.file_path,
                        or_(
                            CodeSymbol.name == caller_node.name,
                            CodeSymbol.name == caller_node.symbol_name,
                            CodeSymbol.name.endswith(f".{caller_node.name}"),
                        ),
                    )
                )
                if caller_node.start_line is not None:
                    sym = sq.filter(CodeSymbol.start_line == caller_node.start_line).first()
                if not sym:
                    sym = sq.first()

            if not sym:
                sym = (
                    db.query(CodeSymbol)
                    .filter(
                        CodeSymbol.repository_id == repository_id,
                        CodeSymbol.name == caller_node.name,
                    )
                    .first()
                )

            # Determine true call site line from edge evidence if recorded
            call_site_line = caller_node.start_line or (sym.start_line if sym else None)
            if edge.evidence:
                import re
                m = re.search(r"at line (\d+)", edge.evidence)
                if m:
                    call_site_line = int(m.group(1))

            nested_calls: List[Dict[str, Any]] = []
            if not is_cycle and current_depth < max_depth:
                sub_items, sub_cycle = cls._trace_callers(
                    db=db,
                    repository_id=repository_id,
                    current_node_id=caller_node.id,
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    visited_path=visited_path | {caller_node.id},
                )
                if sub_cycle:
                    cycle_detected = True
                nested_calls = [it.model_dump() if hasattr(it, "model_dump") else it.dict() for it in sub_items]

            items.append(
                CallHierarchyItem(
                    node_id=caller_node.id,
                    symbol_id=sym.id if sym else None,
                    symbol_name=caller_node.name,
                    caller_name=caller_node.name,
                    kind=caller_node.node_type,
                    file_path=caller_node.file_path or (sym.file.path if sym and sym.file else ""),
                    caller_file_path=caller_node.file_path or (sym.file.path if sym and sym.file else ""),
                    start_line=caller_node.start_line or (sym.start_line if sym else None),
                    end_line=caller_node.end_line or (sym.end_line if sym else None),
                    caller_start_line=caller_node.start_line or (sym.start_line if sym else None),
                    caller_end_line=caller_node.end_line or (sym.end_line if sym else None),
                    call_line=call_site_line,
                    call_site_line=call_site_line,
                    evidence=edge.evidence,
                    is_verified=edge.is_verified,
                    is_ambiguous=False,
                    depth=current_depth,
                    calls=nested_calls,
                )
            )

        return items, cycle_detected

    @classmethod
    def _trace_callees(
        cls,
        db: Session,
        repository_id: int,
        current_node_id: int,
        current_depth: int,
        max_depth: int,
        visited_path: Set[int],
    ) -> (List[CallHierarchyItem], bool):
        if current_depth > max_depth:
            return [], False

        outgoing_edges = (
            db.query(GraphEdge, GraphNode)
            .join(GraphNode, GraphEdge.target_node_id == GraphNode.id)
            .filter(
                GraphEdge.repository_id == repository_id,
                GraphEdge.source_node_id == current_node_id,
                GraphEdge.edge_type == "CALLS",
            )
            .limit(25)
            .all()
        )

        items: List[CallHierarchyItem] = []
        cycle_detected = False

        for edge, callee_node in outgoing_edges:
            is_cycle = callee_node.id in visited_path
            if is_cycle:
                cycle_detected = True

            sym = None
            if callee_node.file_path:
                sq = (
                    db.query(CodeSymbol)
                    .join(IndexedFile, CodeSymbol.file_id == IndexedFile.id)
                    .filter(
                        CodeSymbol.repository_id == repository_id,
                        IndexedFile.path == callee_node.file_path,
                        or_(
                            CodeSymbol.name == callee_node.name,
                            CodeSymbol.name == callee_node.symbol_name,
                            CodeSymbol.name.endswith(f".{callee_node.name}"),
                        ),
                    )
                )
                if callee_node.start_line is not None:
                    sym = sq.filter(CodeSymbol.start_line == callee_node.start_line).first()
                if not sym:
                    sym = sq.first()

            if not sym:
                sym = (
                    db.query(CodeSymbol)
                    .filter(
                        CodeSymbol.repository_id == repository_id,
                        CodeSymbol.name == callee_node.name,
                    )
                    .first()
                )

            call_site_line = callee_node.start_line or (sym.start_line if sym else None)
            if edge.evidence:
                import re
                m = re.search(r"at line (\d+)", edge.evidence)
                if m:
                    call_site_line = int(m.group(1))

            nested_calls: List[Dict[str, Any]] = []
            if not is_cycle and current_depth < max_depth:
                sub_items, sub_cycle = cls._trace_callees(
                    db=db,
                    repository_id=repository_id,
                    current_node_id=callee_node.id,
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    visited_path=visited_path | {callee_node.id},
                )
                if sub_cycle:
                    cycle_detected = True
                nested_calls = [it.model_dump() if hasattr(it, "model_dump") else it.dict() for it in sub_items]

            items.append(
                CallHierarchyItem(
                    node_id=callee_node.id,
                    symbol_id=sym.id if sym else None,
                    symbol_name=callee_node.name,
                    callee_name=callee_node.name,
                    kind=callee_node.node_type,
                    file_path=callee_node.file_path or (sym.file.path if sym and sym.file else ""),
                    callee_file_path=callee_node.file_path or (sym.file.path if sym and sym.file else ""),
                    start_line=callee_node.start_line or (sym.start_line if sym else None),
                    end_line=callee_node.end_line or (sym.end_line if sym else None),
                    callee_start_line=callee_node.start_line or (sym.start_line if sym else None),
                    callee_end_line=callee_node.end_line or (sym.end_line if sym else None),
                    call_line=call_site_line,
                    call_site_line=call_site_line,
                    evidence=edge.evidence,
                    is_verified=edge.is_verified,
                    is_ambiguous=False,
                    depth=current_depth,
                    calls=nested_calls,
                )
            )

        return items, cycle_detected
