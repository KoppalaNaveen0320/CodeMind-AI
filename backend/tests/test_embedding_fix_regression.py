import asyncio
import io
import os
import zipfile
import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from backend.app.db.session import SessionLocal
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.services.indexing_service import IndexingService
from backend.app.integrations.embeddings.service import EmbeddingService
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.integrations.github.service import GitHubService


# ---------------------------------------------------------------------------
# 1. Small Repository (< 32 chunks)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_small_repo_fewer_than_32_chunks(db_session: Session):
    """Verify embedding generation succeeds for small repos with fewer than 32 chunks."""
    repo = Repository(name="small-repo", full_name="test/small-repo", is_private=False, default_branch="main")
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)
    chunks = []
    for i in range(7):
        c = CodeChunk(
            repository_id=repo.id,
            file_path=f"src/small_{i}.py",
            chunk_index=0,
            chunk_text=f"def small_func_{i}(): return {i}\n",
            content_hash=f"hash_small_{i}",
            language="python",
            start_line=1,
            end_line=2,
        )
        db_session.add(c)
        chunks.append(c)
    db_session.commit()

    res = await EmbeddingService.embed_new_chunks(db_session, chunks, provider=provider, repository_id=repo.id)
    assert res["success"] is True
    assert res["embedded_count"] == 7
    assert res["skipped_count"] == 0

    # Verify all 7 persisted in DB with 768-dim embeddings
    persisted = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
    assert len(persisted) == 7
    for p in persisted:
        assert p.embedding is not None
        assert len(list(p.embedding)) == 768
        assert p.embedding_model == provider.model_name


# ---------------------------------------------------------------------------
# 2. Repository with Exactly 32 Chunks (Exact Batch Boundary)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_exact_32_chunks_boundary(db_session: Session):
    """Verify repository with exactly 32 chunks updates all rows without StaleDataError."""
    repo = Repository(name="exact32-repo", full_name="test/exact32-repo", is_private=False, default_branch="main")
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)
    chunks = []
    for i in range(32):
        c = CodeChunk(
            repository_id=repo.id,
            file_path=f"src/exact32_{i}.py",
            chunk_index=0,
            chunk_text=f"def exact32_func_{i}(): return {i}\n",
            content_hash=f"hash_exact32_{i}",
            language="python",
            start_line=1,
            end_line=2,
        )
        db_session.add(c)
        chunks.append(c)
    db_session.commit()

    res = await EmbeddingService.embed_new_chunks(db_session, chunks, provider=provider, repository_id=repo.id)
    assert res["success"] is True
    assert res["embedded_count"] == 32
    assert res["skipped_count"] == 0

    # Verify in DB
    embedded_count = (
        db_session.query(CodeChunk)
        .filter(CodeChunk.repository_id == repo.id, CodeChunk.embedding.isnot(None))
        .count()
    )
    assert embedded_count == 32


# ---------------------------------------------------------------------------
# 3. Repository with More Than 32 Chunks (Multiple Embedding Batches)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_multi_batch_more_than_32_chunks(db_session: Session):
    """Verify arbitrary batch sizes (> 32) update across multiple consecutive batches without row-count mismatch."""
    repo = Repository(name="multibatch-repo", full_name="test/multibatch-repo", is_private=False, default_branch="main")
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)
    chunk_count = 85  # Exercises 32 + 32 + 21
    chunks = []
    for i in range(chunk_count):
        c = CodeChunk(
            repository_id=repo.id,
            file_path=f"src/mb_{i}.py",
            chunk_index=0,
            chunk_text=f"def mb_func_{i}():\n    val = {i}\n    return val * 2\n",
            content_hash=f"hash_mb_{i}",
            language="python",
            start_line=1,
            end_line=4,
        )
        db_session.add(c)
        chunks.append(c)
    db_session.commit()

    res = await EmbeddingService.embed_new_chunks(db_session, chunks, provider=provider, repository_id=repo.id)
    assert res["success"] is True
    assert res["embedded_count"] == 85
    assert res["skipped_count"] == 0

    db_embedded = (
        db_session.query(CodeChunk)
        .filter(CodeChunk.repository_id == repo.id, CodeChunk.embedding.isnot(None))
        .count()
    )
    assert db_embedded == 85


# ---------------------------------------------------------------------------
# 4. Larger Repository with Many Files and Chunks
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_larger_repository_many_files_and_chunks(db_session: Session):
    """Verify a larger repository with multiple files and 100 chunks embeds correctly."""
    repo = Repository(name="large-repo", full_name="test/large-repo", is_private=False, default_branch="main")
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)
    chunks = []
    for file_idx in range(20):
        f = IndexedFile(
            repository_id=repo.id,
            path=f"src/module_{file_idx}/handler.py",
            language="python",
            lines_count=100,
            size_bytes=2048,
            content_hash=f"file_hash_{file_idx}"
        )
        db_session.add(f)
        db_session.flush()

        for chunk_idx in range(5):
            c = CodeChunk(
                repository_id=repo.id,
                file_id=f.id,
                file_path=f.path,
                chunk_index=chunk_idx,
                chunk_text=f"def handler_{file_idx}_{chunk_idx}(): pass",
                content_hash=f"hash_{file_idx}_{chunk_idx}",
                language="python",
                start_line=chunk_idx * 15 + 1,
                end_line=chunk_idx * 15 + 15,
            )
            db_session.add(c)
            chunks.append(c)
    db_session.commit()

    assert len(chunks) == 100
    res = await EmbeddingService.embed_new_chunks(db_session, chunks, provider=provider, repository_id=repo.id)
    assert res["success"] is True
    assert res["embedded_count"] == 100

    unembedded = (
        db_session.query(CodeChunk)
        .filter(CodeChunk.repository_id == repo.id, CodeChunk.embedding.is_(None))
        .count()
    )
    assert unembedded == 0


# ---------------------------------------------------------------------------
# 5. Full Pipeline: GitHub Ingestion Path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_github_ingestion_path(db_session: Session, monkeypatch, tmp_path):
    """Verify full end-to-end GitHub indexing pipeline completes with real chunk persistence and embeddings."""
    repo = Repository(
        name="gh-pipe-repo",
        full_name="acme/gh-pipe-repo",
        provider="github",
        default_branch="main",
        status="pending"
    )
    db_session.add(repo)
    db_session.commit()

    job = IndexingService.create_indexing_job(db_session, repo, "main")

    # Mock download_and_extract_archive to create real multi-chunk files
    async def mock_download(token, full_name, ref, target_dir):
        repo_dir = target_dir / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "main.py").write_text(
            "\n".join([f"def func_{i}():\n    return {i}\n" for i in range(40)]),
            encoding="utf-8"
        )
        (repo_dir / "service.py").write_text(
            "class Service:\n    def execute(self):\n        return 'ok'\n",
            encoding="utf-8"
        )
        return repo_dir

    monkeypatch.setattr(GitHubService, "download_and_extract_archive", mock_download)

    # Use mock provider for test isolation
    mock_prov = MockEmbeddingProvider(dimension=768)
    monkeypatch.setattr("backend.app.integrations.embeddings.service.get_embedding_provider", lambda *args: mock_prov)

    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "COMPLETED"
    assert job.stage == "COMPLETED"
    assert job.error_message is None
    assert repo.status == "ready"
    assert repo.files_count == 2

    # Verify chunks have embeddings
    chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
    assert len(chunks) > 0
    for c in chunks:
        assert c.embedding is not None
        assert len(list(c.embedding)) == 768


# ---------------------------------------------------------------------------
# 6. Full Pipeline: ZIP Folder Ingestion Path
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_zip_folder_ingestion_path(db_session: Session, monkeypatch, tmp_path):
    """Verify local uploaded ZIP archive ingestion path indexes all files and chunks successfully."""
    # Create a test folder with multiple files
    local_repo_dir = tmp_path / "local_export_project"
    local_repo_dir.mkdir(parents=True, exist_ok=True)
    (local_repo_dir / "index.js").write_text(
        "function startApp() { console.log('started'); }\nmodule.exports = { startApp };\n",
        encoding="utf-8"
    )
    (local_repo_dir / "utils.py").write_text(
        "\n".join([f"def utility_fn_{i}(x):\n    return x + {i}\n" for i in range(35)]),
        encoding="utf-8"
    )

    repo = Repository(
        name="local_export_project",
        full_name="local/local_export_project",
        provider="folder",
        clone_url=str(local_repo_dir),
        default_branch="main",
        status="pending"
    )
    db_session.add(repo)
    db_session.commit()

    job = IndexingService.create_indexing_job(db_session, repo, "main")

    mock_prov = MockEmbeddingProvider(dimension=768)
    monkeypatch.setattr("backend.app.integrations.embeddings.service.get_embedding_provider", lambda *args: mock_prov)

    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "COMPLETED"
    assert job.stage == "COMPLETED"
    assert repo.status == "ready"
    assert repo.files_count == 2

    # Verify chunks created and embedded
    chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
    assert len(chunks) > 0
    assert all(c.embedding is not None for c in chunks)


# ---------------------------------------------------------------------------
# 7. Repositories Containing Different Programming Languages (Polyglot)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_polyglot_languages_indexing(db_session: Session, monkeypatch, tmp_path):
    """Verify embedding generation handles polyglot repositories (Python, JS, TS, Go)."""
    repo_dir = tmp_path / "polyglot_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    (repo_dir / "app.py").write_text("def run_py(): return 'python'\n", encoding="utf-8")
    (repo_dir / "server.js").write_text("function runJs() { return 'js'; }\n", encoding="utf-8")
    (repo_dir / "client.ts").write_text("export function runTs(): string { return 'ts'; }\n", encoding="utf-8")
    (repo_dir / "main.go").write_text("package main\nfunc RunGo() string { return \"go\" }\n", encoding="utf-8")

    repo = Repository(
        name="polyglot",
        full_name="local/polyglot",
        provider="folder",
        clone_url=str(repo_dir),
        default_branch="main"
    )
    db_session.add(repo)
    db_session.commit()

    job = IndexingService.create_indexing_job(db_session, repo, "main")
    mock_prov = MockEmbeddingProvider(dimension=768)
    monkeypatch.setattr("backend.app.integrations.embeddings.service.get_embedding_provider", lambda *args: mock_prov)

    await IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "COMPLETED"
    assert repo.status == "ready"
    assert repo.files_count == 4

    chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
    assert len(chunks) >= 4
    languages = {c.language for c in chunks}
    assert "python" in languages
    assert "javascript" in languages
    assert all(c.embedding is not None for c in chunks)


# ---------------------------------------------------------------------------
# 8. Sequential Repository Indexing
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_sequential_repositories_indexing(db_session: Session):
    """Verify indexing two repositories sequentially preserves strict repository isolation."""
    repo1 = Repository(name="seq-repo-1", full_name="test/seq-repo-1", default_branch="main")
    repo2 = Repository(name="seq-repo-2", full_name="test/seq-repo-2", default_branch="main")
    db_session.add_all([repo1, repo2])
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)

    # Chunks for Repo 1
    chunks1 = [
        CodeChunk(repository_id=repo1.id, file_path="f1.py", chunk_index=0, chunk_text="def r1(): pass", content_hash="h1", start_line=1, end_line=1),
        CodeChunk(repository_id=repo1.id, file_path="f2.py", chunk_index=0, chunk_text="def r2(): pass", content_hash="h2", start_line=1, end_line=1),
    ]
    db_session.add_all(chunks1)
    db_session.commit()

    res1 = await EmbeddingService.embed_new_chunks(db_session, chunks1, provider=provider, repository_id=repo1.id)
    assert res1["success"] is True
    assert res1["embedded_count"] == 2

    # Chunks for Repo 2 (one chunk has identical content_hash to test cross-repo reuse)
    chunks2 = [
        CodeChunk(repository_id=repo2.id, file_path="f1.py", chunk_index=0, chunk_text="def r1(): pass", content_hash="h1", start_line=1, end_line=1),
        CodeChunk(repository_id=repo2.id, file_path="f3.py", chunk_index=0, chunk_text="def r3(): pass", content_hash="h3", start_line=1, end_line=1),
    ]
    db_session.add_all(chunks2)
    db_session.commit()

    res2 = await EmbeddingService.embed_new_chunks(db_session, chunks2, provider=provider, repository_id=repo2.id)
    assert res2["success"] is True
    assert res2["reused_count"] == 1
    assert res2["embedded_count"] == 1

    # Verify repo 1 chunks still belong strictly to repo 1
    c_r1 = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo1.id).all()
    assert len(c_r1) == 2
    assert all(c.repository_id == repo1.id for c in c_r1)

    # Verify repo 2 chunks belong strictly to repo 2
    c_r2 = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo2.id).all()
    assert len(c_r2) == 2
    assert all(c.repository_id == repo2.id for c in c_r2)


# ---------------------------------------------------------------------------
# 9. Concurrent Job Claiming & Duplicate Task Prevention
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_concurrent_job_claim_prevention(db_session: Session, monkeypatch):
    """Verify that multiple concurrent executions of the same job do not step on each other."""
    repo = Repository(name="concurrent-repo", full_name="acme/concurrent-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    job = IndexingJob(repository_id=repo.id, status="QUEUED", stage="QUEUED")
    db_session.add(job)
    db_session.commit()

    mock_prov = MockEmbeddingProvider(dimension=768)
    monkeypatch.setattr("backend.app.integrations.embeddings.service.get_embedding_provider", lambda *args: mock_prov)

    # Run pipeline concurrently in two tasks
    task1 = IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)
    task2 = IndexingService.run_indexing_pipeline(job.id, repo.id, "main", db_session=db_session)

    await asyncio.gather(task1, task2)

    db_session.refresh(job)
    assert job.status in ["COMPLETED", "INDEXING"]
    # No crash or StaleDataError occurred


# ---------------------------------------------------------------------------
# 10. Retry After Embedding Stage Failure (Idempotency)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_retry_after_embedding_failure(db_session: Session):
    """Verify retry after partial embedding failure only embeds remaining chunks and succeeds idempotently."""
    repo = Repository(name="retry-repo", full_name="test/retry-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)

    # Create 4 chunks, manually embed 2
    c1 = CodeChunk(repository_id=repo.id, file_path="c1.py", chunk_index=0, chunk_text="def c1(): pass", content_hash="h_c1", start_line=1, end_line=1, embedding=[0.1] * 768, embedding_model=provider.model_name)
    c2 = CodeChunk(repository_id=repo.id, file_path="c2.py", chunk_index=0, chunk_text="def c2(): pass", content_hash="h_c2", start_line=1, end_line=1, embedding=[0.2] * 768, embedding_model=provider.model_name)
    c3 = CodeChunk(repository_id=repo.id, file_path="c3.py", chunk_index=0, chunk_text="def c3(): pass", content_hash="h_c3", start_line=1, end_line=1)
    c4 = CodeChunk(repository_id=repo.id, file_path="c4.py", chunk_index=0, chunk_text="def c4(): pass", content_hash="h_c4", start_line=1, end_line=1)
    db_session.add_all([c1, c2, c3, c4])
    db_session.commit()

    # Retry should only embed c3 and c4
    res = await EmbeddingService.embed_new_chunks(db_session, [c1, c2, c3, c4], provider=provider, repository_id=repo.id)
    assert res["success"] is True
    assert res["embedded_count"] == 2
    assert res["already_embedded_count"] == 2

    # All 4 chunks now have embeddings
    all_chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
    assert len(all_chunks) == 4
    assert all(c.embedding is not None for c in all_chunks)


# ---------------------------------------------------------------------------
# 11. Missing or Stale Chunk IDs Handled Explicitly
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_missing_or_stale_chunk_ids_handling(db_session: Session):
    """Verify missing/deleted database rows are handled gracefully without throwing StaleDataError."""
    repo = Repository(name="stale-repo", full_name="test/stale-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)

    c_valid = CodeChunk(repository_id=repo.id, file_path="v.py", chunk_index=0, chunk_text="def valid(): pass", content_hash="h_valid", start_line=1, end_line=1)
    c_stale = CodeChunk(repository_id=repo.id, file_path="s.py", chunk_index=0, chunk_text="def stale(): pass", content_hash="h_stale", start_line=1, end_line=1)
    db_session.add_all([c_valid, c_stale])
    db_session.commit()

    # Delete c_stale from DB
    db_session.query(CodeChunk).filter(CodeChunk.id == c_stale.id).delete()
    db_session.commit()

    # Pass both descriptors to embed_new_chunks
    res = await EmbeddingService.embed_new_chunks(db_session, [c_valid, c_stale], provider=provider, repository_id=repo.id)
    assert res["success"] is True
    assert res["embedded_count"] == 1
    assert res["skipped_count"] == 1

    # Valid chunk received embedding
    db_session.refresh(c_valid)
    assert c_valid.embedding is not None


# ---------------------------------------------------------------------------
# 12. Verification that Each Embedding Belongs to Correct Chunk and Repo
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_chunk_and_repository_ownership_verification(db_session: Session):
    """Verify cross-repository embedding update attempts cannot contaminate other repos."""
    repo_a = Repository(name="repo-a", full_name="test/repo-a")
    repo_b = Repository(name="repo-b", full_name="test/repo-b")
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=768)

    chunk_b = CodeChunk(repository_id=repo_b.id, file_path="b.py", chunk_index=0, chunk_text="def b(): pass", content_hash="h_b", start_line=1, end_line=1)
    db_session.add(chunk_b)
    db_session.commit()

    # Attempt to update chunk_b while scoping to repo_a
    res = await EmbeddingService.embed_new_chunks(db_session, [chunk_b], provider=provider, repository_id=repo_a.id)
    # The update was scoped to repo_a, so 0 rows matched for repo_a
    assert res["embedded_count"] == 0
    assert res["skipped_count"] == 1

    # chunk_b in repo_b was NOT modified
    db_session.refresh(chunk_b)
    assert chunk_b.embedding is None


# ---------------------------------------------------------------------------
# 13. Failed Indexing Never Incorrectly Reports Success
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_failed_indexing_never_reports_success(db_session: Session):
    """Verify that if an unrecoverable failure occurs in embedding, failure is reported truthfully."""
    repo = Repository(name="fail-truthful-repo", full_name="test/fail-truthful-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    c = CodeChunk(repository_id=repo.id, file_path="f.py", chunk_index=0, chunk_text="def f(): pass", content_hash="h_f", start_line=1, end_line=1)
    db_session.add(c)
    db_session.commit()

    # Unconfigured provider (or forced error provider)
    class BrokenProvider(MockEmbeddingProvider):
        @property
        def is_configured(self) -> bool:
            return False

    broken_prov = BrokenProvider(dimension=768)
    res = await EmbeddingService.embed_new_chunks(db_session, [c], provider=broken_prov, repository_id=repo.id)
    assert res["success"] is False
    assert res["embedded_count"] == 0
    assert "unconfigured" in res["reason"]

    # Verify chunk was NOT marked as embedded
    db_session.refresh(c)
    assert c.embedding is None
