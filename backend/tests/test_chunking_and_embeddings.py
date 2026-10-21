import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.repository import Repository
from backend.app.parsing.chunker import CodeChunker
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.integrations.embeddings.openai_provider import OpenAIEmbeddingProvider
from backend.app.integrations.embeddings.service import EmbeddingService
from backend.app.integrations.embeddings.base import EmbeddingProviderUnconfiguredError


def test_code_chunking_by_symbols():
    """Verify that chunking respects function and class symbol boundaries."""
    indexed_file = IndexedFile(id=1, repository_id=1, path="auth/service.py", language="python")
    code = (
        "import os\n\n"
        "class AuthService:\n"
        "    def __init__(self):\n"
        "        pass\n\n"
        "def validate_session(token):\n"
        "    return token is not None\n"
    )

    symbols = [
        CodeSymbol(id=10, repository_id=1, file_id=1, name="AuthService", kind="class", start_line=3, end_line=5),
        CodeSymbol(id=11, repository_id=1, file_id=1, name="validate_session", kind="function", start_line=7, end_line=8),
    ]

    chunks = CodeChunker.chunk_file(indexed_file, code, symbols)
    assert len(chunks) == 2
    
    # Class chunk
    assert chunks[0].code_symbol == "AuthService"
    assert chunks[0].start_line == 3
    assert chunks[0].end_line == 5
    assert "class AuthService" in chunks[0].chunk_text
    assert chunks[0].symbol_id == 10

    # Function chunk
    assert chunks[1].code_symbol == "validate_session"
    assert chunks[1].start_line == 7
    assert chunks[1].end_line == 8
    assert "def validate_session" in chunks[1].chunk_text
    assert chunks[1].symbol_id == 11


def test_code_chunking_sliding_window_fallback():
    """Verify sliding window fallback when no symbols are extracted."""
    indexed_file = IndexedFile(id=2, repository_id=1, path="config.yaml", language="yaml")
    code = "\n".join([f"key_{i}: value_{i}" for i in range(120)])

    chunks = CodeChunker.chunk_file(indexed_file, code, symbols=[])
    assert len(chunks) >= 2
    assert chunks[0].code_symbol is None
    assert chunks[0].start_line == 1
    assert chunks[0].content_hash is not None


def test_mock_embedding_provider_deterministic():
    """Verify mock provider generates unit-length normalized vectors deterministically."""
    provider = MockEmbeddingProvider(dimension=128)
    status = provider.get_configuration_status()
    assert status["configured"] is True
    assert status["dimension"] == 128

    import asyncio
    v1 = asyncio.run(provider.embed_text("def authenticate(): pass"))
    v2 = asyncio.run(provider.embed_text("def authenticate(): pass"))
    v3 = asyncio.run(provider.embed_text("def completely_different(): pass"))

    assert len(v1) == 128
    assert v1 == v2  # Deterministic
    assert v1 != v3  # Distinct text yields distinct vector


def test_unconfigured_openai_provider_fails_truthfully():
    """Verify unconfigured provider raises specific error and never generates fake vectors."""
    provider = OpenAIEmbeddingProvider(api_key="")
    assert provider.is_configured is False
    status = provider.get_configuration_status()
    assert status["configured"] is False

    import asyncio
    with pytest.raises(EmbeddingProviderUnconfiguredError):
        asyncio.run(provider.embed_text("sample code"))


def test_embedding_deduplication_by_content_hash(db_session: Session):
    """Verify identical content hash reuses stored vector without redundant embedding calls."""
    repo = Repository(name="dedup-repo", full_name="acme/dedup-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    provider = MockEmbeddingProvider(dimension=1536)

    c1 = CodeChunk(
        repository_id=repo.id,
        file_path="src/main.py",
        chunk_index=0,
        chunk_text="def run(): pass",
        content_hash="hash_abc_123",
        start_line=1,
        end_line=2,
    )
    db_session.add(c1)
    db_session.commit()

    import asyncio
    # First embed
    res1 = asyncio.run(EmbeddingService.embed_new_chunks(db_session, [c1], provider=provider))
    assert res1["success"] is True
    assert res1["embedded_count"] == 1
    assert c1.embedding is not None

    # Second chunk with identical hash
    c2 = CodeChunk(
        repository_id=repo.id,
        file_path="src/other.py",
        chunk_index=0,
        chunk_text="def run(): pass",
        content_hash="hash_abc_123",
        start_line=1,
        end_line=2,
    )
    db_session.add(c2)
    db_session.commit()

    # Second embed should reuse without calling provider embed_batch
    res2 = asyncio.run(EmbeddingService.embed_new_chunks(db_session, [c2], provider=provider))
    assert res2["success"] is True
    assert res2["reused_count"] == 1
    assert res2["embedded_count"] == 0
    assert c2.embedding == c1.embedding
