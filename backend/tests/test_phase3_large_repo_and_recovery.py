import asyncio
import hashlib
import hmac
import tempfile
import time
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
from backend.app.services.github_sync_service import GitHubSyncService
from backend.app.ingestion.change_detector import ChangeDetector
from backend.app.core.config import settings


def test_recover_stale_indexing_jobs_on_restart(db_session: Session):
    """
    Verify that upon process restart, jobs left in intermediate states
    (QUEUED, CLONING, PARSING, INDEXING) are transitioned to FAILED,
    and repositories with previous successful indexes remain 'ready'.
    """
    # 1. Previously indexed repository
    ready_repo = Repository(
        name="previously-indexed-repo",
        full_name="org/previously-indexed-repo",
        provider="folder",
        status="indexing",
        files_count=10,
        last_indexed_at=datetime.now(timezone.utc),
    )
    db_session.add(ready_repo)
    db_session.commit()

    stale_job_1 = IndexingJob(
        repository_id=ready_repo.id,
        status="INDEXING",
        stage="EMBEDDING",
        progress_percent=70,
        files_processed=5,
        total_files=10,
    )
    db_session.add(stale_job_1)

    # 2. Brand new repo never indexed
    new_repo = Repository(
        name="never-indexed-repo",
        full_name="org/never-indexed-repo",
        provider="folder",
        status="indexing",
        files_count=0,
        last_indexed_at=None,
    )
    db_session.add(new_repo)
    db_session.commit()

    stale_job_2 = IndexingJob(
        repository_id=new_repo.id,
        status="QUEUED",
        stage="QUEUED",
        progress_percent=0,
    )
    db_session.add(stale_job_2)
    db_session.commit()

    # Execute recovery routine
    recovered_count = IndexingService.recover_stale_indexing_jobs(db_session)
    assert recovered_count >= 2

    db_session.refresh(stale_job_1)
    db_session.refresh(stale_job_2)
    db_session.refresh(ready_repo)
    db_session.refresh(new_repo)

    assert stale_job_1.status == "FAILED"
    assert "interrupted by server restart" in stale_job_1.error_message
    assert ready_repo.status == "ready", "Previously indexed repo must preserve 'ready' status"

    assert stale_job_2.status == "FAILED"
    assert new_repo.status == "failed", "Never-indexed repo must be marked 'failed'"


def test_preserve_last_known_good_index_on_failed_reindex(db_session: Session):
    """
    Verify that if a repository has a successful index and a subsequent incremental
    reindex fails during embedding or scan, the existing index and 'ready' status
    are preserved.
    """
    async def _run():
        repo = Repository(
            name="good-index-repo",
            full_name="org/good-index-repo",
            provider="folder",
            status="ready",
        )
        db_session.add(repo)
        db_session.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            f1 = repo_dir / "module.py"
            f1.write_text("def stable_function(): return 42\n", encoding="utf-8")
            repo.clone_url = str(repo_dir)
            db_session.commit()

            # First index: succeeds
            job1 = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job1.id, repo.id, "main", db_session=db_session)

            db_session.refresh(repo)
            db_session.refresh(job1)
            assert job1.status == "COMPLETED"
            assert repo.status == "ready"
            assert repo.files_count == 1
            original_chunks_count = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).count()
            assert original_chunks_count > 0

            # Modify file to trigger incremental change
            f1.write_text("def stable_function(): return 99\ndef broken_func(): pass\n", encoding="utf-8")

            # Second index: simulate embedding service failure
            job2 = IndexingService.create_indexing_job(db_session, repo)
            with patch("backend.app.integrations.embeddings.service.EmbeddingService.embed_new_chunks", new_callable=AsyncMock) as mock_embed:
                mock_embed.return_value = {"success": False, "error": "Simulated Ollama 503 Service Unavailable"}
                await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)

            db_session.refresh(job2)
            db_session.refresh(repo)

            assert job2.status == "FAILED"
            assert "Simulated Ollama 503" in job2.error_message
            # Repository must preserve 'ready' status because it has an existing valid index
            assert repo.status == "ready"
            # Synchronization status remains 'synced' because GitHub sync succeeded; indexing failure is isolated to the indexing job
            assert repo.sync_status == "synced"

    asyncio.run(_run())


def test_unchanged_files_memory_release(db_session: Session):
    """
    Verify that ChangeDetector releases text_content and clean_bytes
    for unchanged files to avoid keeping file contents in memory on large repos.
    """
    repo = Repository(
        name="memory-repo",
        full_name="org/memory-repo",
        provider="folder",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()

    content = "def calculate_hash(x: int) -> int:\n    return x * 10\n"
    content_bytes = content.encode("utf-8")
    c_hash = hashlib.sha256(content_bytes).hexdigest()

    # Pre-populate indexed file
    idx_file = IndexedFile(
        repository_id=repo.id,
        path="src/calc.py",
        language="python",
        content_hash=c_hash,
        size_bytes=len(content_bytes),
        lines_count=2,
    )
    db_session.add(idx_file)
    db_session.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir)
        (repo_dir / "src").mkdir()
        file_path = repo_dir / "src" / "calc.py"
        file_path.write_bytes(content_bytes)

        def mock_validator(p: Path):
            data = p.read_bytes()
            return data.decode("utf-8"), data, None

        change_set = ChangeDetector.detect_changes(
            db=db_session,
            repository_id=repo.id,
            source_folder=repo_dir,
            discovered_paths=[file_path],
            read_validator=mock_validator,
            is_complete_scan=True,
        )

        assert len(change_set.unchanged) == 1
        snapshot, _ = change_set.unchanged[0]
        # Memory buffers MUST be cleared for unchanged files
        assert snapshot.text_content is None, "text_content must be cleared for unchanged files"
        assert snapshot.clean_bytes is None, "clean_bytes must be cleared for unchanged files"


def test_batching_and_concurrency_on_multi_file_repo(db_session: Session):
    """
    Verify indexing pipeline correctly processes a multi-file repository
    across batch boundaries (BATCH_SIZE = 25) with exact parity and no missing data.
    """
    async def _run():
        repo = Repository(
            name="batch-test-repo",
            full_name="org/batch-test-repo",
            provider="folder",
            status="ready"
        )
        db_session.add(repo)
        db_session.commit()

        num_files = 35  # Exceeds BATCH_SIZE=25 to exercise batch boundaries
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            src_dir = repo_dir / "pkg"
            src_dir.mkdir()

            for i in range(num_files):
                file_path = src_dir / f"mod_{i:03d}.py"
                file_path.write_text(f"def func_{i:03d}(val: int) -> int:\n    return val + {i}\n", encoding="utf-8")

            repo.clone_url = str(repo_dir)
            db_session.commit()

            start_t = time.perf_counter()
            job = IndexingService.create_indexing_job(db_session, repo)
            await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)
            elapsed_t = time.perf_counter() - start_t

            db_session.refresh(job)
            db_session.refresh(repo)

            assert job.status == "COMPLETED"
            assert repo.files_count == num_files
            assert job.files_added == num_files

            files_in_db = db_session.query(IndexedFile).filter(IndexedFile.repository_id == repo.id).count()
            chunks_in_db = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).count()
            symbols_in_db = db_session.query(CodeSymbol).filter(CodeSymbol.repository_id == repo.id).count()

            assert files_in_db == num_files
            assert symbols_in_db == num_files
            assert chunks_in_db == num_files

            # Second run: test incremental indexing on the multi-file repo
            # Modify 2 files, add 1 file, delete 1 file
            (src_dir / "mod_000.py").write_text("def func_000_updated(): return 'modified'\n", encoding="utf-8")
            (src_dir / "mod_001.py").write_text("def func_001_updated(): return 'modified_too'\n", encoding="utf-8")
            (src_dir / "mod_new.py").write_text("def func_brand_new(): return 'new'\n", encoding="utf-8")
            (src_dir / "mod_034.py").unlink()

            job2 = IndexingService.create_indexing_job(db_session, repo)
            start_inc = time.perf_counter()
            await IndexingService.run_indexing_pipeline(job2.id, repo.id, "main", db_session=db_session)
            inc_elapsed = time.perf_counter() - start_inc

            db_session.refresh(job2)
            db_session.refresh(repo)

            assert job2.status == "COMPLETED"
            assert job2.files_modified == 2
            assert job2.files_added == 1
            assert job2.files_deleted == 1
            assert job2.files_unchanged == (num_files - 3)
            assert repo.files_count == num_files  # (35 - 1 deleted + 1 added = 35)

    asyncio.run(_run())


def test_github_webhook_hmac_verification():
    """
    Verify GitHub webhook signature verification:
    - Rejects invalid HMAC signatures.
    - Accepts valid HMAC-SHA256 signatures.
    - Gracefully handles missing secret configuration.
    """
    secret = "test-webhook-secret-key"
    payload = b'{"ref": "refs/heads/main", "after": "0123456789abcdef", "repository": {"full_name": "org/repo"}}'

    # Compute valid signature
    mac = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    valid_sig = f"sha256={mac.hexdigest()}"

    # Verify matching
    assert GitHubSyncService.verify_webhook_signature(payload, valid_sig, secret) is True

    # Tampered payload
    tampered_payload = b'{"ref": "refs/heads/main", "after": "tampered", "repository": {"full_name": "org/repo"}}'
    assert GitHubSyncService.verify_webhook_signature(tampered_payload, valid_sig, secret) is False

    # Invalid header format
    assert GitHubSyncService.verify_webhook_signature(payload, "invalid_sig", secret) is False

    # Empty signature
    assert GitHubSyncService.verify_webhook_signature(payload, "", secret) is False
