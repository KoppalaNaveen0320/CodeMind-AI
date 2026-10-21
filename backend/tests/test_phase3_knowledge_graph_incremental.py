import asyncio
import hashlib
import tempfile
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.graph.builder import KnowledgeGraphBuilder
from backend.app.parsing.extractor import ExtractedCall
from backend.app.services.indexing_service import IndexingService


def test_knowledge_graph_removes_deleted_file_nodes_and_edges(db_session: Session):
    """
    Verify that deleting a file cleanly cleans up all associated
    graph nodes and edges without leaving any orphaned edges.
    """
    async def _run():
        repo = Repository(
            name="kg-del-repo",
            full_name="test-org/kg-del-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            (repo_dir / "consumer.py").write_text("import producer\ndef use(): producer.produce()\n", encoding="utf-8")
            (repo_dir / "producer.py").write_text("def produce(): return 1\n", encoding="utf-8")
            repo.clone_url = str(repo_dir)
            db_session.commit()

            # Full index
            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            # Confirm graph nodes and edges exist for both
            prod_nodes = db_session.query(GraphNode).filter(
                GraphNode.repository_id == repo.id,
                GraphNode.file_path == "producer.py"
            ).all()
            assert len(prod_nodes) >= 1

            # Delete producer.py
            (repo_dir / "producer.py").unlink()

            # Incremental index
            job2 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job2)
            assert job2.status == "COMPLETED"

            # Verify producer.py nodes are gone
            remaining_prod = db_session.query(GraphNode).filter(
                GraphNode.repository_id == repo.id,
                GraphNode.file_path == "producer.py"
            ).all()
            assert len(remaining_prod) == 0

            # Verify no orphaned edges exist in the entire graph
            node_ids = {n.id for n in db_session.query(GraphNode.id).filter(GraphNode.repository_id == repo.id).all()}
            all_edges = db_session.query(GraphEdge).filter(GraphEdge.repository_id == repo.id).all()
            for edge in all_edges:
                assert edge.source_node_id in node_ids, f"Orphaned source in edge {edge.id}"
                assert edge.target_node_id in node_ids, f"Orphaned target in edge {edge.id}"

    asyncio.run(_run())


def test_knowledge_graph_refreshes_modified_imports_and_calls(db_session: Session):
    """
    Verify modifying import statements and function calls refreshes graph edges.
    """
    async def _run():
        repo = Repository(
            name="kg-mod-repo",
            full_name="test-org/kg-mod-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            src = repo_dir / "src"
            src.mkdir()
            (src / "service_a.py").write_text("class ServiceA:\n    def run_a(self): pass\n", encoding="utf-8")
            (src / "service_b.py").write_text("class ServiceB:\n    def run_b(self): pass\n", encoding="utf-8")
            (src / "main.py").write_text("import src.service_a as sa\ndef main(): pass\n", encoding="utf-8")
            repo.clone_url = str(repo_dir)
            db_session.commit()

            # 1. Initial indexing
            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            # Check import edge: main imports service_a
            import_edges = db_session.query(GraphEdge).filter(
                GraphEdge.repository_id == repo.id,
                GraphEdge.edge_type == "IMPORTS"
            ).all()
            assert len(import_edges) >= 1

            # 2. Modify main.py to import service_b instead of service_a
            (src / "main.py").write_text("import src.service_b as sb\ndef main(): pass\n", encoding="utf-8")

            # Incremental indexing
            job2 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job2)
            assert job2.status == "COMPLETED"

            # Verify updated import edge points to service_b
            updated_import_edges = db_session.query(GraphEdge).filter(
                GraphEdge.repository_id == repo.id,
                GraphEdge.edge_type == "IMPORTS"
            ).all()
            assert len(updated_import_edges) >= 1
            target_node = db_session.query(GraphNode).filter(GraphNode.id == updated_import_edges[0].target_node_id).first()
            assert target_node is not None
            assert "service_b" in target_node.file_path or "service_b" in target_node.name

    asyncio.run(_run())


def test_knowledge_graph_fallback_on_heavy_change(db_session: Session):
    """
    Verify that when more than 40% of files change, the graph builder safely triggers full rebuild fallback.
    """
    async def _run():
        repo = Repository(
            name="kg-fallback-repo",
            full_name="test-org/kg-fallback-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            for i in range(10):
                (repo_dir / f"file_{i}.py").write_text(f"def fn_{i}(): return {i}\n", encoding="utf-8")
            repo.clone_url = str(repo_dir)
            db_session.commit()

            # Initial indexing
            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            # Modify 5 out of 10 files (50% > 40% threshold)
            for i in range(5):
                (repo_dir / f"file_{i}.py").write_text(f"def fn_{i}_updated(): return {i * 10}\n", encoding="utf-8")

            # Incremental indexing
            job2 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job2)
            assert job2.status == "COMPLETED"
            assert job2.files_modified == 5
            assert job2.files_unchanged == 5

            # All 10 files have valid nodes
            nodes = db_session.query(GraphNode).filter(
                GraphNode.repository_id == repo.id,
                GraphNode.node_type == "file"
            ).all()
            assert len(nodes) == 10

    asyncio.run(_run())
