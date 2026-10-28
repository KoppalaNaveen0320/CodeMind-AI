import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService


def _get_or_create_user(db: Session) -> User:
    user = db.query(User).filter(User.is_active == True).first()
    if not user:
        user = User(
            email="tester@codemind.dev",
            full_name="CodeMind Tester",
            workspace_name="CodeMind",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def parse_sse_events(raw_text: str):
    events = []
    lines = raw_text.strip().split("\n")
    current_event = None
    current_data = []

    for line in lines:
        line = line.strip("\r")
        if not line:
            if current_event and current_data:
                data_str = "\n".join(current_data)
                try:
                    parsed_json = json.loads(data_str)
                except Exception:
                    parsed_json = data_str
                events.append((current_event, parsed_json))
            current_event = None
            current_data = []
        elif line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            current_data.append(line[len("data: "):])

    if current_event and current_data:
        data_str = "\n".join(current_data)
        try:
            parsed_json = json.loads(data_str)
        except Exception:
            parsed_json = data_str
        events.append((current_event, parsed_json))

    return events


# ==============================================================================
# Issue 1: AI Assistant Loading UI, SSE Streaming, Token Increments & Cancellation
# ==============================================================================

def test_sse_stream_status_progression_and_incremental_tokens(client: TestClient, db_session: Session, monkeypatch):
    """
    Verify backend SSE stream emits structured status events:
    1. meta event (conversation ID, repo ID)
    2. status event (stage="retrieving") -> frontend maps to "Searching your codebase..."
    3. citation event -> frontend updates verified sources
    4. status event (stage="generating") -> frontend maps to "Writing your answer..."
    5. token events -> incremental rendering
    6. done event -> completion and stats
    """
    user = _get_or_create_user(db_session)
    repo = Repository(name="stream-repo", full_name="codemind/stream-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/router.py",
        code_symbol="dispatch_request",
        chunk_index=0,
        chunk_text="def dispatch_request(req):\n    return execute(req)\n",
        content_hash="stream_h1",
        language="python",
        start_line=10,
        end_line=20,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="SSE Progression Test")
    db_session.add(conv)
    db_session.commit()

    tokens_to_yield = ["The ", "dispatch_request ", "routes ", "the ", "HTTP ", "call."]

    class MockStreamingProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            for t in tokens_to_yield:
                yield t

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: MockStreamingProvider()
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "How does dispatch work?", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    event_names = [e[0] for e in events]

    assert "meta" in event_names
    assert "status" in event_names
    assert "token" in event_names
    assert "done" in event_names

    statuses = [e[1].get("stage") for e in events if e[0] == "status"]
    assert "retrieving" in statuses
    assert "generating" in statuses

    tokens = [e[1]["token"] for e in events if e[0] == "token"]
    assert tokens == tokens_to_yield
    assert "".join(tokens) == "The dispatch_request routes the HTTP call."

    done_event = [e[1] for e in events if e[0] == "done"][0]
    assert done_event["status"] == "success"
    assert done_event["answer"] == "The dispatch_request routes the HTTP call."


def test_sse_stream_failure_emits_error_event(client: TestClient, db_session: Session, monkeypatch):
    """Verify stream handles LLM failure by emitting an SSE error event without leaving chat blank."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="err-repo", full_name="codemind/err-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/service.py",
        code_symbol="do_work",
        chunk_index=0,
        chunk_text="def do_work(): pass\n",
        content_hash="err_h1",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="SSE Error Test")
    db_session.add(conv)
    db_session.commit()

    class FailingProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            raise RuntimeError("Ollama connection failed")
            yield "never"

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: FailingProvider()
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "How does do_work work?", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    error_events = [e[1] for e in events if e[0] == "error"]
    assert len(error_events) >= 1
    assert "Ollama connection failed" in error_events[0].get("message", "")


# ==============================================================================
# Issue 2: Fast Conversation History Retrieval & Isolation
# ==============================================================================

def test_get_conversation_history_does_not_invoke_llm_or_embeddings(client: TestClient, db_session: Session, monkeypatch):
    """
    Verify fetching persisted conversation history retrieves messages directly from PostgreSQL
    without calling any LLM generation, Ollama, or embedding engine.
    """
    user = _get_or_create_user(db_session)
    conv = AssistantConversation(user_id=user.id, title="Fast History Test")
    db_session.add(conv)
    db_session.commit()

    msg1 = AssistantMessage(conversation_id=conv.id, role="user", content="Question 1")
    msg2 = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content="Answer 1",
        citations='[{"file_path": "a.py", "start_line": 1, "end_line": 5}]'
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()

    llm_called = False
    embedding_called = False

    def mock_llm(*args, **kwargs):
        nonlocal llm_called
        llm_called = True
        raise AssertionError("LLM should not be called when retrieving conversation history!")

    def mock_embedding(*args, **kwargs):
        nonlocal embedding_called
        embedding_called = True
        raise AssertionError("Embedding engine should not be called when retrieving conversation history!")

    monkeypatch.setattr("backend.app.services.assistant_service.AssistantService._generate_llm_answer", mock_llm)
    monkeypatch.setattr("backend.app.retrieval.hybrid_engine.HybridRetrievalEngine.retrieve", mock_embedding)

    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == conv.id
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Question 1"
    assert data["messages"][1]["content"] == "Answer 1"
    assert len(data["messages"][1]["citations"]) == 1

    assert not llm_called, "LLM was unexpectedly invoked during history retrieval"
    assert not embedding_called, "Embedding retrieval was unexpectedly invoked during history retrieval"


def test_messages_strictly_chronological_with_stable_ids(client: TestClient, db_session: Session):
    """Verify conversation messages are returned strictly in ascending chronological order."""
    user = _get_or_create_user(db_session)
    conv = AssistantConversation(user_id=user.id, title="Chronological Order Test")
    db_session.add(conv)
    db_session.commit()

    created_messages = []
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        m = AssistantMessage(conversation_id=conv.id, role=role, content=f"Message step {i}")
        db_session.add(m)
        created_messages.append(m)
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    msgs = res.json()["messages"]
    assert len(msgs) == 10

    for idx, msg in enumerate(msgs):
        assert msg["content"] == f"Message step {idx}"
        assert msg["id"] == created_messages[idx].id
        if idx > 0:
            assert msg["id"] > msgs[idx - 1]["id"]


def test_empty_conversation_returns_empty_messages(client: TestClient, db_session: Session):
    """Verify an empty conversation returns 200 with an empty message array quickly."""
    user = _get_or_create_user(db_session)
    conv = AssistantConversation(user_id=user.id, title="Empty Discussion")
    db_session.add(conv)
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == conv.id
    assert data["messages"] == []


def test_conversation_authorization_and_ownership(client: TestClient, db_session: Session):
    """Verify users cannot view or delete conversations belonging to other users (workspace isolation)."""
    user = _get_or_create_user(db_session)
    other = User(email="other_isolated@user.dev", full_name="Other User Isolated", is_active=False)
    db_session.add(other)
    db_session.commit()

    other_conv = AssistantConversation(user_id=other.id, title="User Other Secret Conversation")
    db_session.add(other_conv)
    db_session.commit()

    # Active user attempts to view other's conversation
    res = client.get(f"/api/v1/assistant/conversations/{other_conv.id}")
    assert res.status_code == 403

    # Active user attempts to delete other's conversation
    res_del = client.delete(f"/api/v1/assistant/conversations/{other_conv.id}")
    assert res_del.status_code == 403


def test_nonexistent_conversation_returns_404(client: TestClient, db_session: Session):
    """Verify attempting to retrieve a nonexistent conversation ID returns 404 cleanly."""
    _get_or_create_user(db_session)
    res = client.get("/api/v1/assistant/conversations/987654321")
    assert res.status_code == 404
    assert "not found" in res.json().get("detail", "").lower()


# ==============================================================================
# Frontend Contracts & UI Accessibility Tests (Static File Audits)
# ==============================================================================

def test_frontend_css_contains_thinking_and_skeleton_styles():
    """Verify styles.css includes animated thinking state, shimmering skeletons, and reduced-motion support."""
    css_path = Path("frontend/static/css/styles.css")
    assert css_path.exists(), "frontend/static/css/styles.css must exist"
    content = css_path.read_text(encoding="utf-8")

    # Thinking state elements
    assert ".assistant-thinking-state" in content
    assert ".thinking-header" in content
    assert ".thinking-spinner" in content
    assert ".thinking-dot" in content
    assert ".thinking-label" in content
    assert ".thinking-shimmer-bar" in content
    assert "@keyframes thinkingBounce" in content
    assert "@keyframes thinkingShimmer" in content

    # Skeleton elements for fast history loading
    assert ".conversation-skeleton-container" in content
    assert ".conv-skeleton-" in content

    # Reduced motion preference support
    assert "@media (prefers-reduced-motion: reduce)" in content


def test_frontend_js_contains_abort_controller_and_loading_logic():
    """
    Verify api.js includes:
    1. currentHistoryAbortController to abort pending requests on conversation switch
    2. AbortError handling to prevent stale responses from overwriting the view
    3. thinking state rendering and stage label updating
    4. retry actions for cancelled/failed streams and failed history loading
    5. initialEmptyPromptHtml preservation
    """
    js_path = Path("frontend/static/js/api.js")
    assert js_path.exists(), "frontend/static/js/api.js must exist"
    content = js_path.read_text(encoding="utf-8")

    assert "currentHistoryAbortController" in content
    assert "AbortController" in content
    assert "err.name === 'AbortError'" in content or "error.name === 'AbortError'" in content
    assert "assistant-thinking-state" in content
    assert "thinking-label" in content
    assert "Searching your codebase..." in content
    assert "Thinking through" in content
    assert "retry-cancelled-btn" in content
    assert "retry-load-conv-btn" in content
    assert "initialEmptyPromptHtml" in content
