"""
test_answer_quality_evaluation.py

Production-Grade AI Chat Accuracy, Reasoning & Response Quality Evaluation Suite.
Validates the 8 core evaluation dimensions:
1. Intent Understanding
2. Factual Correctness
3. Evidence Relevance
4. Completeness
5. Technical Explanation Quality
6. Citation Accuracy
7. Conversation Continuity
8. Repository Isolation
"""

import pytest
from sqlalchemy.orm import Session
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation
from backend.app.services.assistant_service import AssistantService


@pytest.mark.anyio
async def test_general_programming_intent_and_zero_citations(db_session: Session):
    """Verifies that general programming questions have 0 repository citations and clear explanations."""
    repo = Repository(name="dummy-repo", full_name="acme/dummy-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    questions = [
        "Explain the difference between synchronous and asynchronous programming with practical Python examples.",
        "Debug a supplied code snippet and explain the root cause.",
        "Explain a technical concept with an example without forcing repository-specific citations."
    ]

    for q in questions:
        intents = AssistantService.classify_query_intent(q)
        assert "GENERAL_PROGRAMMING" in intents, f"Failed for query: {q}"

        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question=q
        )
        assert len(res["citations"]) == 0, f"Expected 0 citations for general programming, got: {res['citations']}"
        assert len(res["answer"]) > 50


@pytest.mark.anyio
async def test_persistence_and_reboot_intents():
    """Verifies intent classification for storage, reboot, and follow-up failure questions."""
    q_store = "Where is the location data stored, and how is it updated?"
    intents_store = AssistantService.classify_query_intent(q_store)
    assert "PERSISTENCE_AND_STORAGE" in intents_store
    assert "DATABASE_MODELS" in intents_store

    q_boot = "Explain how the application handles background tracking after a device reboot, if implemented."
    intents_boot = AssistantService.classify_query_intent(q_boot)
    assert "BACKGROUND_AND_LIFECYCLE" in intents_boot
    assert "ERROR_AND_JOBS" in intents_boot

    q_fail = "What happens if that function fails?"
    intents_fail = AssistantService.classify_query_intent(q_fail)
    assert "ERROR_HANDLING" in intents_fail


@pytest.mark.anyio
async def test_multi_turn_continuity_and_repo_isolation(db_session: Session):
    """Verifies conversation history continuity and strict repository isolation on switch."""
    repo_cm = Repository(name="CodeMind-AI", full_name="acme/CodeMind-AI", is_private=False)
    repo_fc = Repository(name="FinCell", full_name="acme/FinCell", is_private=False)
    db_session.add_all([repo_cm, repo_fc])
    db_session.commit()

    # Seed auth chunk for CodeMind
    f_auth = IndexedFile(repository_id=repo_cm.id, path="backend/app/api/routes/api_v1.py", lines_count=120)
    db_session.add(f_auth)
    db_session.commit()
    chunk_auth = CodeChunk(
        repository_id=repo_cm.id,
        file_id=f_auth.id,
        file_path=f_auth.path,
        code_symbol="get_current_user_record",
        chunk_index=0,
        chunk_text="def get_current_user_record(request: Request):\n    if not token:\n        raise HTTPException(status_code=401, detail='Authentication required')\n    return user",
        content_hash="hash_auth",
        language="python",
        start_line=74,
        end_line=122
    )
    # Seed flutter chunk for FinCell
    f_fc = IndexedFile(repository_id=repo_fc.id, path="lib/main.dart", lines_count=50)
    db_session.add(f_fc)
    db_session.commit()
    chunk_fc = CodeChunk(
        repository_id=repo_fc.id,
        file_id=f_fc.id,
        file_path=f_fc.path,
        code_symbol="FinCellApp",
        chunk_index=0,
        chunk_text="void main() => runApp(FinCellApp());\nclass FinCellApp extends StatelessWidget {}",
        content_hash="hash_fc",
        language="dart",
        start_line=1,
        end_line=30
    )
    db_session.add_all([chunk_auth, chunk_fc])
    db_session.commit()

    conv = AssistantConversation(
        title="Multi-turn Test",
        repository_id=repo_cm.id,
        user_id=None
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Turn 1: Which function validates the token?
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_cm.id,
        conversation_id=conv.id,
        question="Which function validates the token?",
        user_id=None
    )
    assert len(res1["citations"]) > 0
    assert any("api_v1.py" in c["file_path"] for c in res1["citations"])

    # Turn 2: What happens if that function fails?
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_cm.id,
        conversation_id=conv.id,
        question="What happens if that function fails?",
        user_id=None
    )
    assert "401" in res2["answer"] or "Unauthorized" in res2["answer"] or "HTTPException" in res2["answer"] or "Authentication required" in res2["answer"]

    # Turn 3: Switch to FinCell
    res3 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_fc.id,
        conversation_id=conv.id,
        question="Explain the architecture of FinCell.",
        user_id=None
    )
    # Must NOT contain CodeMind files in citations
    leaked = [c for c in res3["citations"] if "backend/app" in c.get("file_path", "")]
    assert len(leaked) == 0, f"Repository isolation violated! Leaked citations: {leaked}"
    assert "main.dart" in [c.get("file_path", "") for c in res3["citations"]] or "fincell" in res3["answer"].lower() or "flutter" in res3["answer"].lower()
