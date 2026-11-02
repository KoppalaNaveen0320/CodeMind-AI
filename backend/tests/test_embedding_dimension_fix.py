import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.integrations.embeddings.service import EmbeddingService
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.integrations.embeddings.base import EmbeddingError


class CustomDimMockProvider(MockEmbeddingProvider):
    def __init__(self, dimension: int, model: str = "custom-mock-v1"):
        super().__init__(dimension=dimension, model=model)


@pytest.mark.anyio
async def test_valid_768_dimension_writes_cleanly(db_session: Session):
    """Verify that a provider returning 768-dim vectors writes cleanly and persists."""
    repo = Repository(name="valid-dim-repo", full_name="test/valid-dim-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()
    repo_id = repo.id

    chunk = CodeChunk(
        repository_id=repo_id,
        file_path="src/main.py",
        chunk_index=0,
        chunk_text="def test_ok(): pass",
        content_hash="hash_valid_768",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk)
    db_session.commit()
    chunk_id = chunk.id

    provider = CustomDimMockProvider(dimension=768)
    res = await EmbeddingService.embed_new_chunks(db_session, [chunk], provider=provider, repository_id=repo_id)

    assert res["success"] is True
    assert res["embedded_count"] == 1
    assert res["skipped_count"] == 0

    persisted = db_session.query(CodeChunk).filter(CodeChunk.id == chunk_id).first()
    assert persisted is not None
    assert persisted.embedding is not None
    assert len(list(persisted.embedding)) == 768
    assert persisted.embedding_model == provider.model_name


@pytest.mark.anyio
async def test_dimension_mismatch_rejected_before_db_write(db_session: Session):
    """Verify that a vector with 12379 dimensions is rejected before database write with rollback."""
    repo = Repository(name="mismatch-repo", full_name="test/mismatch-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()
    repo_id = repo.id

    chunk = CodeChunk(
        repository_id=repo_id,
        file_path="src/bad_dim.py",
        chunk_index=0,
        chunk_text="def test_bad(): pass",
        content_hash="hash_mismatch_12379",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk)
    db_session.commit()
    chunk_id = chunk.id

    # Provider with expected dimension 768, but returns 12379 dimensions
    provider_12379 = CustomDimMockProvider(dimension=768)

    fake_12379_vec = [0.01] * 12379
    with patch.object(provider_12379, "embed_batch", new=AsyncMock(return_value=[fake_12379_vec])):
        res = await EmbeddingService.embed_new_chunks(
            db_session, [chunk], provider=provider_12379, repository_id=repo_id
        )

    assert res["success"] is False
    assert "Vector dimension mismatch" in res.get("error", "")
    assert "expected 768, got 12379" in res.get("error", "")

    # Confirm transaction rolled back cleanly
    refreshed = db_session.query(CodeChunk).filter(CodeChunk.id == chunk_id).first()
    assert refreshed is None or refreshed.embedding is None


@pytest.mark.anyio
async def test_non_list_vector_rejected(db_session: Session):
    """Verify that non-list vectors are rejected before write."""
    repo = Repository(name="nonlist-repo", full_name="test/nonlist-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()
    repo_id = repo.id

    chunk = CodeChunk(
        repository_id=repo_id,
        file_path="src/nonlist.py",
        chunk_index=0,
        chunk_text="def test_nonlist(): pass",
        content_hash="hash_nonlist",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk)
    db_session.commit()

    provider = CustomDimMockProvider(dimension=768)
    with patch.object(provider, "embed_batch", new=AsyncMock(return_value=["invalid_str_vector"])):
        res = await EmbeddingService.embed_new_chunks(db_session, [chunk], provider=provider, repository_id=repo_id)
        assert res["success"] is False
        assert "non-list vector" in res.get("error", "")


@pytest.mark.anyio
async def test_non_numeric_vector_rejected(db_session: Session):
    """Verify that vectors with non-numeric elements are rejected before write."""
    repo = Repository(name="nonnum-repo", full_name="test/nonnum-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()
    repo_id = repo.id

    chunk = CodeChunk(
        repository_id=repo_id,
        file_path="src/nonnum.py",
        chunk_index=0,
        chunk_text="def test_nonnum(): pass",
        content_hash="hash_nonnum",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk)
    db_session.commit()

    provider = CustomDimMockProvider(dimension=768)
    non_numeric_vec = [0.1] * 767 + ["bad_value"]
    with patch.object(provider, "embed_batch", new=AsyncMock(return_value=[non_numeric_vec])):
        res = await EmbeddingService.embed_new_chunks(db_session, [chunk], provider=provider, repository_id=repo_id)
        assert res["success"] is False
        assert "non-numeric elements" in res.get("error", "")


@pytest.mark.anyio
async def test_provider_error_rolls_back_transaction(db_session: Session):
    """Verify that when a provider throws EmbeddingError, the transaction rolls back cleanly."""
    repo = Repository(name="error-repo", full_name="test/error-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()
    repo_id = repo.id

    chunk = CodeChunk(
        repository_id=repo_id,
        file_path="src/error.py",
        chunk_index=0,
        chunk_text="def test_err(): pass",
        content_hash="hash_error",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk)
    db_session.commit()
    chunk_id = chunk.id

    provider = CustomDimMockProvider(dimension=768)
    with patch.object(provider, "embed_batch", side_effect=EmbeddingError("Connection reset by peer")):
        res = await EmbeddingService.embed_new_chunks(db_session, [chunk], provider=provider, repository_id=repo_id)

    assert res["success"] is False
    assert "Connection reset by peer" in res.get("error", "")

    refreshed = db_session.query(CodeChunk).filter(CodeChunk.id == chunk_id).first()
    assert refreshed is None or refreshed.embedding is None


@pytest.mark.anyio
async def test_reused_vector_with_wrong_dimension_is_not_reused(db_session: Session):
    """Verify that an existing vector with mismatched dimension is not reused."""
    repo = Repository(name="reuse-dim-repo", full_name="test/reuse-dim-repo", default_branch="main")
    db_session.add(repo)
    db_session.commit()
    repo_id = repo.id

    provider = CustomDimMockProvider(dimension=768)

    # First chunk: valid 768
    chunk1 = CodeChunk(
        repository_id=repo_id,
        file_path="src/c1.py",
        chunk_index=0,
        chunk_text="def f(): pass",
        content_hash="shared_hash_123",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk1)
    db_session.commit()

    res1 = await EmbeddingService.embed_new_chunks(db_session, [chunk1], provider=provider, repository_id=repo_id)
    assert res1["success"] is True
    assert res1["embedded_count"] == 1

    # Second chunk: identical hash, but requested with 1536-dim provider
    chunk2 = CodeChunk(
        repository_id=repo_id,
        file_path="src/c2.py",
        chunk_index=0,
        chunk_text="def f(): pass",
        content_hash="shared_hash_123",
        start_line=1,
        end_line=1,
    )
    db_session.add(chunk2)
    db_session.commit()
    chunk2_id = chunk2.id

    provider_1536 = CustomDimMockProvider(dimension=1536, model="mock-1536")
    # It should not reuse 768-dim vector for a 1536-dim request; it must re-embed with provider_1536
    res2 = await EmbeddingService.embed_new_chunks(db_session, [chunk2], provider=provider_1536, repository_id=repo_id)
    assert res2["success"] is True
    assert res2["embedded_count"] == 1
    assert res2["reused_count"] == 0

    refreshed2 = db_session.query(CodeChunk).filter(CodeChunk.id == chunk2_id).first()
    assert len(list(refreshed2.embedding)) == 1536
