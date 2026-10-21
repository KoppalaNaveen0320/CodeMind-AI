import asyncio
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.services.indexing_service import IndexingService
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine


def _setup_v1_repo(root: Path):
    """Sets up state V1 of the test repository."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)

    (src / "math_ops.py").write_text(
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "    def multiply(self, a, b):\n"
        "        return a * b\n"
        "\n"
        "def power(base, exp):\n"
        "    return base ** exp\n",
        encoding="utf-8",
    )

    (src / "formatter.py").write_text(
        "def format_result(val: int) -> str:\n"
        "    return f'Result: {val}'\n",
        encoding="utf-8",
    )

    (src / "to_delete.py").write_text(
        "def obsolete_helper():\n"
        "    return 'deprecated'\n",
        encoding="utf-8",
    )

    (src / "to_rename.py").write_text(
        "def legacy_function():\n"
        "    return 42\n",
        encoding="utf-8",
    )


def _evolve_to_v2_repo(root: Path):
    """
    Evolves repository from state V1 to state V2:
    - Modifies math_ops.py
    - Adds statistics.py (with import of math_ops)
    - Deletes to_delete.py
    - Renames to_rename.py -> renamed_utils.py
    - Leaves formatter.py untouched
    """
    src = root / "src"

    # 1. Modify math_ops.py (updated signature, added subtract method)
    (src / "math_ops.py").write_text(
        "class Calculator:\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n"
        "    def multiply(self, a: int, b: int) -> int:\n"
        "        return a * b\n"
        "    def subtract(self, a: int, b: int) -> int:\n"
        "        return a - b\n"
        "\n"
        "def power(base: int, exp: int) -> int:\n"
        "    return int(base ** exp)\n",
        encoding="utf-8",
    )

    # 2. Add statistics.py
    (src / "statistics.py").write_text(
        "from src.math_ops import Calculator\n"
        "\n"
        "class StatsEngine:\n"
        "    def mean(self, items):\n"
        "        calc = Calculator()\n"
        "        total = sum(items)\n"
        "        return total / len(items)\n"
        "\n"
        "def median(items):\n"
        "    sorted_items = sorted(items)\n"
        "    return sorted_items[len(sorted_items) // 2]\n",
        encoding="utf-8",
    )

    # 3. Delete to_delete.py
    (src / "to_delete.py").unlink()

    # 4. Rename to_rename.py -> renamed_utils.py
    (src / "to_rename.py").rename(src / "renamed_utils.py")


def test_incremental_versus_full_index_parity(db_session: Session):
    """
    Mandatory Parity Test:
    Builds an incremental index through genuine repository evolution
    (V1 -> V2 via addition, modification, rename, deletion).
    Separately builds a clean full index of the final V2 snapshot.
    Compares the resulting logical data:
    1. Indexed file paths and hashes.
    2. Symbols and symbol metadata.
    3. Chunks and source locations.
    4. Embeddings presence and dimensions.
    5. Knowledge graph nodes and edges.
    6. Retrieval results and citation paths.
    """
    async def _run():
        # 1. Create two repositories
        repo_inc = Repository(
            name="repo-incremental",
            full_name="test-org/repo-incremental",
            provider="folder",
            status="ready",
        )
        repo_full = Repository(
            name="repo-full",
            full_name="test-org/repo-full",
            provider="folder",
            status="ready",
        )
        db_session.add_all([repo_inc, repo_full])
        db_session.commit()
        db_session.refresh(repo_inc)
        db_session.refresh(repo_full)

        with tempfile.TemporaryDirectory() as tmp_inc, tempfile.TemporaryDirectory() as tmp_full:
            path_inc = Path(tmp_inc)
            path_full = Path(tmp_full)

            # Setup V1 in path_inc
            _setup_v1_repo(path_inc)
            repo_inc.clone_url = str(path_inc)
            db_session.commit()

            # --- Step A: Initial full index of repo_inc at V1 ---
            job_inc_v1 = IndexingService.create_indexing_job(db_session, repo_inc)
            await IndexingService.run_indexing_pipeline(job_inc_v1.id, repo_inc.id, "main", db_session=db_session)
            db_session.refresh(job_inc_v1)
            assert job_inc_v1.status == "COMPLETED"

            # --- Step B: Evolve path_inc from V1 to V2 ---
            _evolve_to_v2_repo(path_inc)

            # Setup path_full directly with identical V2 files
            _setup_v1_repo(path_full)
            _evolve_to_v2_repo(path_full)
            repo_full.clone_url = str(path_full)
            db_session.commit()

            # --- Step C: Run Incremental Index on repo_inc ---
            job_inc_v2 = IndexingService.create_indexing_job(db_session, repo_inc)
            await IndexingService.run_indexing_pipeline(job_inc_v2.id, repo_inc.id, "main", db_session=db_session)
            db_session.refresh(job_inc_v2)
            assert job_inc_v2.status == "COMPLETED"

            # Verify change detection counts
            assert job_inc_v2.files_modified == 1  # math_ops.py
            assert job_inc_v2.files_unchanged == 1  # formatter.py
            # 2 added/renamed (statistics.py + renamed_utils.py)
            assert job_inc_v2.files_added in (1, 2)
            # deleted (to_delete.py + old to_rename.py)
            assert job_inc_v2.files_deleted in (1, 2)

            # --- Step D: Run Clean Full Index on repo_full ---
            job_full = IndexingService.create_indexing_job(db_session, repo_full)
            await IndexingService.run_indexing_pipeline(job_full.id, repo_full.id, "main", db_session=db_session)
            db_session.refresh(job_full)
            assert job_full.status == "COMPLETED"

            # ========================================================
            # PARITY ASSERTIONS: Compare logical data between inc and full
            # ========================================================

            # 1. Indexed Files Parity
            files_inc = db_session.query(IndexedFile).filter(IndexedFile.repository_id == repo_inc.id).all()
            files_full = db_session.query(IndexedFile).filter(IndexedFile.repository_id == repo_full.id).all()

            paths_inc = sorted([f.path for f in files_inc])
            paths_full = sorted([f.path for f in files_full])
            assert paths_inc == paths_full, f"Files mismatch: {paths_inc} vs {paths_full}"
            assert "src/to_delete.py" not in paths_inc
            assert "src/to_rename.py" not in paths_inc
            assert "src/renamed_utils.py" in paths_inc
            assert "src/statistics.py" in paths_inc

            hash_map_inc = {f.path: f.content_hash for f in files_inc}
            hash_map_full = {f.path: f.content_hash for f in files_full}
            assert hash_map_inc == hash_map_full, "Content hashes must match 1:1"

            # 2. Symbols Parity
            syms_inc = db_session.query(CodeSymbol).filter(CodeSymbol.repository_id == repo_inc.id).all()
            syms_full = db_session.query(CodeSymbol).filter(CodeSymbol.repository_id == repo_full.id).all()

            # Canonical representation: (relative_file_path, symbol_name, kind, start_line, end_line)
            file_path_by_id_inc = {f.id: f.path for f in files_inc}
            file_path_by_id_full = {f.id: f.path for f in files_full}

            sym_canon_inc = sorted([
                (file_path_by_id_inc.get(s.file_id), s.name, s.kind, s.start_line, s.end_line)
                for s in syms_inc
            ])
            sym_canon_full = sorted([
                (file_path_by_id_full.get(s.file_id), s.name, s.kind, s.start_line, s.end_line)
                for s in syms_full
            ])
            assert sym_canon_inc == sym_canon_full, f"Symbols mismatch:\nInc: {sym_canon_inc}\nFull: {sym_canon_full}"

            # 3. Chunks Parity
            chunks_inc = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo_inc.id).all()
            chunks_full = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo_full.id).all()

            chunk_canon_inc = sorted([
                (c.file_path, c.chunk_index, c.code_symbol, c.start_line, c.end_line, c.chunk_text.strip(), c.content_hash)
                for c in chunks_inc
            ])
            chunk_canon_full = sorted([
                (c.file_path, c.chunk_index, c.code_symbol, c.start_line, c.end_line, c.chunk_text.strip(), c.content_hash)
                for c in chunks_full
            ])
            assert chunk_canon_inc == chunk_canon_full, f"Chunks mismatch:\nInc: {chunk_canon_inc}\nFull: {chunk_canon_full}"

            # 4. Embeddings Presence and Dimensions
            assert len(chunks_inc) > 0
            for c in chunks_inc:
                assert c.embedding is not None, f"Chunk {c.id} in repo_inc missing embedding"
                assert len(c.embedding) == 768, f"Unexpected embedding dimension: {len(c.embedding)}"
            for c in chunks_full:
                assert c.embedding is not None, f"Chunk {c.id} in repo_full missing embedding"
                assert len(c.embedding) == 768

            # 5. Knowledge Graph Nodes Parity
            nodes_inc = db_session.query(GraphNode).filter(GraphNode.repository_id == repo_inc.id).all()
            nodes_full = db_session.query(GraphNode).filter(GraphNode.repository_id == repo_full.id).all()

            node_canon_inc = sorted([
                (n.node_type, n.name if n.node_type != "repository" else "<REPO_ROOT>", n.file_path)
                for n in nodes_inc
            ])
            node_canon_full = sorted([
                (n.node_type, n.name if n.node_type != "repository" else "<REPO_ROOT>", n.file_path)
                for n in nodes_full
            ])
            assert node_canon_inc == node_canon_full, f"Graph nodes mismatch:\nInc: {node_canon_inc}\nFull: {node_canon_full}"

            # 6. Knowledge Graph Edges Parity
            edges_inc = db_session.query(GraphEdge).filter(GraphEdge.repository_id == repo_inc.id).all()
            edges_full = db_session.query(GraphEdge).filter(GraphEdge.repository_id == repo_full.id).all()

            node_map_inc = {
                n.id: (n.node_type, n.name if n.node_type != "repository" else "<REPO_ROOT>", n.file_path)
                for n in nodes_inc
            }
            node_map_full = {
                n.id: (n.node_type, n.name if n.node_type != "repository" else "<REPO_ROOT>", n.file_path)
                for n in nodes_full
            }

            edge_canon_inc = sorted([
                (node_map_inc[e.source_node_id], e.edge_type, node_map_inc[e.target_node_id])
                for e in edges_inc
                if e.source_node_id in node_map_inc and e.target_node_id in node_map_inc
            ])
            edge_canon_full = sorted([
                (node_map_full[e.source_node_id], e.edge_type, node_map_full[e.target_node_id])
                for e in edges_full
                if e.source_node_id in node_map_full and e.target_node_id in node_map_full
            ])
            assert edge_canon_inc == edge_canon_full, f"Graph edges mismatch:\nInc: {edge_canon_inc}\nFull: {edge_canon_full}"

            # Ensure zero orphaned edges in both
            for e in edges_inc:
                assert e.source_node_id in node_map_inc
                assert e.target_node_id in node_map_inc
            for e in edges_full:
                assert e.source_node_id in node_map_full
                assert e.target_node_id in node_map_full

            # 7. Search & Retrieval Parity
            res_inc = await HybridRetrievalEngine.retrieve(db=db_session, repository_id=repo_inc.id, query="subtract numbers in Calculator", top_k=5)
            res_full = await HybridRetrievalEngine.retrieve(db=db_session, repository_id=repo_full.id, query="subtract numbers in Calculator", top_k=5)

            assert len(res_inc) > 0
            assert len(res_full) > 0
            # Both should cite src/math_ops.py as top match
            assert res_inc[0].file_path == "src/math_ops.py"
            assert res_full[0].file_path == "src/math_ops.py"
            assert "subtract" in res_inc[0].chunk_text
            assert "subtract" in res_full[0].chunk_text

            # Deleted function should NOT be retrieved in either
            del_res_inc = await HybridRetrievalEngine.retrieve(db=db_session, repository_id=repo_inc.id, query="obsolete_helper deprecated", top_k=5)
            for hit in del_res_inc:
                assert "obsolete_helper" not in hit.chunk_text
                assert hit.file_path != "src/to_delete.py"

    asyncio.run(_run())
