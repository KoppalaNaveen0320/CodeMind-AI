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
from backend.app.integrations.llm.base import LLMTimeoutError, LLMConnectionError


def _get_or_create_user(db: Session, email="regression_tester@codemind.dev") -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            full_name="Regression Tester",
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
# Scenario 1: Successful non-streaming responses (POST /messages)
# ==============================================================================
def test_scenario_1_successful_non_streaming_response(client: TestClient, db_session: Session, monkeypatch):
    user = _get_or_create_user(db_session)
    repo = Repository(name="sync-repo", full_name="codemind/sync-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/main.py",
        code_symbol="bootstrap_app",
        chunk_index=0,
        chunk_text="def bootstrap_app(): return 'App started'\n",
        content_hash="sync_h1",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Non-Streaming Test")
    db_session.add(conv)
    db_session.commit()

    async def mock_gen(*args, **kwargs):
        return "The bootstrap_app initializes the platform."

    monkeypatch.setattr(
        "backend.app.services.assistant_service.AssistantService._generate_llm_answer",
        mock_gen
    )

    response = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={"content": "How does bootstrap_app work?", "repository_id": repo.id}
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "bootstrap_app" in data["answer"]
    assert data["status"] == "success"
    assert data["conversation_id"] == conv.id


# ==============================================================================
# Scenario 2: Successful streaming with multiple chunks (POST /messages/stream)
# ==============================================================================
def test_scenario_2_successful_streaming_multiple_chunks(client: TestClient, db_session: Session, monkeypatch):
    user = _get_or_create_user(db_session)
    repo = Repository(name="stream-repo-2", full_name="codemind/stream-repo-2", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/engine.py",
        code_symbol="run_engine",
        chunk_index=0,
        chunk_text="def run_engine(): return True\n",
        content_hash="stream_h2",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Multi-Chunk Stream Test")
    db_session.add(conv)
    db_session.commit()

    expected_tokens = ["Engine ", "executes ", "in ", "real-time."]

    class MockStreamProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            for t in expected_tokens:
                yield t

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: MockStreamProvider()
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "How does run_engine operate?", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    tokens = [e[1]["token"] for e in events if e[0] == "token"]
    assert tokens == expected_tokens
    assert "".join(tokens) == "Engine executes in real-time."


# ==============================================================================
# Scenario 3: SSE chunks split across network reads (Buffer handling)
# ==============================================================================
def test_scenario_3_sse_chunks_split_across_network_reads():
    """
    Simulate the frontend streamSSE line-buffering algorithm when network reads
    split SSE frames across arbitrary chunk boundaries.
    """
    raw_sse = (
        "event: meta\ndata: {\"conversation_id\": 10}\n\n"
        "event: status\ndata: {\"stage\": \"generating\"}\n\n"
        "event: token\ndata: {\"token\": \"Hello \"}\n\n"
        "event: token\ndata: {\"token\": \"World!\"}\n\n"
        "event: done\ndata: {\"status\": \"success\"}\n\n"
    )

    # Split into arbitrary 11-byte fragments
    fragments = [raw_sse[i:i+11] for i in range(0, len(raw_sse), 11)]
    assert len(fragments) > 5

    parsed_events = []
    buffer = ""
    current_event = None

    for frag in fragments:
        buffer += frag
        lines = buffer.split("\n")
        buffer = lines.pop() # Keep incomplete trailing slice

        for line in lines:
            line = line.strip("\r")
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_val = json.loads(line[len("data: "):].strip())
                parsed_events.append((current_event, data_val))
                current_event = None

    assert len(parsed_events) == 5
    assert parsed_events[0][0] == "meta"
    assert parsed_events[2][1]["token"] == "Hello "
    assert parsed_events[3][1]["token"] == "World!"
    assert parsed_events[4][0] == "done"


# ==============================================================================
# Scenario 4: Completion and Error events
# ==============================================================================
def test_scenario_4_completion_and_error_events(client: TestClient, db_session: Session, monkeypatch):
    user = _get_or_create_user(db_session)
    repo = Repository(name="event-repo", full_name="codemind/event-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/event_handler.py",
        code_symbol="handle_event",
        chunk_index=0,
        chunk_text="def handle_event(): return 'event handled'\n",
        content_hash="event_h1",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Error Event Test")
    db_session.add(conv)
    db_session.commit()

    class FailingProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            raise LLMConnectionError("Remote provider refused connection")
            yield "never"

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: FailingProvider()
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Explain handle_event failure", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    event_names = [e[0] for e in events]
    assert "error" in event_names
    err = [e[1] for e in events if e[0] == "error"][0]
    assert "Remote provider refused connection" in err["message"]
    assert err["status"] == "failed"


# ==============================================================================
# Scenario 5: LLM Timeout and Provider Failure
# ==============================================================================
def test_scenario_5_llm_timeout_and_provider_failure(client: TestClient, db_session: Session, monkeypatch):
    user = _get_or_create_user(db_session)
    repo = Repository(name="timeout-repo", full_name="codemind/timeout-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/slow.py",
        code_symbol="slow_operation",
        chunk_index=0,
        chunk_text="def slow_operation(): time.sleep(100)\n",
        content_hash="slow_h1",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Timeout Test")
    db_session.add(conv)
    db_session.commit()

    class TimeoutProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            raise LLMTimeoutError("LLM response timed out after 45 seconds")
            yield "never"

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: TimeoutProvider()
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Explain slow_operation", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    err = [e[1] for e in events if e[0] == "error"][0]
    assert "timed out" in err["message"].lower()

    # Verify assistant message in DB marked as failed with actionable error
    saved_msg = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "assistant"
    ).order_by(AssistantMessage.id.desc()).first()
    assert saved_msg is not None
    assert saved_msg.status == "failed"
    assert "timed out" in saved_msg.content.lower()


# ==============================================================================
# Scenario 6: User Cancellation and Stop Button Cleanup
# ==============================================================================
def test_scenario_6_cancellation_persists_cancelled_message(client: TestClient, db_session: Session, monkeypatch):
    """Verify that when a client disconnects/cancels, status is saved as 'cancelled'."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="cancel-repo", full_name="codemind/cancel-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/cancel.py",
        code_symbol="abortable_task",
        chunk_index=0,
        chunk_text="def abortable_task(): pass\n",
        content_hash="cancel_h1",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Cancellation Test")
    db_session.add(conv)
    db_session.commit()

    class CancelledStreamProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            yield "Starting task... "
            raise asyncio.CancelledError()

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: CancelledStreamProvider()
    )

    try:
        client.post(
            f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
            json={"content": "Explain abortable_task", "repository_id": repo.id}
        )
    except Exception:
        pass

    cancelled_msg = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "assistant",
        AssistantMessage.status == "cancelled"
    ).first()
    assert cancelled_msg is not None
    assert "Starting task..." in cancelled_msg.content


# ==============================================================================
# Scenario 7: Empty or Malformed Streaming Events
# ==============================================================================
def test_scenario_7_empty_or_malformed_streaming_events():
    """Verify parser handles empty events, corrupted JSON, and non-JSON tokens without throwing."""
    malformed_body = (
        ": heartbeat\n\n"
        "event: meta\ndata: \n\n"
        "event: token\ndata: not_valid_json\n\n"
        "event: token\ndata: {\"token\": \"Valid token\"}\n\n"
        "data: [DONE]\n\n"
    )

    events = parse_sse_events(malformed_body)
    assert len(events) >= 2
    # Verify non-JSON string is preserved rather than throwing
    non_json = [e[1] for e in events if e[1] == "not_valid_json"]
    assert len(non_json) == 1
    # Verify valid token is correctly extracted
    valid_token = [e[1]["token"] for e in events if isinstance(e[1], dict) and "token" in e[1]]
    assert valid_token == ["Valid token"]


# ==============================================================================
# Scenario 8: Duplicate Submission Prevention
# ==============================================================================
def test_scenario_8_duplicate_submission_prevention(client: TestClient, db_session: Session, monkeypatch):
    """Verify concurrent or retried identical question reuses the pending message instead of duplicating."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="dedup-repo", full_name="codemind/dedup-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Dedup Test")
    db_session.add(conv)
    db_session.commit()

    # Create an initial user message without assistant response yet
    initial_msg = AssistantMessage(
        conversation_id=conv.id,
        role="user",
        content="What is the architecture?",
        status="success"
    )
    db_session.add(initial_msg)
    db_session.commit()

    class DummyProvider:
        is_configured = True
        async def generate_chat_stream(self, *args, **kwargs):
            yield "Architecture details."

    monkeypatch.setattr(
        "backend.app.services.assistant_service.get_llm_provider",
        lambda *args, **kwargs: DummyProvider()
    )

    # Calling stream with identical content
    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "What is the architecture?", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200

    user_msgs = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "user"
    ).all()
    # Should not have created a second duplicate user message
    assert len(user_msgs) == 1


# ==============================================================================
# Scenario 9: Loading existing conversation with multiple messages in chronological order
# ==============================================================================
def test_scenario_9_loading_existing_conversation_chronological(client: TestClient, db_session: Session):
    user = _get_or_create_user(db_session)
    repo = Repository(name="hist-repo", full_name="codemind/hist-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="History Chronological Test")
    db_session.add(conv)
    db_session.commit()

    # Insert 6 messages
    for i in range(6):
        role = "user" if i % 2 == 0 else "assistant"
        db_session.add(AssistantMessage(conversation_id=conv.id, role=role, content=f"Step {i}"))
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["messages"]) == 6
    for idx, m in enumerate(data["messages"]):
        assert m["content"] == f"Step {idx}"
        if idx > 0:
            assert m["id"] > data["messages"][idx - 1]["id"]


# ==============================================================================
# Scenario 10: Switching between two conversations without stale message leakage
# ==============================================================================
def test_scenario_10_switching_between_conversations_isolation(client: TestClient, db_session: Session):
    user = _get_or_create_user(db_session)
    conv1 = AssistantConversation(user_id=user.id, title="Conversation Alpha")
    conv2 = AssistantConversation(user_id=user.id, title="Conversation Beta")
    db_session.add_all([conv1, conv2])
    db_session.commit()

    db_session.add(AssistantMessage(conversation_id=conv1.id, role="user", content="Secret Alpha 123"))
    db_session.add(AssistantMessage(conversation_id=conv2.id, role="user", content="Secret Beta 456"))
    db_session.commit()

    res1 = client.get(f"/api/v1/assistant/conversations/{conv1.id}").json()
    res2 = client.get(f"/api/v1/assistant/conversations/{conv2.id}").json()

    assert len(res1["messages"]) == 1
    assert res1["messages"][0]["content"] == "Secret Alpha 123"

    assert len(res2["messages"]) == 1
    assert res2["messages"][0]["content"] == "Secret Beta 456"

    # Verify no cross-contamination
    assert not any("Beta" in m["content"] for m in res1["messages"])
    assert not any("Alpha" in m["content"] for m in res2["messages"])


# ==============================================================================
# Scenario 11: Refreshing and reopening conversation history
# ==============================================================================
def test_scenario_11_refresh_and_reopen_preserves_history(client: TestClient, db_session: Session):
    user = _get_or_create_user(db_session)
    repo = Repository(name="persist-repo", full_name="codemind/persist-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Persistence Test")
    db_session.add(conv)
    db_session.commit()

    msg = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content="Persistent summary.",
        citations=json.dumps([{"file_path": "a.py", "start_line": 1, "end_line": 10}])
    )
    db_session.add(msg)
    db_session.commit()

    # First fetch (e.g., initial open)
    res_1 = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res_1.status_code == 200

    # Second fetch (e.g., page refresh and reopen)
    res_2 = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res_2.status_code == 200
    assert res_1.json() == res_2.json()
    assert res_2.json()["messages"][0]["citations"][0]["file_path"] == "a.py"


# ==============================================================================
# Scenario 12: Repository context restoration
# ==============================================================================
def test_scenario_12_repository_context_restoration(client: TestClient, db_session: Session):
    user = _get_or_create_user(db_session)
    repo = Repository(
        name="restored-repo",
        full_name="codemind/restored-repo",
        user_id=user.id,
        default_branch="dev-v2",
        status="ready"
    )
    db_session.add(repo)
    db_session.commit()

    conv = AssistantConversation(
        user_id=user.id,
        repository_id=repo.id,
        branch="dev-v2",
        title="Restoration Test"
    )
    db_session.add(conv)
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["repository_id"] == repo.id
    assert data["branch"] == "dev-v2"


# ==============================================================================
# Scenario 13: Unauthorized conversation access rejection
# ==============================================================================
def test_scenario_13_unauthorized_conversation_access_rejected(client: TestClient, db_session: Session):
    _get_or_create_user(db_session, email="active_session@codemind.dev")
    other_user = User(email="isolated_victim@codemind.dev", full_name="Victim", is_active=False)
    db_session.add(other_user)
    db_session.commit()

    other_conv = AssistantConversation(user_id=other_user.id, title="Victim Private Notes")
    db_session.add(other_conv)
    db_session.commit()

    # Active user attempts to access victim's conversation
    res = client.get(f"/api/v1/assistant/conversations/{other_conv.id}")
    assert res.status_code == 403
    assert "access denied" in res.json().get("detail", "").lower()


# ==============================================================================
# Scenario 14: Backend history errors and empty conversations
# ==============================================================================
def test_scenario_14_backend_history_errors_and_empty_conversations(client: TestClient, db_session: Session):
    user = _get_or_create_user(db_session)

    # 1. Nonexistent conversation -> 404
    res_404 = client.get("/api/v1/assistant/conversations/999999999")
    assert res_404.status_code == 404

    # 2. Empty conversation -> 200 with empty messages array
    empty_conv = AssistantConversation(user_id=user.id, title="Empty Conversation")
    db_session.add(empty_conv)
    db_session.commit()

    res_empty = client.get(f"/api/v1/assistant/conversations/{empty_conv.id}")
    assert res_empty.status_code == 200
    assert res_empty.json()["messages"] == []


# ==============================================================================
# Scenario 15: Ensuring loading and Stop controls reset on every terminal path
# ==============================================================================
def test_scenario_15_loading_and_stop_controls_reset_contracts():
    """Verify frontend JavaScript guarantees composer state reset on success, error, timeout, and stop."""
    js_path = Path("frontend/static/js/api.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    # resetComposerState function must exist and reset isSending, stopBtn, sendBtn, and textarea
    assert "function resetComposerState()" in content
    assert "isSending = false;" in content
    assert "stopBtn.style.display = 'none';" in content
    assert "sendBtn.style.display = 'grid';" in content
    assert "textarea.disabled = false;" in content

    # Guaranteed invocation in finally block
    assert "finally {" in content
    assert "resetComposerState();" in content

    # Guaranteed invocation on stopBtn click
    assert "stopBtn.onclick" in content or "stopBtn.addEventListener('click'" in content
    assert "currentStreamAbortController.abort();" in content
