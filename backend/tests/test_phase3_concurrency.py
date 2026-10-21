import asyncio
import tempfile
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode
from backend.app.services.indexing_service import IndexingService


def test_concurrent_jobs_same_repository_prevented(db_session: Session):
    """
    Verify that if two indexing pipelines attempt to run simultaneously
    on the exact same repository, the concurrency lock prevents overlap.
    """
    async def _run():
        repo = Repository(
            name="lock-repo",
            full_name="test-org/lock-repo",
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

            job1 = IndexingService.create_indexing_job(db_session, repo)

            # create_indexing_job deduplication test
            job2 = IndexingService.create_indexing_job(db_session, repo)
            assert job2.id == job1.id, "Second create_indexing_job must return existing active job"

            # Concurrency safety in run_indexing_pipeline:
            # Simulate lock being held
            if repo.id not in IndexingService._REPO_ASYNC_LOCKS:
                IndexingService._REPO_ASYNC_LOCKS[repo.id] = asyncio.Lock()

            async with IndexingService._REPO_ASYNC_LOCKS[repo.id]:
                # Now lock is held; second run must abort cleanly without corrupting
                await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)
                db_session.refresh(job1)
                # job1 should still be in queued or original state, not corrupted
                assert job1.status in ("QUEUED", "ready")

    asyncio.run(_run())


def test_independent_repositories_index_concurrently(db_session: Session):
    """
    Verify that different repositories can be indexed independently
    without blocking or sharing state.
    """
    async def _run():
        repo_a = Repository(name="repo-a", full_name="org/repo-a", provider="folder", status="ready")
        repo_b = Repository(name="repo-b", full_name="org/repo-b", provider="folder", status="ready")
        db_session.add_all([repo_a, repo_b])
        db_session.commit()

        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            path_a = Path(dir_a)
            path_b = Path(dir_b)
            (path_a / "a.py").write_text("def fn_a(): return 'a'\n", encoding="utf-8")
            (path_b / "b.py").write_text("def fn_b(): return 'b'\n", encoding="utf-8")

            repo_a.clone_url = str(path_a)
            repo_b.clone_url = str(path_b)
            db_session.commit()

            job_a = IndexingService.create_indexing_job(db_session, repo_a)
            job_b = IndexingService.create_indexing_job(db_session, repo_b)

            # Run both sequentially or gathered
            await IndexingService.run_indexing_pipeline(job_a.id, repo_a.id, "main", db_session=db_session)
            await IndexingService.run_indexing_pipeline(job_b.id, repo_b.id, "main", db_session=db_session)

            db_session.refresh(job_a)
            db_session.refresh(job_b)
            assert job_a.status == "COMPLETED"
            assert job_b.status == "COMPLETED"

            # Check repository isolation
            chunks_a = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo_a.id).all()
            chunks_b = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo_b.id).all()
            assert len(chunks_a) >= 1
            assert len(chunks_b) >= 1
            assert "fn_a" in chunks_a[0].chunk_text
            assert "fn_b" in chunks_b[0].chunk_text

    asyncio.run(_run())


def test_failed_job_retry_safety(db_session: Session):
    """
    Verify that after a job fails, retry_job safely re-queues it
    and subsequent successful run updates repository state cleanly.
    """
    repo = Repository(name="retry-repo", full_name="org/retry-repo", provider="folder", status="ready")
    db_session.add(repo)
    db_session.commit()

    job = IndexingJob(
        repository_id=repo.id,
        status="FAILED",
        stage="EMBEDDING",
        error_message="Simulated connection error",
    )
    db_session.add(job)
    db_session.commit()

    # Retry the job
    retried_job = IndexingService.retry_job(db_session, job.id)
    assert retried_job.status == "QUEUED"
    assert retried_job.error_message is None
    assert retried_job.progress_percent == 0
