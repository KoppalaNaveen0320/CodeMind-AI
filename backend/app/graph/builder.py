import json
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.parsing.extractor import ExtractedCall

logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """
    Constructs a queryable Knowledge Graph from parsed source files, symbols,
    imports, and static call expressions.
    Ensures strict deduplication, verified static relationships, and atomic re-indexing.
    """

    @classmethod
    def build_graph_for_repository(
        cls,
        db: Session,
        repository: Repository,
        files: List[IndexedFile],
        symbols_by_file: Dict[int, List[CodeSymbol]],
        calls_by_file: Optional[Dict[int, List[ExtractedCall]]] = None,
        revision: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        Builds or rebuilds graph nodes and edges for the repository.
        Returns: (nodes_count, edges_count)
        """
        # 1. Clean existing stale graph nodes and edges for this repo
        db.query(GraphEdge).filter(GraphEdge.repository_id == repository.id).delete()
        db.query(GraphNode).filter(GraphNode.repository_id == repository.id).delete()
        db.flush()

        node_map: Dict[str, GraphNode] = {}
        created_edges_set: Set[Tuple[str, str, str]] = set()
        edges_to_add: List[GraphEdge] = []
        rev = revision or repository.current_revision or "HEAD"

        # Helper to get or create node
        def get_or_create_node(
            node_key: str,
            node_type: str,
            name: str,
            file_path: Optional[str] = None,
            symbol_name: Optional[str] = None,
            signature: Optional[str] = None,
            start_line: Optional[int] = None,
            end_line: Optional[int] = None,
            language: Optional[str] = None,
            properties: Optional[dict] = None,
        ) -> GraphNode:
            clean_node_key = node_key.replace("\x00", "")[:500]
            if clean_node_key in node_map:
                return node_map[clean_node_key]

            clean_name = name.replace("\x00", "")[:255]
            clean_file_path = file_path.replace("\x00", "")[:500] if file_path else None
            clean_symbol_name = symbol_name.replace("\x00", "")[:255] if symbol_name else None
            clean_signature = signature.replace("\x00", "") if signature else None
            clean_props = json.dumps(properties or {}).replace("\x00", "")

            node = GraphNode(
                repository_id=repository.id,
                node_key=clean_node_key,
                node_type=node_type[:50],
                name=clean_name,
                file_path=clean_file_path,
                symbol_name=clean_symbol_name,
                signature=clean_signature,
                start_line=start_line,
                end_line=end_line,
                language=language[:50] if language else None,
                source_revision=rev[:100] if rev else None,
                properties=clean_props,
            )
            db.add(node)
            db.flush()
            node_map[clean_node_key] = node
            return node

        # Helper to add edge with deduplication
        def add_edge(
            source_node: GraphNode,
            target_node: GraphNode,
            edge_type: str,
            is_verified: bool = True,
            evidence: Optional[str] = None,
        ):
            if source_node.id == target_node.id and edge_type != "CALLS":
                return
            edge_key = (source_node.node_key, target_node.node_key, edge_type)
            if edge_key in created_edges_set:
                return

            created_edges_set.add(edge_key)
            clean_evidence = evidence.replace("\x00", "") if evidence else None
            edge = GraphEdge(
                repository_id=repository.id,
                source_node_id=source_node.id,
                target_node_id=target_node.id,
                edge_type=edge_type,
                is_verified=is_verified,
                source_revision=rev,
                evidence=clean_evidence,
            )
            edges_to_add.append(edge)

        # 2. Create Root Repository Node
        repo_node_key = f"repo:{repository.id}"
        repo_node = get_or_create_node(
            node_key=repo_node_key,
            node_type="repository",
            name=repository.name,
            properties={"full_name": repository.full_name, "default_branch": repository.default_branch},
        )

        # Fast lookup for files by normalized path and by basename
        file_by_path: Dict[str, IndexedFile] = {f.path: f for f in files}
        file_by_name: Dict[str, List[IndexedFile]] = {}
        for f in files:
            bname = f.path.split("/")[-1].split(".")[0]
            file_by_name.setdefault(bname, []).append(f)

        # 3. Create File and Symbol Nodes
        symbol_nodes_by_name: Dict[str, List[GraphNode]] = {}
        imported_files_by_source: Dict[str, Set[str]] = {}

        for indexed_file in files:
            file_node_key = f"repo:{repository.id}:file:{indexed_file.path}"
            file_name = indexed_file.path.split("/")[-1]
            file_node = get_or_create_node(
                node_key=file_node_key,
                node_type="file",
                name=file_name,
                file_path=indexed_file.path,
                language=indexed_file.language,
                properties={"lines_count": indexed_file.lines_count, "size_bytes": indexed_file.size_bytes},
            )
            add_edge(repo_node, file_node, "CONTAINS", is_verified=True, evidence=f"File in repository {repository.name}")

            file_symbols = symbols_by_file.get(indexed_file.id, [])
            classes_in_file: Dict[str, GraphNode] = {}

            # First pass: create class nodes
            for sym in file_symbols:
                if sym.kind == "class":
                    sym_node_key = f"repo:{repository.id}:symbol:{indexed_file.path}:{sym.name}"
                    sym_node = get_or_create_node(
                        node_key=sym_node_key,
                        node_type="class",
                        name=sym.name,
                        file_path=indexed_file.path,
                        symbol_name=sym.name,
                        signature=sym.signature,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        language=indexed_file.language,
                    )
                    add_edge(file_node, sym_node, "CONTAINS", is_verified=True, evidence=f"Class defined in {indexed_file.path}:{sym.start_line}")
                    classes_in_file[sym.name] = sym_node
                    symbol_nodes_by_name.setdefault(sym.name, []).append(sym_node)

            # Second pass: functions, methods, imports
            for sym in file_symbols:
                if sym.kind in ("function", "method"):
                    sym_node_key = f"repo:{repository.id}:symbol:{indexed_file.path}:{sym.name}"
                    parent_class = None
                    simple_name = sym.name
                    if "." in sym.name:
                        parts = sym.name.split(".", 1)
                        parent_class = parts[0]
                        simple_name = parts[1]

                    sym_node = get_or_create_node(
                        node_key=sym_node_key,
                        node_type="method" if parent_class else "function",
                        name=simple_name,
                        file_path=indexed_file.path,
                        symbol_name=sym.name,
                        signature=sym.signature,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        language=indexed_file.language,
                    )
                    symbol_nodes_by_name.setdefault(simple_name, []).append(sym_node)
                    if sym.name != simple_name:
                        symbol_nodes_by_name.setdefault(sym.name, []).append(sym_node)

                    if parent_class and parent_class in classes_in_file:
                        add_edge(classes_in_file[parent_class], sym_node, "DEFINES", is_verified=True, evidence=f"Method in {parent_class} at line {sym.start_line}")
                    else:
                        add_edge(file_node, sym_node, "CONTAINS", is_verified=True, evidence=f"Function in {indexed_file.path} at line {sym.start_line}")

                elif sym.kind == "import":
                    cls._process_import_symbol(
                        db, repository, indexed_file, file_node, sym,
                        file_by_path, file_by_name, get_or_create_node, add_edge,
                        imported_files_by_source
                    )


        # 4. Verified Static CALLS across all files (executed after all file symbols are indexed)
        file_by_id: Dict[int, IndexedFile] = {f.id: f for f in files}
        if calls_by_file:
            for file_id, file_calls in calls_by_file.items():
                indexed_file = file_by_id.get(file_id)
                if not indexed_file:
                    continue
                for call in file_calls:
                    # Find caller node in current file (prefer node enclosing call.line_number)
                    file_callers = [
                        n for n in symbol_nodes_by_name.get(call.caller_name, [])
                        if n.file_path == indexed_file.path
                    ]
                    if not file_callers:
                        continue
                    enclosing_callers = [
                        n for n in file_callers
                        if n.start_line is not None and n.end_line is not None and n.start_line <= call.line_number <= n.end_line
                    ]
                    caller_nodes = enclosing_callers if enclosing_callers else file_callers

                    # Find callee node (strictly within same file or explicitly imported files)
                    raw_callee_candidates = symbol_nodes_by_name.get(call.callee_name, [])
                    if not raw_callee_candidates:
                        continue

                    # Deduplicate candidate nodes
                    seen_c_ids = set()
                    callee_candidates = []
                    for c in raw_callee_candidates:
                        c_id = id(c) if c.id is None else c.id
                        if c_id not in seen_c_ids:
                            seen_c_ids.add(c_id)
                            callee_candidates.append(c)

                    local_callees = [c for c in callee_candidates if c.file_path == indexed_file.path]
                    callee_node = None
                    call_receiver = getattr(call, "receiver", None)

                    if call_receiver in ("self", "cls"):
                        # Internal method invocation on same class/file
                        callee_node = local_callees[0] if local_callees else None
                    elif call_receiver and call_receiver not in ("self", "cls"):
                        # Explicit receiver like DashboardService.get_dashboard or service.get_dashboard
                        imported_paths = imported_files_by_source.get(indexed_file.path, set())
                        receiver_str = str(call_receiver).lower().replace("_", "")
                        # 1. Match imported files where receiver matches the path
                        imported_callees = [c for c in callee_candidates if c.file_path in imported_paths]
                        matching_receiver = [c for c in imported_callees if receiver_str in c.file_path.lower().replace("_", "")]
                        if matching_receiver:
                            callee_node = matching_receiver[0]
                        elif imported_callees:
                            callee_node = imported_callees[0]
                        else:
                            # 2. Match any callee candidate where receiver matches the path
                            matching_all = [c for c in callee_candidates if receiver_str in c.file_path.lower().replace("_", "")]
                            if matching_all:
                                callee_node = matching_all[0]
                            elif len(callee_candidates) == 1:
                                callee_node = callee_candidates[0]
                    elif local_callees:
                        # Local call within same file (bare function invocation e.g. helper_func())
                        callee_node = local_callees[0]
                    else:
                        # Cross-file call with no receiver: require verified import of target file or unambiguous single repo candidate
                        imported_paths = imported_files_by_source.get(indexed_file.path, set())
                        if imported_paths:
                            imported_callees = [c for c in callee_candidates if c.file_path in imported_paths]
                            if imported_callees:
                                callee_node = imported_callees[0]
                        elif len(callee_candidates) == 1:
                            # File has no parsed imports (e.g. unit test or standalone script) and callee symbol is uniquely defined
                            callee_node = callee_candidates[0]

                    if callee_node:
                        for caller_node in caller_nodes:
                            if caller_node.id == callee_node.id and call_receiver not in (None, "", "self", "cls"):
                                continue
                            add_edge(
                                caller_node,
                                callee_node,
                                "CALLS",
                                is_verified=True,
                                evidence=call.evidence
                            )

        # Bulk save edges
        db.bulk_save_objects(edges_to_add)
        db.commit()

        # Update dependencies count on repository
        dep_count = (
            db.query(GraphEdge)
            .filter(
                GraphEdge.repository_id == repository.id,
                GraphEdge.edge_type.in_(["IMPORTS", "DEPENDS_ON"]),
            )
            .count()
        )
        repository.dependencies_count = dep_count
        db.commit()

        logger.info(
            f"Built knowledge graph for repo {repository.id}: {len(node_map)} nodes, {len(edges_to_add)} edges."
        )
        return len(node_map), len(edges_to_add)

    @classmethod
    def _process_import_symbol(
        cls,
        db: Session,
        repository: Repository,
        source_file: IndexedFile,
        source_node: GraphNode,
        sym: CodeSymbol,
        file_by_path: Dict[str, IndexedFile],
        file_by_name: Dict[str, List[IndexedFile]],
        get_or_create_node,
        add_edge,
        imported_files_by_source: Optional[Dict[str, Set[str]]] = None,
    ):
        raw = sym.signature or sym.name or ""
        # Match python / javascript import patterns
        # e.g.: "from ./auth import validateSession" or "import express from 'express'" or "const x = require('x')"
        tokens = re.findall(r"['\"]([^'\"]+)['\"]", raw)
        target_path_hint = tokens[0] if tokens else ""

        if not target_path_hint:
            # Fallback for Python simple imports like "import os, sys" or "from auth import token" or sym.name="module_name"
            words = raw.replace(",", " ").split()
            if "from" in words:
                idx = words.index("from")
                if idx + 1 < len(words):
                    target_path_hint = words[idx + 1]
            elif "import" in words:
                idx = words.index("import")
                if idx + 1 < len(words):
                    target_path_hint = words[idx + 1]
            elif words:
                target_path_hint = words[0]

        target_path_hint = target_path_hint.strip("./\\")
        if not target_path_hint:
            return

        normalized_hint = target_path_hint.replace(".", "/")
        last_segment = target_path_hint.split(".")[-1].split("/")[-1]

        # Check if matches an internal file
        matched_file: Optional[IndexedFile] = None
        # 1. Exact or suffix match in file_by_path
        for fpath, ifile in file_by_path.items():
            fpath_no_ext = fpath.rsplit(".", 1)[0]
            if (
                target_path_hint in fpath
                or normalized_hint in fpath
                or fpath_no_ext.endswith(normalized_hint)
                or fpath.endswith(target_path_hint)
            ):
                matched_file = ifile
                break

        # 2. Basename match
        if not matched_file:
            if last_segment in file_by_name:
                candidates = file_by_name[last_segment]
                matched_file = candidates[0] if candidates else None
            elif target_path_hint in file_by_name:
                candidates = file_by_name[target_path_hint]
                matched_file = candidates[0] if candidates else None

        if matched_file:
            target_key = f"repo:{repository.id}:file:{matched_file.path}"
            target_node = get_or_create_node(
                node_key=target_key,
                node_type="file",
                name=matched_file.path.split("/")[-1],
                file_path=matched_file.path,
                language=matched_file.language,
            )
            add_edge(
                source_node,
                target_node,
                "IMPORTS",
                is_verified=True,
                evidence=f"Import statement at line {sym.start_line}: {raw[:80]}",
            )
            if imported_files_by_source is not None:
                imported_files_by_source.setdefault(source_file.path, set()).add(matched_file.path)
        else:
            # External dependency package
            pkg_name = target_path_hint.split("/")[0].split(".")[0]
            if pkg_name:
                dep_key = f"repo:{repository.id}:dep:{pkg_name}"
                dep_node = get_or_create_node(
                    node_key=dep_key,
                    node_type="dependency",
                    name=pkg_name,
                    properties={"package_manager": "pip" if source_file.language == "python" else "npm"},
                )
                add_edge(
                    source_node,
                    dep_node,
                    "DEPENDS_ON",
                    is_verified=True,
                    evidence=f"External dependency import at line {sym.start_line}: {raw[:80]}",
                )

    @classmethod
    def clean_files_from_graph(
        cls,
        db: Session,
        repository_id: int,
        file_paths: Set[str],
    ) -> int:
        """
        Safely removes graph nodes and associated edges for the specified file paths.
        Guarantees no orphaned edges remain.
        """
        if not file_paths:
            return 0

        clean_paths = [p.replace("\\", "/").strip("./").strip("/") for p in file_paths if p]
        if not clean_paths:
            return 0

        nodes = (
            db.query(GraphNode)
            .filter(
                GraphNode.repository_id == repository_id,
                GraphNode.file_path.in_(clean_paths),
            )
            .all()
        )
        if not nodes:
            return 0

        node_ids = [n.id for n in nodes]

        # Clean any incident edges explicitly
        db.query(GraphEdge).filter(
            GraphEdge.repository_id == repository_id,
            (GraphEdge.source_node_id.in_(node_ids) | GraphEdge.target_node_id.in_(node_ids)),
        ).delete(synchronize_session=False)

        deleted_nodes_count = (
            db.query(GraphNode)
            .filter(GraphNode.id.in_(node_ids))
            .delete(synchronize_session=False)
        )
        db.flush()
        return deleted_nodes_count

    @classmethod
    def incremental_update_graph(
        cls,
        db: Session,
        repository: Repository,
        all_current_files: List[IndexedFile],
        symbols_by_file: Dict[int, List[CodeSymbol]],
        calls_by_file: Optional[Dict[int, List[ExtractedCall]]] = None,
        affected_file_paths: Optional[Set[str]] = None,
        deleted_file_paths: Optional[Set[str]] = None,
        revision: Optional[str] = None,
        force_full_rebuild: bool = False,
    ) -> Tuple[int, int]:
        """
        Incrementally updates the knowledge graph for changed files (added, modified, renamed, deleted).
        Preserves unchanged nodes and edges.
        Falls back to safe full graph rebuild if dependencies are uncertain or broken integrity is detected.
        Returns: (total_nodes_count, total_edges_count)
        """
        affected = set(affected_file_paths or [])
        deleted = set(deleted_file_paths or [])
        rev = revision or repository.current_revision or "HEAD"

        existing_nodes_count = db.query(GraphNode).filter(GraphNode.repository_id == repository.id).count()

        # Fallback conditions:
        # 1. Explicit full rebuild requested
        # 2. No existing graph exists for this repository
        # 3. High change volume (>40% of all files affected)
        # 4. Total current files is small (<= 5 files), where rebuild is instantaneous and eliminates edge cases
        should_fallback = (
            force_full_rebuild
            or existing_nodes_count == 0
            or len(all_current_files) <= 5
            or (len(all_current_files) > 0 and len(affected) / len(all_current_files) > 0.40)
        )

        if should_fallback:
            logger.info(
                f"Using safe full graph rebuild for repo {repository.id} "
                f"(force={force_full_rebuild}, existing_nodes={existing_nodes_count}, affected={len(affected)}/{len(all_current_files)})"
            )
            return cls.build_graph_for_repository(
                db=db,
                repository=repository,
                files=all_current_files,
                symbols_by_file=symbols_by_file,
                calls_by_file=calls_by_file,
                revision=rev,
            )

        try:
            # 1. Clean obsolete nodes and edges for deleted and modified files
            paths_to_clean = affected | deleted
            cls.clean_files_from_graph(db, repository.id, paths_to_clean)

            # 2. Ensure root repository node exists
            repo_node_key = f"repo:{repository.id}"
            repo_node = (
                db.query(GraphNode)
                .filter(GraphNode.repository_id == repository.id, GraphNode.node_key == repo_node_key)
                .first()
            )
            if not repo_node:
                repo_node = GraphNode(
                    repository_id=repository.id,
                    node_key=repo_node_key,
                    node_type="repository",
                    name=repository.name,
                    properties=json.dumps({"full_name": repository.full_name, "default_branch": repository.default_branch}),
                )
                db.add(repo_node)
                db.flush()

            # 3. Build lookup maps from current files and existing DB graph nodes
            file_by_path: Dict[str, IndexedFile] = {f.path: f for f in all_current_files}
            file_by_name: Dict[str, List[IndexedFile]] = {}
            for f in all_current_files:
                bname = f.path.split("/")[-1].split(".")[0]
                file_by_name.setdefault(bname, []).append(f)

            # Load all current nodes into node_map
            all_db_nodes = db.query(GraphNode).filter(GraphNode.repository_id == repository.id).all()
            node_map: Dict[str, GraphNode] = {n.node_key: n for n in all_db_nodes}
            symbol_nodes_by_name: Dict[str, List[GraphNode]] = {}
            for n in all_db_nodes:
                if n.node_type in ("function", "method", "class"):
                    symbol_nodes_by_name.setdefault(n.name, []).append(n)
                    if n.symbol_name and n.symbol_name != n.name:
                        symbol_nodes_by_name.setdefault(n.symbol_name, []).append(n)

            # Load existing edges and imports
            all_db_edges = db.query(GraphEdge).filter(GraphEdge.repository_id == repository.id).all()
            created_edges_set: Set[Tuple[int, int, str]] = {
                (e.source_node_id, e.target_node_id, e.edge_type) for e in all_db_edges
            }
            edges_to_add: List[GraphEdge] = []

            id_to_file_path = {n.id: n.file_path for n in all_db_nodes if n.file_path}
            imported_files_by_source: Dict[str, Set[str]] = {}
            for e in all_db_edges:
                if e.edge_type == "IMPORTS":
                    src_fp = id_to_file_path.get(e.source_node_id)
                    tgt_fp = id_to_file_path.get(e.target_node_id)
                    if src_fp and tgt_fp:
                        imported_files_by_source.setdefault(src_fp, set()).add(tgt_fp)

            # Helper to get or create node
            def get_or_create_node(
                node_key: str,
                node_type: str,
                name: str,
                file_path: Optional[str] = None,
                symbol_name: Optional[str] = None,
                signature: Optional[str] = None,
                start_line: Optional[int] = None,
                end_line: Optional[int] = None,
                language: Optional[str] = None,
                properties: Optional[dict] = None,
            ) -> GraphNode:
                clean_node_key = node_key.replace("\x00", "")[:500]
                if clean_node_key in node_map:
                    return node_map[clean_node_key]

                clean_name = name.replace("\x00", "")[:255]
                clean_file_path = file_path.replace("\x00", "")[:500] if file_path else None
                clean_symbol_name = symbol_name.replace("\x00", "")[:255] if symbol_name else None
                clean_signature = signature.replace("\x00", "") if signature else None
                clean_props = json.dumps(properties or {}).replace("\x00", "")

                node = GraphNode(
                    repository_id=repository.id,
                    node_key=clean_node_key,
                    node_type=node_type[:50],
                    name=clean_name,
                    file_path=clean_file_path,
                    symbol_name=clean_symbol_name,
                    signature=clean_signature,
                    start_line=start_line,
                    end_line=end_line,
                    language=language[:50] if language else None,
                    source_revision=rev[:100] if rev else None,
                    properties=clean_props,
                )
                db.add(node)
                db.flush()
                node_map[clean_node_key] = node
                return node

            # Helper to add edge with deduplication
            def add_edge(
                source_node: GraphNode,
                target_node: GraphNode,
                edge_type: str,
                is_verified: bool = True,
                evidence: Optional[str] = None,
            ):
                if source_node.id == target_node.id and edge_type != "CALLS":
                    return
                edge_tuple = (source_node.id, target_node.id, edge_type)
                if edge_tuple in created_edges_set:
                    return

                created_edges_set.add(edge_tuple)
                clean_evidence = evidence.replace("\x00", "") if evidence else None
                edge = GraphEdge(
                    repository_id=repository.id,
                    source_node_id=source_node.id,
                    target_node_id=target_node.id,
                    edge_type=edge_type,
                    is_verified=is_verified,
                    source_revision=rev,
                    evidence=clean_evidence,
                )
                edges_to_add.append(edge)

            # 4. Process only affected files (added, modified, renamed)
            files_to_process = [f for f in all_current_files if f.path in affected]

            for indexed_file in files_to_process:
                file_node_key = f"repo:{repository.id}:file:{indexed_file.path}"
                file_name = indexed_file.path.split("/")[-1]
                file_node = get_or_create_node(
                    node_key=file_node_key,
                    node_type="file",
                    name=file_name,
                    file_path=indexed_file.path,
                    language=indexed_file.language,
                    properties={"lines_count": indexed_file.lines_count, "size_bytes": indexed_file.size_bytes},
                )
                add_edge(repo_node, file_node, "CONTAINS", is_verified=True, evidence=f"File in repository {repository.name}")

                file_symbols = symbols_by_file.get(indexed_file.id, [])
                classes_in_file: Dict[str, GraphNode] = {}

                # Classes pass
                for sym in file_symbols:
                    if sym.kind == "class":
                        sym_node_key = f"repo:{repository.id}:symbol:{indexed_file.path}:{sym.name}"
                        sym_node = get_or_create_node(
                            node_key=sym_node_key,
                            node_type="class",
                            name=sym.name,
                            file_path=indexed_file.path,
                            symbol_name=sym.name,
                            signature=sym.signature,
                            start_line=sym.start_line,
                            end_line=sym.end_line,
                            language=indexed_file.language,
                        )
                        add_edge(file_node, sym_node, "CONTAINS", is_verified=True, evidence=f"Class defined in {indexed_file.path}:{sym.start_line}")
                        classes_in_file[sym.name] = sym_node
                        symbol_nodes_by_name.setdefault(sym.name, []).append(sym_node)

                # Functions, methods, imports pass
                for sym in file_symbols:
                    if sym.kind in ("function", "method"):
                        sym_node_key = f"repo:{repository.id}:symbol:{indexed_file.path}:{sym.name}"
                        parent_class = None
                        simple_name = sym.name
                        if "." in sym.name:
                            parts = sym.name.split(".", 1)
                            parent_class = parts[0]
                            simple_name = parts[1]

                        sym_node = get_or_create_node(
                            node_key=sym_node_key,
                            node_type="method" if parent_class else "function",
                            name=simple_name,
                            file_path=indexed_file.path,
                            symbol_name=sym.name,
                            signature=sym.signature,
                            start_line=sym.start_line,
                            end_line=sym.end_line,
                            language=indexed_file.language,
                        )
                        symbol_nodes_by_name.setdefault(simple_name, []).append(sym_node)
                        symbol_nodes_by_name.setdefault(sym.name, []).append(sym_node)

                        if parent_class and parent_class in classes_in_file:
                            add_edge(classes_in_file[parent_class], sym_node, "DEFINES", is_verified=True, evidence=f"Method in {parent_class} at line {sym.start_line}")
                        else:
                            add_edge(file_node, sym_node, "CONTAINS", is_verified=True, evidence=f"Function in {indexed_file.path} at line {sym.start_line}")

                    elif sym.kind == "import":
                        cls._process_import_symbol(
                            db, repository, indexed_file, file_node, sym,
                            file_by_path, file_by_name, get_or_create_node, add_edge,
                            imported_files_by_source
                        )

            # 5. Verified Static Calls for affected files
            file_by_id: Dict[int, IndexedFile] = {f.id: f for f in all_current_files}
            if calls_by_file:
                for file_id, file_calls in calls_by_file.items():
                    indexed_file = file_by_id.get(file_id)
                    if not indexed_file or indexed_file.path not in affected:
                        continue
                    for call in file_calls:
                        file_callers = [
                            n for n in symbol_nodes_by_name.get(call.caller_name, [])
                            if n.file_path == indexed_file.path
                        ]
                        if not file_callers:
                            continue
                        enclosing_callers = [
                            n for n in file_callers
                            if n.start_line is not None and n.end_line is not None and n.start_line <= call.line_number <= n.end_line
                        ]
                        caller_nodes = enclosing_callers if enclosing_callers else file_callers

                        callee_candidates = symbol_nodes_by_name.get(call.callee_name, [])
                        if not callee_candidates:
                            continue

                        local_callees = [c for c in callee_candidates if c.file_path == indexed_file.path]
                        callee_node = None
                        call_receiver = getattr(call, "receiver", None)

                        if call_receiver in ("self", "cls"):
                            callee_node = local_callees[0] if local_callees else None
                        elif call_receiver and call_receiver not in ("self", "cls"):
                            # Explicit receiver like DashboardService.get_dashboard or service.get_dashboard
                            imported_paths = imported_files_by_source.get(indexed_file.path, set())
                            receiver_str = str(call_receiver).lower().replace("_", "")
                            # 1. Match imported files where receiver matches the path
                            imported_callees = [c for c in callee_candidates if c.file_path in imported_paths]
                            matching_receiver = [c for c in imported_callees if receiver_str in c.file_path.lower().replace("_", "")]
                            if matching_receiver:
                                callee_node = matching_receiver[0]
                            elif imported_callees:
                                callee_node = imported_callees[0]
                            else:
                                # 2. Match any callee candidate where receiver matches the path
                                matching_all = [c for c in callee_candidates if receiver_str in c.file_path.lower().replace("_", "")]
                                if matching_all:
                                    callee_node = matching_all[0]
                                elif len(callee_candidates) == 1:
                                    callee_node = callee_candidates[0]
                        elif local_callees:
                            callee_node = local_callees[0]
                        else:
                            # Cross-file call with no receiver: require verified import of target file or unambiguous single repo candidate
                            imported_paths = imported_files_by_source.get(indexed_file.path, set())
                            if imported_paths:
                                imported_callees = [c for c in callee_candidates if c.file_path in imported_paths]
                                if imported_callees:
                                    callee_node = imported_callees[0]
                            elif len(callee_candidates) == 1:
                                # File has no parsed imports (e.g. unit test or standalone script) and callee symbol is uniquely defined
                                callee_node = callee_candidates[0]

                        if callee_node:
                            for caller_node in caller_nodes:
                                if caller_node.id == callee_node.id and call_receiver not in (None, "", "self", "cls"):
                                    continue
                                add_edge(
                                    caller_node,
                                    callee_node,
                                    "CALLS",
                                    is_verified=True,
                                    evidence=call.evidence
                                )

            if edges_to_add:
                db.bulk_save_objects(edges_to_add)
                db.flush()

            # 6. Integrity check: ensure no orphaned edges exist
            orphaned = (
                db.query(GraphEdge)
                .filter(
                    GraphEdge.repository_id == repository.id,
                    ~GraphEdge.source_node_id.in_(db.query(GraphNode.id).filter(GraphNode.repository_id == repository.id)),
                )
                .count()
            )
            if orphaned > 0:
                logger.warning(f"Detected {orphaned} orphaned edges after incremental update; falling back to clean rebuild.")
                return cls.build_graph_for_repository(
                    db=db,
                    repository=repository,
                    files=all_current_files,
                    symbols_by_file=symbols_by_file,
                    calls_by_file=calls_by_file,
                    revision=rev,
                )

            # Update repository dependency count
            dep_count = (
                db.query(GraphEdge)
                .filter(
                    GraphEdge.repository_id == repository.id,
                    GraphEdge.edge_type.in_(["IMPORTS", "DEPENDS_ON"]),
                )
                .count()
            )
            repository.dependencies_count = dep_count
            db.commit()

            total_nodes = db.query(GraphNode).filter(GraphNode.repository_id == repository.id).count()
            total_edges = db.query(GraphEdge).filter(GraphEdge.repository_id == repository.id).count()
            logger.info(f"Incremental graph update completed: {total_nodes} nodes, {total_edges} edges.")
            return total_nodes, total_edges

        except Exception as inc_err:
            logger.warning(f"Incremental graph update failed: {inc_err}. Falling back to safe full graph rebuild.", exc_info=True)
            db.rollback()
            return cls.build_graph_for_repository(
                db=db,
                repository=repository,
                files=all_current_files,
                symbols_by_file=symbols_by_file,
                calls_by_file=calls_by_file,
                revision=rev,
            )

