import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.integrations.llm.base import (
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelNotFoundError,
)


def _get_or_create_user(db: Session) -> User:
    user = db.query(User).filter(User.is_active == True).first()
    if not user:
        user = User(email="streamer@acme.dev", full_name="Stream Tester", workspace_name="Acme", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _create_repo_and_chunk(db: Session, name: str, user_id: int, file_path: str = "src/main.py", code: str = "def handle():\n    return True\n"):
    repo = Repository(name=name, full_name=f"acme/{name}", user_id=user_id, status="ready")
    db.add(repo)
    db.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path=file_path,
        code_symbol="handle",
        chunk_index=0,
        chunk_text=code,
        content_hash=f"h_{name}",
        language="python",
        start_line=1,
        end_line=10,
    )
    db.add(chunk)
    db.commit()
    return repo


def parse_sse_events(raw_text: str):
    """Parses raw SSE response text into a list of (event_name, data_dict) tuples."""
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


def test_stream_event_ordering_and_encoding(client: TestClient, db_session: Session, monkeypatch):
    """Verify SSE streaming produces correctly ordered and encoded meta, status, token, citation, and done events."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "stream-repo", user.id, "src/auth.py", "def login(username, password):\n    return verify_password(password)\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Stream Test Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_stream_chunks(*args, **kwargs):
        for token in ["The ", "login ", "flow ", "calls ", "`verify_password`."]:
            yield token

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Explain the login flow", "repository_id": repo.id}
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

    # Meta is first event
    assert event_names[0] == "meta"
    meta_data = events[0][1]
    assert meta_data["conversation_id"] == conv.id
    assert meta_data["repository_id"] == repo.id
    assert meta_data["stream_protocol_version"] == "1.0"

    # Done is last event
    assert event_names[-1] == "done"
    done_data = events[-1][1]
    assert done_data["conversation_id"] == conv.id
    assert done_data["status"] == "success"
    assert "login" in done_data["answer"]
    assert "facts" in done_data

    # Tokens assembled
    tokens = [e[1]["token"] for e in events if e[0] == "token"]
    assert "".join(tokens) == "The login flow calls `verify_password`."


def test_stream_multiple_token_fragments_assembly(client: TestClient, db_session: Session, monkeypatch):
    """Verify multiple fine-grained token chunks stream and reassemble accurately in DB."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "tok-repo", user.id, "src/session.py", "def check_session(token):\n    return token.is_valid()\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Token Assembly Conv")
    db_session.add(conv)
    db_session.commit()

    fragments = ["def ", "check_session", "(token):\n", "    return ", "token.is_valid()"]

    async def mock_stream_chunks(*args, **kwargs):
        for frag in fragments:
            yield frag

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Show session check", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    streamed_tokens = [e[1]["token"] for e in events if e[0] == "token"]
    assert streamed_tokens == fragments

    # Verify persisted message in DB matches assembled text
    msg = db_session.query(AssistantMessage).filter_by(conversation_id=conv.id, role="assistant").first()
    assert msg is not None
    assert msg.status == "success"
    assert "".join(fragments) in msg.content


def test_stream_unicode_and_multiline_content(client: TestClient, db_session: Session, monkeypatch):
    """Verify stream handles emojis, multi-byte Unicode characters, and code block newlines."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "unicode-repo", user.id, "src/auth_intl.py", "def verify_unicode():\n    return 'ok'\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Unicode Conv")
    db_session.add(conv)
    db_session.commit()

    unicode_fragments = [
        "🚀 Authenticating user...\n",
        "ユーザー認証: 成功\n",
        "```python\n",
        "def verify():\n",
        "    return '✨ verified'\n",
        "```",
    ]

    async def mock_stream_chunks(*args, **kwargs):
        for frag in unicode_fragments:
            yield frag

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Show Unicode auth", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    tokens = [e[1]["token"] for e in events if e[0] == "token"]
    assert "".join(tokens) == "".join(unicode_fragments)


def test_stream_empty_response(client: TestClient, db_session: Session, monkeypatch):
    """Verify handling when LLM returns no tokens."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "empty-repo", user.id, "src/empty.py", "# empty file\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Empty Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_empty_chunks(*args, **kwargs):
        if False:
            yield "never"

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_empty_chunks
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Nothing here", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    done_events = [e[1] for e in events if e[0] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["status"] == "success"


def test_stream_ollama_connection_error_handling(client: TestClient, db_session: Session, monkeypatch):
    """Verify Ollama connection error emits error event, does NOT emit done, and does NOT record success in DB."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "err-repo", user.id, "src/err.py", "def error_target(): pass\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Error Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_conn_error(*args, **kwargs):
        raise LLMConnectionError("Could not connect to Ollama at 127.0.0.1:11434")
        yield "never"

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_conn_error
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Trigger error", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    event_names = [e[0] for e in events]

    assert "error" in event_names
    assert "done" not in event_names

    err_data = next(e[1] for e in events if e[0] == "error")
    assert err_data["error_type"] == "LLMConnectionError"
    assert "Ollama" in err_data["message"] or "connect" in err_data["message"]

    # Verify database does not mark as success
    asst_msg = db_session.query(AssistantMessage).filter_by(conversation_id=conv.id, role="assistant").first()
    assert asst_msg is not None
    assert asst_msg.status == "failed"


def test_stream_ollama_timeout_handling(client: TestClient, db_session: Session, monkeypatch):
    """Verify Ollama timeout emits structured error event with timeout detail."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "tout-repo", user.id, "src/tout.py", "def timeout_target(): pass\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Timeout Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_timeout_error(*args, **kwargs):
        raise LLMTimeoutError("Ollama generation timed out after 30.0s")
        yield "never"

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_timeout_error
    )

    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Trigger timeout", "repository_id": repo.id}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    err_data = next(e[1] for e in events if e[0] == "error")
    assert err_data["error_type"] == "LLMTimeoutError"
    assert "timed out" in err_data["message"]

    asst_msg = db_session.query(AssistantMessage).filter_by(conversation_id=conv.id, role="assistant").first()
    assert asst_msg.status == "failed"


def test_stream_direct_repo_endpoint(client: TestClient, db_session: Session, monkeypatch):
    """Verify POST /api/v1/repositories/{id}/assistant/stream creates conversation and streams response."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "direct-repo", user.id, "src/app.py", "def main(): pass\n")

    async def mock_stream_chunks(*args, **kwargs):
        for t in ["Direct ", "repo ", "streaming ", "answer."]:
            yield t

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    with client.stream(
        "POST",
        f"/api/v1/repositories/{repo.id}/assistant/stream",
        json={"question": "What does this repo do?"}
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = parse_sse_events(body)
    event_names = [e[0] for e in events]
    assert "meta" in event_names
    assert "done" in event_names

    meta_data = events[0][1]
    assert meta_data["repository_id"] == repo.id
    assert meta_data["conversation_id"] is not None

    tokens = [e[1]["token"] for e in events if e[0] == "token"]
    assert "".join(tokens) == "Direct repo streaming answer."


def test_non_streaming_endpoint_remains_backward_compatible(client: TestClient, db_session: Session, monkeypatch):
    """Verify non-streaming endpoint still functions as before without regressions."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "compat-repo", user.id, "src/compat.py", "def compat(): pass\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Compat Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_generate_answer(*args, **kwargs):
        return "Standard non-streaming answer."

    monkeypatch.setattr(
        "backend.app.services.assistant_service.AssistantService._generate_llm_answer",
        mock_generate_answer
    )

    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={"content": "Compat question", "repository_id": repo.id}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["conversation_id"] == conv.id
    assert "Standard non-streaming answer" in data["answer"]
    assert "citations" in data
    assert "facts" in data
    assert data["status"] == "success"


def test_streaming_cancellation_on_disconnect(db_session: Session, monkeypatch):
    """Verify that when client disconnects during streaming, CancelledError is raised and message status is cancelled."""
    user = _get_or_create_user(db_session)
    repo = _create_repo_and_chunk(db_session, "cancel-repo", user.id, "src/cancel.py", "def cancel_test(): pass\n")

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Cancel Conv")
    db_session.add(conv)
    db_session.commit()

    from unittest.mock import MagicMock
    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(side_effect=[False, True, True])

    from backend.app.services.assistant_service import AssistantService

    async def mock_stream_chunks(*args, **kwargs):
        yield "First chunk "
        yield "Second chunk "

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    async def _run():
        gen = AssistantService.stream_answer_question(
            db=db_session,
            repository_id=repo.id,
            question="How does cancellation work?",
            user_id=user.id,
            conversation_id=conv.id,
            request=mock_request,
        )

        with pytest.raises(asyncio.CancelledError):
            async for _ in gen:
                pass

    asyncio.run(_run())

    cancelled_msg = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "assistant"
    ).first()
    assert cancelled_msg is not None
    assert cancelled_msg.status == "cancelled"


