import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.integrations.embeddings.base import EmbeddingError
from backend.app.integrations.embeddings.ollama_provider import OllamaEmbeddingProvider
from backend.app.integrations.embeddings.service import get_embedding_provider, EmbeddingService
from backend.app.integrations.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.integrations.llm.base import (
    LLMError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
)
from backend.app.integrations.llm.ollama_provider import OllamaLLMProvider
from backend.app.integrations.llm.service import get_llm_provider
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.indexing_job import IndexingJob
from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.assistant_service import AssistantService
from backend.app.services.indexing_service import IndexingService


# ---------------------------------------------------------------------------
# 1. Ollama Chat Request and Response Parsing (Unit Test with Mock)
# ---------------------------------------------------------------------------

def test_ollama_chat_request_and_response_parsing():
    """Verify Ollama chat request formatting and response parsing using unit test mock."""
    provider = OllamaLLMProvider(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:3b",
        temperature=0.2,
        context_limit=4096,
        timeout_seconds=30.0,
    )

    captured_payload = None

    async def mock_post(url, *args, **kwargs):
        nonlocal captured_payload
        captured_payload = kwargs.get("json", {})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "model": "qwen2.5:3b",
            "message": {
                "role": "assistant",
                "content": "Grounded answer from local Qwen model.",
            },
            "done": True,
        }
        return mock_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        messages = [
            {"role": "system", "content": "You are CodeMind assistant."},
            {"role": "user", "content": "Explain the auth module."},
        ]
        result = asyncio.run(provider.generate_chat_response(messages))

    assert result == "Grounded answer from local Qwen model."
    assert captured_payload is not None
    assert captured_payload["model"] == "qwen2.5:3b"
    assert captured_payload["stream"] is False
    assert captured_payload["options"]["temperature"] == 0.2
    assert captured_payload["options"]["num_ctx"] == 4096
    assert len(captured_payload["messages"]) == 2


# ---------------------------------------------------------------------------
# 2. Ollama Embedding Request and Response Parsing (Unit Test with Mock)
# ---------------------------------------------------------------------------

def test_ollama_embedding_request_and_response_parsing():
    """Verify Ollama embedding batch request formatting and response parsing."""
    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model="nomic-embed-text",
        dimension=768,
    )

    captured_payload = None
    mock_vec = [0.01 * (i % 10) for i in range(768)]

    async def mock_post(url, *args, **kwargs):
        nonlocal captured_payload
        captured_payload = kwargs.get("json", {})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "model": "nomic-embed-text",
            "embeddings": [mock_vec, mock_vec],
        }
        return mock_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        texts = ["def auth(): return True", "def verify(): return False"]
        results = asyncio.run(provider.embed_batch(texts))

    assert len(results) == 2
    assert len(results[0]) == 768
    assert captured_payload is not None
    assert captured_payload["model"] == "nomic-embed-text"
    assert captured_payload["input"] == texts


# ---------------------------------------------------------------------------
# 3. Connection Failures and Timeouts (Unit Test with Mock)
# ---------------------------------------------------------------------------

def test_ollama_connection_failures():
    """Verify Ollama connection refusal generates actionable error messages."""
    provider = OllamaLLMProvider(base_url="http://127.0.0.1:11434", model="qwen2.5:3b")

    async def mock_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    with patch("httpx.AsyncClient.post", side_effect=mock_connect_error):
        with pytest.raises(LLMConnectionError) as exc_info:
            asyncio.run(provider.generate_chat_response([{"role": "user", "content": "hi"}]))
        assert "Cannot connect to local Ollama runtime" in str(exc_info.value)
        assert "ollama serve" in str(exc_info.value)


def test_ollama_timeouts():
    """Verify Ollama timeout triggers actionable timeout exception."""
    provider = OllamaLLMProvider(base_url="http://127.0.0.1:11434", model="qwen2.5:3b", timeout_seconds=1.0)

    async def mock_timeout(*args, **kwargs):
        raise httpx.TimeoutException("Read timed out")

    with patch("httpx.AsyncClient.post", side_effect=mock_timeout):
        with pytest.raises(LLMTimeoutError) as exc_info:
            asyncio.run(provider.generate_chat_response([{"role": "user", "content": "hi"}]))
        assert "timed out" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 4. Missing Models (Unit Test with Mock)
# ---------------------------------------------------------------------------

def test_ollama_missing_llm_model():
    """Verify HTTP 404 from Ollama reports missing model with pull instructions."""
    provider = OllamaLLMProvider(base_url="http://127.0.0.1:11434", model="non-existent-llm")

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "model not found"

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        with pytest.raises(LLMModelNotFoundError) as exc_info:
            asyncio.run(provider.generate_chat_response([{"role": "user", "content": "hi"}]))
        assert "not found on local runtime" in str(exc_info.value)
        assert "ollama pull non-existent-llm" in str(exc_info.value)


def test_ollama_missing_embedding_model():
    """Verify HTTP 404 on /api/embed instructs pulling the embedding model."""
    provider = OllamaEmbeddingProvider(base_url="http://127.0.0.1:11434", model="non-existent-embed")

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "model not found"

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        with pytest.raises(EmbeddingError) as exc_info:
            asyncio.run(provider.embed_batch(["some code"]))
        assert "not found" in str(exc_info.value)
        assert "ollama pull non-existent-embed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. Embedding Dimension Validation (Unit Test with Mock)
# ---------------------------------------------------------------------------

def test_ollama_embedding_dimension_validation():
    """Verify provider rejects vectors whose dimensions do not match the expected 768."""
    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model="nomic-embed-text",
        dimension=768,
    )

    # Return 512 dimensions instead of 768
    wrong_dim_vec = [0.1] * 512

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embeddings": [wrong_dim_vec]}

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        with pytest.raises(EmbeddingError) as exc_info:
            asyncio.run(provider.embed_batch(["test code snippet"]))
        assert "Dimension mismatch" in str(exc_info.value)
        assert "expected 768, got 512" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. Embedding Cache and Content-Hash Deduplication
# ---------------------------------------------------------------------------

def test_embedding_cache_and_content_hash_deduplication(db_session: Session):
    """Verify that identical code chunks reuse existing embeddings without calling provider."""
    repo = Repository(name="cache-repo", full_name="acme/cache-repo")
    db_session.add(repo)
    db_session.commit()

    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_path="src/utils.py",
        chunk_index=0,
        chunk_text="def add(a, b): return a + b",
        content_hash="hash_identical_123",
        language="python",
        start_line=1,
        end_line=2,
    )
    chunk2 = CodeChunk(
        repository_id=repo.id,
        file_path="src/other.py",
        chunk_index=0,
        chunk_text="def add(a, b): return a + b",
        content_hash="hash_identical_123",
        language="python",
        start_line=1,
        end_line=2,
    )
    db_session.add_all([chunk1, chunk2])
    db_session.commit()

    mock_provider = MagicMock()
    mock_provider.is_configured = True
    mock_provider.provider_name = "ollama"
    mock_provider.model_name = "nomic-embed-text"
    sample_vec = [0.05] * 768
    mock_provider.embed_batch = AsyncMock(return_value=[sample_vec])

    # First embed chunk1
    res1 = asyncio.run(EmbeddingService.embed_new_chunks(db_session, [chunk1], provider=mock_provider))
    assert res1["embedded_count"] == 1
    assert mock_provider.embed_batch.call_count == 1
    assert chunk1.embedding == sample_vec

    # Now embed chunk2 which shares the same content_hash
    res2 = asyncio.run(EmbeddingService.embed_new_chunks(db_session, [chunk2], provider=mock_provider))
    assert res2["reused_count"] == 1
    assert res2["embedded_count"] == 0
    # Provider should NOT have been called again!
    assert mock_provider.embed_batch.call_count == 1
    assert chunk2.embedding == sample_vec


# ---------------------------------------------------------------------------
# 7. Local Mode Configuration Without Cloud API Keys
# ---------------------------------------------------------------------------

def test_local_mode_configuration_without_cloud_api_keys(monkeypatch):
    """Verify local AI operates without OPENAI_API_KEY or LLM_API_KEY."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    llm = get_llm_provider()
    embed = get_embedding_provider()

    assert llm.is_configured is True
    assert embed.is_configured is True
    assert llm.provider_name == "ollama"
    assert embed.provider_name == "ollama"


# ---------------------------------------------------------------------------
# 8. Prevention of Mock Embeddings in Production Mode
# ---------------------------------------------------------------------------

def test_prevention_of_mock_embeddings_in_production(monkeypatch):
    """Verify that mock provider is never silently substituted when AI_PROVIDER is ollama."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "ollama")

    provider = get_embedding_provider()
    assert not isinstance(provider, MockEmbeddingProvider)
    assert isinstance(provider, OllamaEmbeddingProvider)


# ---------------------------------------------------------------------------
# 9. Correct Citation Preservation With Local LLM
# ---------------------------------------------------------------------------

def test_correct_citation_preservation(db_session: Session, monkeypatch):
    """Verify that local LLM execution preserves exact source coordinates in answer & database."""
    repo = Repository(name="cite-repo", full_name="acme/cite-repo")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="backend/core/router.py",
        code_symbol="init_routes",
        chunk_index=0,
        chunk_text="def init_routes(app):\n    # verified routing logic\n    pass",
        content_hash="router_hash_1",
        language="python",
        start_line=12,
        end_line=24,
    )
    db_session.add(chunk)
    db_session.commit()

    mock_llm_response = (
        "The routes are initialized in `backend/core/router.py` lines 12-24 via `init_routes`."
    )

    async def mock_post(*args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "model": "qwen2.5:3b",
            "message": {"role": "assistant", "content": mock_llm_response},
            "done": True,
        }
        return mock_resp

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    res = asyncio.run(AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Where is route initialization?",
    ))

    assert res["llm_configured"] is True
    assert res["answer"] == mock_llm_response
    assert len(res["citations"]) >= 1

    citation = res["citations"][0]
    assert citation["file_path"] == "backend/core/router.py"
    assert citation["symbol_name"] == "init_routes"
    assert citation["start_line"] == 12
    assert citation["end_line"] == 24


# ---------------------------------------------------------------------------
# 10. Indexing Failure Handling When Embedding Fails
# ---------------------------------------------------------------------------

def test_indexing_fails_when_embedding_fails(db_session: Session, monkeypatch):
    """Verify indexing pipeline cannot be marked COMPLETED when embedding stage fails."""
    repo = Repository(name="index-fail-repo", full_name="acme/index-fail-repo", status="pending")
    db_session.add(repo)
    db_session.commit()

    job = IndexingJob(
        repository_id=repo.id,
        commit_sha="abcd123",
        status="QUEUED",
        stage="QUEUED",
    )
    db_session.add(job)
    db_session.commit()

    # Force EmbeddingService.embed_new_chunks to return a failure
    async def mock_embed_fail(db, chunks):
        return {"success": False, "error": "Local Ollama connection failed during indexing"}

    monkeypatch.setattr("backend.app.services.indexing_service.EmbeddingService.embed_new_chunks", mock_embed_fail)

    asyncio.run(IndexingService.run_indexing_pipeline(
        job_id=job.id,
        repository_id=repo.id,
        branch="main",
        db_session=db_session,
    ))

    db_session.refresh(job)
    db_session.refresh(repo)

    assert job.status == "FAILED"
    assert job.stage == "EMBEDDING"
    assert "Local Ollama connection failed" in (job.error_message or "")
    assert repo.status == "failed"


# ---------------------------------------------------------------------------
# 11. Authorization and Cross-User Repository Isolation
# ---------------------------------------------------------------------------

def test_cross_user_repository_isolation(db_session: Session):
    """Verify users cannot perform hybrid retrieval on repositories owned by other users."""
    owner = User(email="owner@acme.com", full_name="Owner User", github_username="owner_user", is_active=True)
    intruder = User(email="intruder@acme.com", full_name="Intruder User", github_username="intruder_user", is_active=True)
    db_session.add_all([owner, intruder])
    db_session.commit()

    private_repo = Repository(
        name="private-vault",
        full_name="owner_user/private-vault",
        user_id=owner.id,
        is_private=True,
    )
    db_session.add(private_repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=private_repo.id,
        file_path="secret.py",
        chunk_index=0,
        chunk_text="SECRET_KEY = 'super_secret'",
        content_hash="secret_h",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    # Attempt retrieval as intruder
    results = asyncio.run(HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=private_repo.id,
        query="SECRET_KEY",
        user_id=intruder.id,
    ))

    # Intruder MUST get empty results due to cross-user isolation
    assert results == []

    # Owner retrieval succeeds
    owner_results = asyncio.run(HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=private_repo.id,
        query="SECRET_KEY",
        user_id=owner.id,
    ))
    assert len(owner_results) >= 1


# ---------------------------------------------------------------------------
# 12. Live Local Ollama Verification (Contacting Real Runtime)
# ---------------------------------------------------------------------------

def test_live_ollama_runtime_integration():
    """
    Live test against the actual local Ollama server running on the host machine.
    Explicitly labeled as LIVE integration test (not a unit mock).
    """
    ollama_url = settings.OLLAMA_BASE_URL.rstrip("/")
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{ollama_url}/api/tags")
    except Exception:
        pytest.skip(f"Live Ollama not accessible at {ollama_url}. Skipping live integration test.")

    if resp.status_code != 200:
        pytest.skip(f"Ollama returned HTTP {resp.status_code}. Skipping live test.")

    models_data = resp.json().get("models", [])
    model_names = [m.get("name", "") for m in models_data]

    # Verify nomic-embed-text presence and live 768 dimension
    embed_model = settings.EMBEDDING_MODEL
    has_embed = any(embed_model in name for name in model_names)
    assert has_embed, f"Live Ollama does not have embedding model '{embed_model}' downloaded."

    embed_provider = OllamaEmbeddingProvider(base_url=ollama_url, model=embed_model, dimension=768)
    live_vector = asyncio.run(embed_provider.embed_text("Live CodeMind verification vector"))
    assert len(live_vector) == 768, f"Expected 768 dimensions from {embed_model}, got {len(live_vector)}"

    # Verify qwen2.5:3b presence and live chat completion
    llm_model = settings.LLM_MODEL
    has_llm = any(llm_model in name for name in model_names)
    assert has_llm, f"Live Ollama does not have LLM model '{llm_model}' downloaded."

    llm_provider = OllamaLLMProvider(base_url=ollama_url, model=llm_model, timeout_seconds=30.0)
    live_answer = asyncio.run(llm_provider.generate_chat_response(
        [{"role": "user", "content": "Respond with the single word: OK"}]
    ))
    assert len(live_answer.strip()) > 0, "Live Ollama LLM returned empty response."
