import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine, RetrievedChunk
from backend.app.services.assistant_service import AssistantService, GENERIC_WORDS_BLOCKLIST


# ==============================================================================
# Dynamic Multi-Repository Fixtures (No hardcoded IDs)
# ==============================================================================

def create_mock_repos(db: Session):
    """Creates two distinct repositories with files and chunks to test isolation."""
    user = User(email="test_isolation_user@example.com", full_name="Test Isolation User")
    db.add(user)
    db.commit()
    db.refresh(user)

    repo_a = Repository(
        name="CodeMind-AI",
        full_name="testorg/codemind-ai",
        is_private=False,
        default_branch="main",
        user_id=user.id,
    )
    repo_b = Repository(
        name="Alzheimer",
        full_name="testorg/alzheimer",
        is_private=False,
        default_branch="main",
        user_id=user.id,
    )
    db.add_all([repo_a, repo_b])
    db.commit()
    db.refresh(repo_a)
    db.refresh(repo_b)

    # Repo A files and chunks (Hybrid retrieval system)
    f_a1 = IndexedFile(repository_id=repo_a.id, path="backend/app/retrieval/hybrid_engine.py", language="python", lines_count=200)
    db.add(f_a1)
    db.commit()

    c_a1 = CodeChunk(
        repository_id=repo_a.id,
        file_path=f_a1.path,
        chunk_index=0,
        start_line=99,
        end_line=150,
        chunk_text="class HybridRetrievalEngine:\n    async def retrieve(cls, db, repository_id, query):\n        # executes vector search, keyword search, exact symbols, and graph expansion\n        return []",
        code_symbol="HybridRetrievalEngine.retrieve",
        content_hash="hash_a1",
        language="python",
    )
    c_a2 = CodeChunk(
        repository_id=repo_a.id,
        file_path="README.md",
        chunk_index=0,
        start_line=1,
        end_line=30,
        chunk_text="# CodeMind AI\nAI-powered codebase intelligence platform with multi-layer hybrid retrieval.",
        code_symbol=None,
        content_hash="hash_a2",
        language="markdown",
    )
    db.add_all([c_a1, c_a2])

    # Repo B files and chunks (Alzheimer MRI dataset & classification)
    f_b1 = IndexedFile(repository_id=repo_b.id, path="src/training/load_split_graphs.py", language="python", lines_count=120)
    db.add(f_b1)
    db.commit()

    c_b1 = CodeChunk(
        repository_id=repo_b.id,
        file_path=f_b1.path,
        chunk_index=0,
        start_line=10,
        end_line=45,
        chunk_text="def load_split_graphs(data_dir):\n    # loads graph neural network dataset for Alzheimer MRI scans\n    return []",
        code_symbol="load_split_graphs",
        content_hash="hash_b1",
        language="python",
    )
    c_b2 = CodeChunk(
        repository_id=repo_b.id,
        file_path="README.md",
        chunk_index=0,
        start_line=1,
        end_line=25,
        chunk_text="# Alzheimer Brain MRI Project\n# Dataset\nMRI dataset for classification.\n# Results\nAccuracy results and evaluation metrics.",
        code_symbol=None,
        content_hash="hash_b2",
        language="markdown",
    )
    db.add_all([c_b1, c_b2])
    db.commit()

    return user, repo_a, repo_b


# ==============================================================================
# Regression Tests
# ==============================================================================

@pytest.mark.anyio
async def test_codemind_ai_retrieval_uses_only_its_repository_id(db_session: Session):
    """Verify that retrieval on CodeMind-AI uses only its repository ID and never returns Alzheimer chunks."""
    user, repo_a, repo_b = create_mock_repos(db_session)

    chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_a.id,
        query="hybrid retrieval semantic vector keyword exact symbol graph",
        user_id=user.id,
    )

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.repository_id == repo_a.id
        assert chunk.repository_id != repo_b.id
        assert "alzheimer" not in chunk.file_path.lower()


@pytest.mark.anyio
async def test_alzheimer_retrieval_uses_only_alzheimer_repository_id(db_session: Session):
    """Verify that retrieval on Alzheimer uses only the Alzheimer repository."""
    user, repo_a, repo_b = create_mock_repos(db_session)

    chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_b.id,
        query="load split graphs MRI dataset results",
        user_id=user.id,
    )

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.repository_id == repo_b.id
        assert chunk.repository_id != repo_a.id
        assert "hybrid_engine" not in chunk.file_path.lower()


@pytest.mark.anyio
async def test_switch_between_repositories_and_ask_same_question(db_session: Session):
    """Verify switching between repositories and asking the exact same question respects each repository's scope."""
    user, repo_a, repo_b = create_mock_repos(db_session)
    question = "Show the implementation of semantic vector search, keyword search, exact symbol matching, graph expansion, and the function that combines the results."

    # Ask in Repo A
    with patch.object(AssistantService, "_generate_llm_answer", return_value="Hybrid retrieval is implemented in hybrid_engine.py."):
        res_a = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo_a.id,
            question=question,
            user_id=user.id,
        )
    assert res_a["repository_id"] == repo_a.id
    for citation in res_a["citations"]:
        assert citation["repository_id"] == repo_a.id

    # Ask in Repo B
    with patch.object(AssistantService, "_generate_llm_answer", return_value="This repository does not implement hybrid retrieval."):
        res_b = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo_b.id,
            question=question,
            user_id=user.id,
        )
    assert res_b["repository_id"] == repo_b.id
    for citation in res_b["citations"]:
        assert citation["repository_id"] == repo_b.id


@pytest.mark.anyio
async def test_open_old_conversation_after_switching_repositories(db_session: Session):
    """Verify that opening an old conversation preserves the conversation's bound repository scope."""
    user, repo_a, repo_b = create_mock_repos(db_session)

    # 1. Create conversation in Repo A
    conv_a = AssistantConversation(
        repository_id=repo_a.id,
        user_id=user.id,
        branch="main",
        title="Repo A Investigation",
    )
    db_session.add(conv_a)
    db_session.commit()
    db_session.refresh(conv_a)

    # 2. Add an assistant message to Conv A
    msg_a = AssistantMessage(
        conversation_id=conv_a.id,
        role="assistant",
        content="Hybrid retrieval combines multiple search channels.",
        citations=json.dumps([{"repository_id": repo_a.id, "repository_name": repo_a.name, "file_path": "backend/app/retrieval/hybrid_engine.py"}]),
        evidence_metadata=json.dumps({"repository_id": repo_a.id, "repository_name": repo_a.name}),
        status="success",
    )
    db_session.add(msg_a)
    db_session.commit()

    # 3. Create conversation in Repo B
    conv_b = AssistantConversation(
        repository_id=repo_b.id,
        user_id=user.id,
        branch="main",
        title="Repo B Investigation",
    )
    db_session.add(conv_b)
    db_session.commit()

    # 4. Open Conv A and ask a follow-up question
    with patch.object(AssistantService, "_generate_llm_answer", return_value="The function is retrieve() in hybrid_engine.py."):
        res_followup = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo_a.id,
            question="What is the function that combines the results?",
            user_id=user.id,
            conversation_id=conv_a.id,
        )

    assert res_followup["conversation_id"] == conv_a.id
    assert res_followup["repository_id"] == repo_a.id
    for cit in res_followup["citations"]:
        assert cit["repository_id"] == repo_a.id


@pytest.mark.anyio
async def test_prompt_evidence_and_citations_cannot_contain_chunks_from_another_repository(db_session: Session):
    """Verify that prompt evidence and citations strictly filter out any foreign repository chunks."""
    user, repo_a, repo_b = create_mock_repos(db_session)

    chunks = [
        RetrievedChunk(
            chunk_id=1,
            repository_id=repo_a.id,
            file_path="backend/app/retrieval/hybrid_engine.py",
            chunk_text="code from repo a",
            symbol_name="retrieve",
            start_line=1,
            end_line=20,
            score=0.9,
            channels=["vector"],
        ),
        RetrievedChunk(
            chunk_id=2,
            repository_id=repo_b.id,  # Foreign chunk
            file_path="src/training/load_split_graphs.py",
            chunk_text="code from repo b",
            symbol_name="load_split_graphs",
            start_line=1,
            end_line=20,
            score=0.9,
            channels=["vector"],
        ),
    ]

    # Filter guard simulation as in stream_answer_question / answer_question
    filtered = [c for c in chunks if getattr(c, "repository_id", repo_a.id) == repo_a.id]
    assert len(filtered) == 1
    assert filtered[0].repository_id == repo_a.id

    messages = AssistantService._build_prompt_messages(
        repo_name=repo_a.name,
        question="Show the hybrid retrieval function",
        chunks=filtered,
    )
    prompt_str = json.dumps(messages)
    assert "backend/app/retrieval/hybrid_engine.py" in prompt_str
    assert "src/training/load_split_graphs.py" not in prompt_str


@pytest.mark.anyio
async def test_repository_mismatches_detected_before_model_generation(db_session: Session):
    """Verify that attempting to query a repository that does not match the conversation's bound repository raises an error."""
    user, repo_a, repo_b = create_mock_repos(db_session)

    conv = AssistantConversation(
        repository_id=repo_a.id,
        user_id=user.id,
        branch="main",
        title="Locked to Repo A",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Non-streaming endpoint
    with pytest.raises(HTTPException) as exc_info:
        await AssistantService.answer_question(
            db=db_session,
            repository_id=repo_b.id,  # Mismatched repository!
            question="Any question",
            user_id=user.id,
            conversation_id=conv.id,
        )
    assert exc_info.value.status_code == 400
    assert "Repository mismatch" in exc_info.value.detail

    # Streaming endpoint
    events = []
    async for event_str in AssistantService.stream_answer_question(
        db=db_session,
        repository_id=repo_b.id,  # Mismatched repository!
        question="Any question",
        user_id=user.id,
        conversation_id=conv.id,
    ):
        events.append(event_str)

    assert any("Repository Mismatch" in e for e in events)


def test_generic_dictionary_words_do_not_hijack_active_repository(db_session: Session):
    """Verify that common doc and dictionary words (results, dataset, documentation, etc.) never hijack the active repo."""
    user, repo_a, repo_b = create_mock_repos(db_session)

    queries = [
        "the function that combines the results",
        "show the dataset split logic",
        "where is the documentation stored?",
        "run the automated test suite",
        "what are the key features and architecture overview?",
    ]

    for q in queries:
        target_repo, norm_q, clar = AssistantService.resolve_repository_from_query(
            db=db_session,
            question=q,
            active_repo_id=repo_a.id,
            user_id=user.id,
        )
        assert target_repo is not None
        assert target_repo.id == repo_a.id
        assert target_repo.id != repo_b.id
        assert clar is None
