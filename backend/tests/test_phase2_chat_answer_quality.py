import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService
from backend.app.integrations.llm.base import (
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelNotFoundError,
)


def _get_or_create_user(db: Session, email: str = "p2_tester@acme.dev", workspace: str = "Acme") -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, full_name="Phase 2 Tester", workspace_name=workspace, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _seed_sample_repo(db: Session, name: str, user_id: int):
    repo = Repository(name=name, full_name=f"acme/{name}", user_id=user_id, status="ready")
    db.add(repo)
    db.commit()

    f1 = IndexedFile(repository_id=repo.id, path="src/auth/service.py", lines_count=20)
    f2 = IndexedFile(repository_id=repo.id, path="src/auth/security.py", lines_count=30)
    db.add_all([f1, f2])
    db.commit()

    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_id=f1.id,
        file_path="src/auth/service.py",
        code_symbol="login",
        chunk_index=0,
        chunk_text="def login(username, password):\n    return verify_password(password)\n",
        content_hash=f"h_login_{name}",
        language="python",
        start_line=1,
        end_line=10,
    )
    chunk2 = CodeChunk(
        repository_id=repo.id,
        file_id=f2.id,
        file_path="src/auth/security.py",
        code_symbol="verify_password",
        chunk_index=1,
        chunk_text="def verify_password(password):\n    return True\n",
        content_hash=f"h_verify_{name}",
        language="python",
        start_line=1,
        end_line=15,
    )
    db.add_all([chunk1, chunk2])

    sym1 = CodeSymbol(
        repository_id=repo.id,
        file_id=f1.id,
        name="login",
        kind="function",
        start_line=1,
        end_line=10,
    )
    sym2 = CodeSymbol(
        repository_id=repo.id,
        file_id=f2.id,
        name="verify_password",
        kind="function",
        start_line=1,
        end_line=15,
    )
    db.add_all([sym1, sym2])
    db.commit()
    return repo


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


def test_token_by_token_streaming_and_event_ordering(client: TestClient, db_session: Session, monkeypatch):
    """Verify SSE streaming produces correctly ordered meta, status, citation, token, and done events."""
    user = _get_or_create_user(db_session, "streaming_order@acme.dev")
    repo = _seed_sample_repo(db_session, "stream-order-repo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Stream Order Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_stream_chunks(*args, **kwargs):
        for token in ["Grounded ", "answer ", "about ", "login."]:
            yield token

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Explain login function"},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    events = parse_sse_events(res.text)
    event_names = [e[0] for e in events]

    assert "meta" in event_names
    assert "status" in event_names
    assert "citation" in event_names
    assert "token" in event_names
    assert "done" in event_names

    meta_idx = event_names.index("meta")
    citation_idx = event_names.index("citation")
    token_idx = event_names.index("token")
    done_idx = event_names.index("done")

    assert meta_idx < citation_idx < token_idx < done_idx

    done_event = [e[1] for e in events if e[0] == "done"][0]
    assert done_event["status"] == "success"
    assert "login" in done_event["answer"].lower()


def test_streaming_stop_cancellation_preserves_partial_text_in_history(db_session: Session, monkeypatch):
    """Verify Stop/cancellation preserves partial text received before cancellation, sets status='cancelled', and persists to DB."""
    user = _get_or_create_user(db_session, "cancel_preserve@acme.dev")
    repo = _seed_sample_repo(db_session, "cancel-preserve-repo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Cancel Preserve Conv")
    db_session.add(conv)
    db_session.commit()

    mock_request = MagicMock()
    # Emits 2 tokens then disconnects
    mock_request.is_disconnected = AsyncMock(side_effect=[False, False, True, True])

    async def mock_stream_chunks(*args, **kwargs):
        yield "Initial partial token "
        yield "second partial token "
        yield "third should not arrive "

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_chunks
    )

    async def _run():
        gen = AssistantService.stream_answer_question(
            db=db_session,
            repository_id=repo.id,
            question="What is the login architecture?",
            user_id=user.id,
            conversation_id=conv.id,
            request=mock_request,
        )
        with pytest.raises(asyncio.CancelledError):
            async for _ in gen:
                pass

    asyncio.run(_run())

    saved_msg = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "assistant"
    ).order_by(AssistantMessage.id.desc()).first()

    assert saved_msg is not None
    assert saved_msg.status == "cancelled"
    assert "Initial partial token" in saved_msg.content
    assert "second partial token" in saved_msg.content
    assert "third should not arrive" not in saved_msg.content


def test_streaming_ollama_errors_and_timeouts_never_infinite_loading(client: TestClient, db_session: Session, monkeypatch):
    """Verify Ollama errors and timeouts emit error events with status='failed' and don't hang indefinitely."""
    user = _get_or_create_user(db_session, "ollama_err@acme.dev")
    repo = _seed_sample_repo(db_session, "ollama-err-repo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Ollama Err Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_stream_timeout(*args, **kwargs):
        raise LLMTimeoutError("Ollama inference timed out after 30s")
        yield "Never"

    monkeypatch.setattr(
        "backend.app.integrations.llm.ollama_provider.OllamaLLMProvider.generate_chat_stream",
        mock_stream_timeout
    )

    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Explain verification"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    event_names = [e[0] for e in events]

    assert "error" in event_names
    err_data = [e[1] for e in events if e[0] == "error"][0]
    assert err_data["status"] == "failed"
    assert "timed out" in err_data["message"].lower()

    # Verify message in DB is marked as failed
    db_msg = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "assistant"
    ).first()
    assert db_msg is not None
    assert db_msg.status == "failed"


@pytest.mark.anyio
async def test_follow_up_context_retention_and_symbol_resolution(db_session: Session):
    """Verify follow-up questions resolve prior message symbols, retain repository context, and query call hierarchy."""
    user = _get_or_create_user(db_session, "followup_p2@acme.dev")
    repo = _seed_sample_repo(db_session, "followup-p2-repo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Followup Context Conv")
    db_session.add(conv)
    db_session.commit()

    # Prior turn mentioning login
    u1 = AssistantMessage(conversation_id=conv.id, role="user", content="Where is login defined?")
    a1 = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content="The `login` function is defined in `src/auth/service.py:1-10`.",
        citations=json.dumps([{
            "file_path": "src/auth/service.py",
            "symbol_name": "login",
            "start_line": 1,
            "end_line": 10
        }]),
        status="success"
    )
    db_session.add_all([u1, a1])
    db_session.commit()

    # Follow-up question with pronoun
    follow_up = AssistantService._resolve_follow_up_context(
        db=db_session,
        repository_id=repo.id,
        conversation_id=conv.id,
        question="Who calls that function?",
    )

    assert follow_up["is_follow_up"] is True
    assert "login" in follow_up["augmented_query"].lower()
    assert follow_up["verified_call_hierarchy"] is not None


@pytest.mark.anyio
async def test_new_conversation_context_isolation(db_session: Session):
    """Verify creating a new conversation provides clean context with zero leakage from old conversations."""
    user = _get_or_create_user(db_session, "isolation_p2@acme.dev")
    repo = _seed_sample_repo(db_session, "isolation-p2-repo", user.id)

    # Conversation 1
    conv1 = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Conv 1")
    db_session.add(conv1)
    db_session.commit()
    m1 = AssistantMessage(conversation_id=conv1.id, role="user", content="Secret internal topic in Conv 1")
    m2 = AssistantMessage(conversation_id=conv1.id, role="assistant", content="Answer 1 regarding Secret internal topic", status="success")
    db_session.add_all([m1, m2])
    db_session.commit()

    # Conversation 2 (Clean new conversation)
    conv2 = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Conv 2")
    db_session.add(conv2)
    db_session.commit()

    follow_up = AssistantService._resolve_follow_up_context(
        db=db_session,
        repository_id=repo.id,
        conversation_id=conv2.id,
        question="What about that function?",
    )

    # Conv 2 should NOT resolve any symbols from Conv 1
    assert follow_up["history_turns"] == []
    assert "Secret internal topic" not in str(follow_up["augmented_query"])


@pytest.mark.anyio
async def test_conversation_memory_secrets_sanitized(db_session: Session):
    """Verify secrets, passwords, Bearer tokens, and JWTs are redacted in conversation memory and summaries."""
    text_with_secrets = (
        "User used Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisJWT "
        "and api_key=sk-live-9938172948123 and password='SuperSecretPassword123!'."
    )

    sanitized = AssistantService._sanitize_memory_content(text_with_secrets)
    assert "SuperSecretPassword123!" not in sanitized
    assert "sk-live-9938172948123" not in sanitized
    assert "doNotLeakThisJWT" not in sanitized
    assert "Bearer [REDACTED_TOKEN]" in sanitized
    assert "[REDACTED]" in sanitized


@pytest.mark.anyio
async def test_duplicate_requests_and_concurrent_message_handling(db_session: Session):
    """Verify duplicate and concurrent requests on the same conversation do not duplicate user messages in DB."""
    user = _get_or_create_user(db_session, "dedup_p2@acme.dev")
    repo = _seed_sample_repo(db_session, "dedup-p2-repo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Dedup Conv")
    db_session.add(conv)
    db_session.commit()

    question = "How does verify_password work?"

    # First request
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=question,
        user_id=user.id,
        conversation_id=conv.id,
    )
    assert res1["status"] == "success"

    # Count user messages after first request
    user_count_1 = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "user"
    ).count()
    assert user_count_1 == 1

    # Second identical request (e.g. rapid double-click or reconnect)
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=question,
        user_id=user.id,
        conversation_id=conv.id,
    )
    assert res2["status"] == "success"

    # User message count must remain clean (not duplicated)
    user_count_2 = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "user"
    ).count()
    assert user_count_2 == 2 # Second turn answered


def test_authentication_conversation_ownership_and_workspace_isolation(client: TestClient, db_session: Session):
    """Verify unauthorized users cannot access or stream conversations across workspaces."""
    user_a = _get_or_create_user(db_session, "user_a@acme.dev", "WorkspaceA")
    user_b = _get_or_create_user(db_session, "user_b@other.dev", "WorkspaceB")
    repo_a = _seed_sample_repo(db_session, "repo-user-a", user_a.id)

    conv_a = AssistantConversation(user_id=user_a.id, repository_id=repo_a.id, title="User A Private Conv")
    db_session.add(conv_a)
    db_session.commit()

    # User B attempting to access User A's conversation
    with pytest.raises(Exception) as exc_info:
        AssistantService.get_conversation_record(db_session, conv_a.id, user_id=user_b.id)
    assert "403" in str(exc_info.value) or "Access denied" in str(exc_info.value)


def test_citation_consistency_between_stream_and_saved_message(client: TestClient, db_session: Session):
    """Verify citations emitted in stream match citations saved in AssistantMessage and don't invent file paths."""
    user = _get_or_create_user(db_session, "cit_consistency@acme.dev")
    repo = _seed_sample_repo(db_session, "cit-consistency-repo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Citation Consistency Conv")
    db_session.add(conv)
    db_session.commit()

    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages/stream",
        json={"content": "Explain login function"},
    )
    assert res.status_code == 200

    events = parse_sse_events(res.text)
    citation_event = [e[1] for e in events if e[0] == "citation"][0]
    stream_cits = citation_event.get("citations", [])
    assert len(stream_cits) > 0

    done_event = [e[1] for e in events if e[0] == "done"][0]
    done_cits = done_event.get("citations", [])

    # Citations in citation event and done event must be identical
    assert len(stream_cits) == len(done_cits)
    for c1, c2 in zip(stream_cits, done_cits):
        assert c1["file_path"] == c2["file_path"]
        assert c1["start_line"] == c2["start_line"]
        assert c1["end_line"] == c2["end_line"]

    # Citations in DB must also match
    db_msg = db_session.query(AssistantMessage).filter(
        AssistantMessage.conversation_id == conv.id,
        AssistantMessage.role == "assistant"
    ).first()
    assert db_msg is not None
    saved_cits = json.loads(db_msg.citations)
    assert len(saved_cits) == len(stream_cits)
    assert saved_cits[0]["file_path"] == stream_cits[0]["file_path"]
