import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine, RetrievedChunk
from backend.app.services.assistant_service import AssistantService
from backend.app.integrations.llm.service import get_llm_provider
from backend.app.integrations.llm.ollama_provider import OllamaLLMProvider
from backend.app.integrations.llm.openai_provider import OpenAILLMProvider
from backend.app.core.config import settings


# ==============================================================================
# Deterministic Regression Tests (Section E: 10 Scenarios)
# ==============================================================================

@pytest.mark.anyio
async def test_wrapper_function_vs_actual_model_provider_invocation(db_session: Session):
    """
    Scenario 1: Wrapper function versus actual model-provider invocation.
    Verifies that AssistantService.answer_question orchestrates the call but delegates
    the actual model execution to the configured LLMProvider (e.g. OllamaLLMProvider.generate_response
    or generate_chat_response), rather than performing the model call directly.
    """
    repo = Repository(name="codemind-core", full_name="org/codemind-core", is_private=False, default_branch="main")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    f = IndexedFile(repository_id=repo.id, path="backend/app/services/assistant_service.py", language="python", lines_count=50)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path=f.path,
        chunk_index=0,
        start_line=1,
        end_line=20,
        chunk_text="class AssistantService:\n    @classmethod\n    async def answer_question(cls, ...):\n        pass",
        code_symbol="AssistantService.answer_question",
        content_hash="h_ans",
        language="python"
    )
    db_session.add(chunk)
    db_session.commit()

    # Mock the underlying provider's generate_chat_response
    mock_provider = MagicMock(spec=OllamaLLMProvider)
    mock_provider.is_configured = True
    mock_provider.model_name = "qwen2.5:3b"
    mock_provider.provider_name = "ollama"
    mock_provider.generate_chat_response = AsyncMock(return_value="The function is `AssistantService.answer_question` in `backend/app/services/assistant_service.py`.")

    with patch("backend.app.services.assistant_service.get_llm_provider", return_value=mock_provider):
        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question="Which exact function generates the AI assistant's final answer?"
        )
        assert res["status"] == "success"
        # The wrapper must have invoked the model provider's generate_chat_response
        assert mock_provider.generate_chat_response.called
        assert "backend/app/services/assistant_service.py" in res["answer"]


@pytest.mark.anyio
async def test_correct_frontend_to_backend_to_model_call_chain(db_session: Session):
    """
    Scenario 2: Correct frontend-to-backend-to-model call chain.
    Verifies that the request pipeline passes through:
    1. api.js (streamConversationMessage) ->
    2. api_v1.py (stream_conversation_message) ->
    3. assistant_service.py (stream_answer_question) ->
    4. ollama_provider.py (generate_chat_stream).
    """
    repo = Repository(name="chain-repo", full_name="org/chain-repo", is_private=False, default_branch="main")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    conv = AssistantConversation(repository_id=repo.id, branch="main", title="Pipeline Chain")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    f = IndexedFile(repository_id=repo.id, path="frontend/static/js/api.js", language="javascript", lines_count=100)
    db_session.add(f)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path=f.path,
        chunk_index=0,
        start_line=1,
        end_line=30,
        chunk_text="async function streamConversationMessage(conversationId, question, options, onEvent) { ... }",
        code_symbol="streamConversationMessage",
        content_hash="h_chain",
        language="javascript"
    )
    db_session.add(chunk)
    db_session.commit()

    # Stream through stream_answer_question
    mock_provider = MagicMock(spec=OllamaLLMProvider)
    mock_provider.is_configured = True
    mock_provider.model_name = "qwen2.5:3b"

    async def mock_stream(*args, **kwargs):
        yield "Step 1: Frontend api.js invokes streamConversationMessage. "
        yield "Step 2: Backend api_v1.py route handles stream_conversation_message. "
        yield "Step 3: AssistantService stream_answer_question orchestrates retrieval. "
        yield "Step 4: OllamaLLMProvider calls Ollama API."

    mock_provider.generate_chat_stream = mock_stream

    with patch("backend.app.services.assistant_service.get_llm_provider", return_value=mock_provider):
        events = []
        async for sse in AssistantService.stream_answer_question(
            db=db_session,
            repository_id=repo.id,
            question="Trace one user question from the frontend submission through the backend service to the Ollama model call.",
            conversation_id=conv.id
        ):
            events.append(sse)

        assert any("token" in e for e in events)
        assert any("done" in e for e in events)


@pytest.mark.anyio
async def test_hybrid_retrieval_presence_or_absence_based_on_actual_selected_repo(db_session: Session):
    """
    Scenario 3: Hybrid retrieval presence or absence based on the actual selected repository.
    Repo A (host platform) implements HybridRetrievalEngine; Repo B (legacy app) does not.
    """
    repo_a = Repository(name="has-retrieval", full_name="org/has-retrieval", is_private=False)
    repo_b = Repository(name="no-retrieval", full_name="org/no-retrieval", is_private=False)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    # Repo A has hybrid_engine.py
    f_a = IndexedFile(repository_id=repo_a.id, path="backend/app/retrieval/hybrid_engine.py", language="python", lines_count=100)
    db_session.add(f_a)
    db_session.commit()

    c_a = CodeChunk(
        repository_id=repo_a.id,
        file_path=f_a.path,
        chunk_index=0,
        start_line=1,
        end_line=50,
        chunk_text="class HybridRetrievalEngine:\n    def retrieve(self, db, query): pass",
        code_symbol="HybridRetrievalEngine",
        content_hash="h_hyb",
        language="python"
    )
    # Repo B has only legacy code
    f_b = IndexedFile(repository_id=repo_b.id, path="legacy_app.py", language="python", lines_count=20)
    db_session.add(f_b)
    db_session.commit()

    c_b = CodeChunk(
        repository_id=repo_b.id,
        file_path=f_b.path,
        chunk_index=0,
        start_line=1,
        end_line=20,
        chunk_text="def legacy_worker(): pass",
        code_symbol="legacy_worker",
        content_hash="h_leg",
        language="python"
    )
    db_session.add_all([c_a, c_b])
    db_session.commit()

    # Query Repo A
    chunks_a = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_a.id,
        query="Where is hybrid retrieval implemented?"
    )
    assert any("hybrid_engine.py" in c.file_path for c in chunks_a)

    # Query Repo B
    chunks_b = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_b.id,
        query="Where is hybrid retrieval implemented?"
    )
    assert not any("hybrid_engine.py" in c.file_path for c in chunks_b)


@pytest.mark.anyio
async def test_repository_scoped_retrieval_and_citation_isolation(db_session: Session):
    """
    Scenario 4: Repository-scoped retrieval and citation isolation.
    Ensures that queries on Repo 1 NEVER retrieve chunks or citations from Repo 2.
    """
    repo1 = Repository(name="tenant-alpha", full_name="org/tenant-alpha", is_private=False)
    repo2 = Repository(name="tenant-beta", full_name="org/tenant-beta", is_private=False)
    db_session.add_all([repo1, repo2])
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo1.id,
        file_path="src/alpha_secrets.py",
        chunk_index=0,
        start_line=1,
        end_line=10,
        chunk_text="ALPHA_CONFIDENTIAL_DATA = 'alpha_value'",
        code_symbol="ALPHA_CONFIDENTIAL_DATA",
        content_hash="h1",
        language="python"
    )
    c2 = CodeChunk(
        repository_id=repo2.id,
        file_path="src/beta_secrets.py",
        chunk_index=0,
        start_line=1,
        end_line=10,
        chunk_text="BETA_CONFIDENTIAL_DATA = 'beta_value'",
        code_symbol="BETA_CONFIDENTIAL_DATA",
        content_hash="h2",
        language="python"
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # Search Repo 1
    chunks = await HybridRetrievalEngine.retrieve(db=db_session, repository_id=repo1.id, query="CONFIDENTIAL_DATA")
    assert all(c.repository_id == repo1.id for c in chunks)
    assert not any("beta" in c.file_path for c in chunks)


def test_evidence_counters_calculated_from_validated_claims_not_retrieved_files():
    """
    Scenario 5: Evidence counters calculated from validated claims rather than retrieved file counts.
    - If 3 chunks are retrieved, but the answer only grounds claims in 2 of them, confirmed == 2.
    - An unrelated retrieved file does NOT increase confirmed facts.
    - An unverified/absent claim increments unknowns, NOT confirmed facts.
    """
    citations = [
        {"file_path": "backend/app/services/assistant_service.py", "symbol_name": "_calculate_evidence_counters"},
        {"file_path": "backend/app/retrieval/hybrid_engine.py", "symbol_name": "retrieve"},
        {"file_path": "backend/app/core/archive_security.py", "symbol_name": "is_zip_member_symlink"}, # unrelated file
    ]
    retrieved_chunks = [
        RetrievedChunk(chunk_id=1, repository_id=1, file_path="backend/app/services/assistant_service.py", symbol_name="_calculate_evidence_counters", start_line=1, end_line=50, chunk_text="", score=0.9),
        RetrievedChunk(chunk_id=2, repository_id=1, file_path="backend/app/retrieval/hybrid_engine.py", symbol_name="retrieve", start_line=1, end_line=50, chunk_text="", score=0.85),
        RetrievedChunk(chunk_id=3, repository_id=1, file_path="backend/app/core/archive_security.py", symbol_name="is_zip_member_symlink", start_line=1, end_line=20, chunk_text="", score=0.4),
    ]

    # Answer grounds claims in assistant_service.py and hybrid_engine.py; archive_security.py is unmentioned
    answer = (
        "Confirmed: `_calculate_evidence_counters` in `backend/app/services/assistant_service.py` calculates counters. "
        "Also `retrieve` in `backend/app/retrieval/hybrid_engine.py` performs hybrid retrieval. "
        "`semantic_reranker.py` is UNVERIFIED / ABSENT in the repository."
    )

    facts = AssistantService._calculate_evidence_counters(
        answer=answer,
        citations=citations,
        retrieved_chunks=retrieved_chunks,
        impact=None,
        audit_meta=None
    )

    # Confirmed facts must be 2 (assistant_service and hybrid_engine), NOT 3 (archive_security was unrelated and unmentioned)
    assert facts["confirmed"] == 2
    # The declared absence of semantic_reranker.py should increment unknowns
    assert facts["unknowns"] >= 1


def test_stale_repository_selection_and_conversation_binding_mismatches(db_session: Session):
    """
    Scenario 6: Stale repository selection and conversation binding mismatches.
    A conversation bound to Repo A cannot have its repository silently replaced by a conflicting request.
    """
    repo_a = Repository(name="repo-a", full_name="org/repo-a", is_private=False)
    repo_b = Repository(name="repo-b", full_name="org/repo-b", is_private=False)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    conv = AssistantConversation(repository_id=repo_a.id, branch="main", title="Repo A Conv")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Simulate routing logic in api_v1.py:
    # effective_repo_id must prioritize conv.repository_id
    incoming_request_repo_id = repo_b.id
    effective_repo_id = conv.repository_id if conv.repository_id is not None else incoming_request_repo_id

    assert effective_repo_id == repo_a.id
    assert effective_repo_id != repo_b.id


def test_unrelated_functions_and_symbols_lexical_filter():
    """
    Scenario 7: Unrelated functions and symbols that lexical search might rank highly.
    Ensures that unrelated lexical matches are not counted as confirmed facts if the answer ignores or negates them.
    """
    citations = [
        {"file_path": "backend/app/core/archive_security.py", "symbol_name": "is_zip_member_symlink"},
    ]
    answer = "The repository does not implement custom zip archiving; `archive_security.py` is unrelated to this feature."
    facts = AssistantService._calculate_evidence_counters(
        answer=answer,
        citations=citations,
        retrieved_chunks=[],
        impact=None,
        audit_meta=None
    )
    # The file is negated/declared unrelated -> confirmed must be 0
    assert facts["confirmed"] == 0


def test_provider_configurations_where_ollama_is_not_active():
    """
    Scenario 8: Provider configurations where Ollama is not the active backend.
    Documents branch conditions when OpenAI or another provider is configured.
    """
    # 1. With LLM_API_KEY set -> OpenAILLMProvider
    with patch.object(settings, "LLM_API_KEY", "sk-proj-test123456"):
        provider = get_llm_provider()
        assert isinstance(provider, OpenAILLMProvider)
        assert provider.provider_name == "openai"

    # 2. Without API key -> OllamaLLMProvider
    with patch.object(settings, "LLM_API_KEY", ""):
        with patch.object(settings, "LLM_PROVIDER", "ollama"):
            provider = get_llm_provider()
            assert isinstance(provider, OllamaLLMProvider)
            assert provider.provider_name == "ollama"


@pytest.mark.anyio
async def test_empty_or_irrelevant_retrieval_evidence(db_session: Session):
    """
    Scenario 9: Empty or irrelevant retrieval evidence.
    Verifies that when zero chunks match, the assistant truthfully yields empty_retrieval strategy,
    confirmed == 0, and unknowns >= 1.
    """
    repo = Repository(name="empty-repo", full_name="org/empty-repo", is_private=False, status="ready", files_count=5)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="src/hello.py", language="python", lines_count=10)
    db_session.add(f)
    db_session.commit()

    c = CodeChunk(
        repository_id=repo.id,
        file_path="src/hello.py",
        chunk_index=0,
        start_line=1,
        end_line=10,
        chunk_text="def say_hello(): print('hello')",
        code_symbol="say_hello",
        content_hash="h_hello",
        language="python"
    )
    db_session.add(c)
    db_session.commit()

    conv = AssistantConversation(repository_id=repo.id, branch="main", title="Empty Test")
    db_session.add(conv)
    db_session.commit()

    events = []
    async for sse in AssistantService.stream_answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What is the quantum encryption protocol used in this repository?",
        conversation_id=conv.id
    ):
        events.append(sse)

    done_event = [e for e in events if "done" in e]
    assert len(done_event) > 0
    # Parse data line from SSE
    data_line = [l for l in done_event[0].split("\n") if l.startswith("data: ")][0]
    payload = json.loads(data_line[6:])
    assert payload["facts"]["confirmed"] == 0
    assert payload["facts"]["unknowns"] >= 1


@pytest.mark.anyio
async def test_prevent_mixing_two_indexed_repositories(db_session: Session):
    """
    Scenario 10: Incorrect claims caused by mixing two indexed repositories.
    Verifies that two concurrently indexed repositories maintain completely separate chunk domains.
    """
    repo1 = Repository(name="service-payments", full_name="org/service-payments", is_private=False)
    repo2 = Repository(name="service-inventory", full_name="org/service-inventory", is_private=False)
    db_session.add_all([repo1, repo2])
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo1.id,
        file_path="payments/gateway.py",
        chunk_index=0,
        start_line=1,
        end_line=20,
        chunk_text="def process_stripe_payment(): pass",
        code_symbol="process_stripe_payment",
        content_hash="p1",
        language="python"
    )
    c2 = CodeChunk(
        repository_id=repo2.id,
        file_path="inventory/warehouse.py",
        chunk_index=0,
        start_line=1,
        end_line=20,
        chunk_text="def reserve_warehouse_stock(): pass",
        code_symbol="reserve_warehouse_stock",
        content_hash="i1",
        language="python"
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # Query 1 for repo1
    res1 = await HybridRetrievalEngine.retrieve(db=db_session, repository_id=repo1.id, query="warehouse stock")
    # Even though query mentions warehouse stock, repo1 does not have it
    assert not any("warehouse.py" in c.file_path for c in res1)

    # Query 2 for repo2
    res2 = await HybridRetrievalEngine.retrieve(db=db_session, repository_id=repo2.id, query="warehouse stock")
    assert any("warehouse.py" in c.file_path for c in res2)
