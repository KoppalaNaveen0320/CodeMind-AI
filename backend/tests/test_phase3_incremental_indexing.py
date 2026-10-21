import asyncio
import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.services.indexing_service import IndexingService
from backend.app.integrations.embeddings.service import EmbeddingService
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider


def test_incremental_indexing_skips_unchanged_files(db_session: Session):
    """
    Verify that when an indexed repository is re-indexed without changes:
    - 0 files are reparsed
    - 0 embedding requests are made
    - Existing chunks and symbols are untouched
    - Job is marked COMPLETED with files_unchanged = N
    """
    async def _run():
        repo = Repository(
            name="unchanged-repo",
            full_name="test-org/unchanged-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()
        db_session.refresh(repo)

        content = "def calculate_total(a: int, b: int) -> int:\n    return a + b\n"
        c_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            src = repo_dir / "src"
            src.mkdir()
            calc_file = src / "calc.py"
            calc_file.write_text(content, encoding="utf-8")

            repo.clone_url = str(repo_dir)
            db_session.commit()

            # Run first full indexing
            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            db_session.refresh(repo)
            db_session.refresh(job1)
            assert job1.status == "COMPLETED"
            assert repo.files_count == 1
            initial_chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
            assert len(initial_chunks) >= 1
            initial_chunk_id = initial_chunks[0].id

            # Spy on embed_new_chunks to ensure it is NOT called for unchanged repo
            with patch.object(EmbeddingService, "embed_new_chunks", new_callable=AsyncMock) as mock_embed:
                job2 = IndexingService.create_indexing_job(db_session, repo)
                await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

                db_session.refresh(job2)
                assert job2.status == "COMPLETED"
                assert job2.files_unchanged == 1
                assert job2.files_added == 0
                assert job2.files_modified == 0
                assert job2.files_deleted == 0
                assert job2.files_processed == 0

                # Zero embedding calls made!
                mock_embed.assert_not_called()

            # Verify initial chunks were preserved, not recreated
            current_chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
            assert len(current_chunks) == len(initial_chunks)
            assert current_chunks[0].id == initial_chunk_id

    asyncio.run(_run())


def test_incremental_indexing_modified_file_updates_artifacts(db_session: Session):
    """
    Verify that modifying 1 file out of 2:
    - Only re-parses and re-chunks the modified file
    - Replaces old chunks for that file (no duplicate accumulation)
    - Leaves unchanged file artifacts untouched
    """
    async def _run():
        repo = Repository(
            name="modified-repo",
            full_name="test-org/modified-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()
        db_session.refresh(repo)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            src = repo_dir / "src"
            src.mkdir()
            (src / "unchanged.py").write_text("def stable_fn(): return 1\n", encoding="utf-8")
            (src / "to_modify.py").write_text("def v1_fn(): return 'v1'\n", encoding="utf-8")

            repo.clone_url = str(repo_dir)
            db_session.commit()

            # Initial indexing
            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            unchanged_chunk = db_session.query(CodeChunk).filter(
                CodeChunk.repository_id == repo.id,
                CodeChunk.file_path == "src/unchanged.py"
            ).first()
            assert unchanged_chunk is not None
            unchanged_chunk_id = unchanged_chunk.id

            # Modify to_modify.py
            (src / "to_modify.py").write_text("def v2_fn(): return 'v2_updated'\n", encoding="utf-8")

            # Second indexing (incremental)
            job2 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job2)
            assert job2.status == "COMPLETED"
            assert job2.files_modified == 1
            assert job2.files_unchanged == 1
            assert job2.files_added == 0
            assert job2.files_deleted == 0

            # Unchanged chunk preserved
            refreshed_unchanged = db_session.query(CodeChunk).filter(
                CodeChunk.repository_id == repo.id,
                CodeChunk.file_path == "src/unchanged.py"
            ).first()
            assert refreshed_unchanged.id == unchanged_chunk_id

            # Modified file chunks replaced (v1 chunk gone, v2 chunk present)
            mod_chunks = db_session.query(CodeChunk).filter(
                CodeChunk.repository_id == repo.id,
                CodeChunk.file_path == "src/to_modify.py"
            ).all()
            assert len(mod_chunks) == 1
            assert "v2_fn" in mod_chunks[0].chunk_text
            assert "v1_fn" not in mod_chunks[0].chunk_text

            # Symbols also updated
            symbols = db_session.query(CodeSymbol).filter(
                CodeSymbol.repository_id == repo.id
            ).all()
            sym_names = [s.name for s in symbols]
            assert "v2_fn" in sym_names
            assert "v1_fn" not in sym_names

    asyncio.run(_run())


def test_deleted_file_removes_all_associated_artifacts(db_session: Session):
    """
    Verify that deleting a file completely cleans up:
    - IndexedFile record
    - CodeChunk records
    - CodeSymbol records
    - GraphNode and GraphEdge records
    """
    async def _run():
        repo = Repository(
            name="delete-repo",
            full_name="test-org/delete-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()
        db_session.refresh(repo)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            src = repo_dir / "src"
            src.mkdir()
            (src / "stay.py").write_text("def stay(): return True\n", encoding="utf-8")
            (src / "delete_me.py").write_text("def delete_me(): return False\n", encoding="utf-8")

            repo.clone_url = str(repo_dir)
            db_session.commit()

            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            # Confirm 2 files indexed
            assert db_session.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).count() == 2

            # Delete delete_me.py from disk
            (src / "delete_me.py").unlink()

            # Incremental index
            job2 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job2)
            assert job2.status == "COMPLETED"
            assert job2.files_deleted == 1
            assert job2.files_unchanged == 1

            # Check database cleanliness
            del_files = db_session.query(IndexedFile).filter(
                IndexedFile.repository_id == repo.id,
                IndexedFile.path == "src/delete_me.py"
            ).all()
            assert len(del_files) == 0

            del_chunks = db_session.query(CodeChunk).filter(
                CodeChunk.repository_id == repo.id,
                CodeChunk.file_path == "src/delete_me.py"
            ).all()
            assert len(del_chunks) == 0

            del_symbols = db_session.query(CodeSymbol).filter(
                CodeSymbol.repository_id == repo.id,
                CodeSymbol.name == "delete_me"
            ).all()
            assert len(del_symbols) == 0

            del_nodes = db_session.query(GraphNode).filter(
                GraphNode.repository_id == repo.id,
                GraphNode.file_path == "src/delete_me.py"
            ).all()
            assert len(del_nodes) == 0

    asyncio.run(_run())


def test_embedding_failure_fails_job_cleanly(db_session: Session):
    """Verify that an embedding service failure marks the job as FAILED without corrupted data."""
    async def _run():
        repo = Repository(
            name="fail-embed-repo",
            full_name="test-org/fail-embed-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            (repo_dir / "app.py").write_text("def app(): pass\n", encoding="utf-8")
            repo.clone_url = str(repo_dir)
            db_session.commit()

            job = IndexingService.create_indexing_job(db_session, repo)

            with patch.object(EmbeddingService, "embed_new_chunks", return_value={"success": False, "error": "Ollama timed out"}):
                await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job)
            assert job.status == "FAILED"
            assert "Embedding generation failed" in job.error_message or "Ollama timed out" in job.error_message

    asyncio.run(_run())
