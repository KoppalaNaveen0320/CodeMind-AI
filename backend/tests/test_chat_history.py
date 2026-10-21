import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch

from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService


def _get_or_create_user(db: Session) -> User:
    user = db.query(User).filter(User.is_active == True).first()
    if not user:
        user = User(email="alex@acme.dev", full_name="Alex Kim", workspace_name="Acme", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def test_create_conversation(client: TestClient, db_session: Session):
    """Verify creating a conversation persists to DB and returns conversation details."""
    repo = Repository(name="conv-repo", full_name="acme/conv-repo", status="ready")
    db_session.add(repo)
    db_session.commit()

    res = client.post("/api/v1/assistant/conversations", json={
        "title": "Auth Architecture Discussion",
        "repository_id": repo.id,
        "branch": "feature/auth"
    })
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Auth Architecture Discussion"
    assert data["repository_id"] == repo.id
    assert data["branch"] == "feature/auth"
    assert data["messages_count"] == 0

    # Authoritative persistence in DB
    conv_in_db = db_session.query(AssistantConversation).filter_by(id=data["id"]).first()
    assert conv_in_db is not None
    assert conv_in_db.title == "Auth Architecture Discussion"
    assert conv_in_db.branch == "feature/auth"


def test_list_conversations_for_authenticated_user(client: TestClient, db_session: Session):
    """Verify listing conversations returns conversations belonging to the user."""
    user = _get_or_create_user(db_session)

    conv1 = AssistantConversation(user_id=user.id, title="Conv 1 - Architecture")
    conv2 = AssistantConversation(user_id=user.id, title="Conv 2 - Bug Hunting")
    db_session.add_all([conv1, conv2])
    db_session.commit()

    res = client.get("/api/v1/assistant/conversations")
    assert res.status_code == 200
    data = res.json()
    titles = [c["title"] for c in data]
    assert "Conv 1 - Architecture" in titles
    assert "Conv 2 - Bug Hunting" in titles


def test_retrieve_messages_in_chronological_order(client: TestClient, db_session: Session):
    """Verify messages are retrieved in chronological order with evidence metadata."""
    user = _get_or_create_user(db_session)
    conv = AssistantConversation(user_id=user.id, title="Test Order")
    db_session.add(conv)
    db_session.commit()

    msg1 = AssistantMessage(conversation_id=conv.id, role="user", content="First question?")
    msg2 = AssistantMessage(conversation_id=conv.id, role="assistant", content="First answer.", status="success")
    msg3 = AssistantMessage(conversation_id=conv.id, role="user", content="Follow-up question?")
    msg4 = AssistantMessage(conversation_id=conv.id, role="assistant", content="Follow-up answer.", status="success")
    db_session.add_all([msg1, msg2, msg3, msg4])
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    data = res.json()
    msgs = data["messages"]
    assert len(msgs) == 4
    assert msgs[0]["content"] == "First question?"
    assert msgs[1]["content"] == "First answer."
    assert msgs[2]["content"] == "Follow-up question?"
    assert msgs[3]["content"] == "Follow-up answer."


def test_reopen_old_conversation_and_append_messages(client: TestClient, db_session: Session, monkeypatch):
    """Verify appending a new question to an existing conversation retains history."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="chat-repo", full_name="acme/chat-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/service.py",
        code_symbol="handleAuth",
        chunk_index=0,
        chunk_text="def handleAuth(req):\n    return True\n",
        content_hash="h_auth",
        language="python",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, branch="main", title="Initial Conv")
    db_session.add(conv)
    db_session.commit()

    # Add initial messages
    m1 = AssistantMessage(conversation_id=conv.id, role="user", content="Initial question")
    m2 = AssistantMessage(conversation_id=conv.id, role="assistant", content="Initial answer")
    db_session.add_all([m1, m2])
    db_session.commit()

    # Reopen conversation and send follow-up message via endpoint
    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={"content": "Follow-up question about handleAuth", "repository_id": repo.id}
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["conversation_id"] == conv.id

    # Verify 4 messages in DB now
    all_msgs = db_session.query(AssistantMessage).filter_by(conversation_id=conv.id).order_by(AssistantMessage.id).all()
    assert len(all_msgs) == 4
    assert all_msgs[2].content == "Follow-up question about handleAuth"
    assert all_msgs[3].role == "assistant"


def test_rename_and_delete_conversation(client: TestClient, db_session: Session):
    """Verify renaming and deleting a conversation with proper cascade."""
    user = _get_or_create_user(db_session)
    conv = AssistantConversation(user_id=user.id, title="Old Title")
    db_session.add(conv)
    db_session.commit()

    msg = AssistantMessage(conversation_id=conv.id, role="user", content="Hello")
    db_session.add(msg)
    db_session.commit()

    # Rename
    res_rename = client.patch(f"/api/v1/assistant/conversations/{conv.id}", json={"title": "Updated Title"})
    assert res_rename.status_code == 200
    assert res_rename.json()["title"] == "Updated Title"

    # Delete
    res_del = client.delete(f"/api/v1/assistant/conversations/{conv.id}")
    assert res_del.status_code == 204

    # Verify deleted from DB
    assert db_session.query(AssistantConversation).filter_by(id=conv.id).first() is None
    # Verify messages cascaded
    assert db_session.query(AssistantMessage).filter_by(conversation_id=conv.id).count() == 0


def test_search_conversation_history(client: TestClient, db_session: Session):
    """Verify searching conversation titles and messages."""
    user = _get_or_create_user(db_session)
    conv1 = AssistantConversation(user_id=user.id, title="PostgreSQL Schema Discussion")
    conv2 = AssistantConversation(user_id=user.id, title="React Frontend Component")
    db_session.add_all([conv1, conv2])
    db_session.commit()

    # Add message with unique keyword
    msg = AssistantMessage(conversation_id=conv1.id, role="user", content="Where is pgvector configured?")
    db_session.add(msg)
    db_session.commit()

    # Search by title
    res_title = client.get("/api/v1/assistant/conversations?search=PostgreSQL")
    assert res_title.status_code == 200
    assert len(res_title.json()) == 1
    assert res_title.json()[0]["id"] == conv1.id

    # Search by message content
    res_msg = client.get("/api/v1/assistant/conversations?search=pgvector")
    assert res_msg.status_code == 200
    assert len(res_msg.json()) == 1
    assert res_msg.json()[0]["id"] == conv1.id


def test_prevent_cross_user_conversation_access(client: TestClient, db_session: Session):
    """Verify a user cannot read, update, delete, or append to another user's conversation."""
    _get_or_create_user(db_session)

    other_user = User(email="other@user.dev", full_name="Other User", is_active=False)
    db_session.add(other_user)
    db_session.commit()

    foreign_conv = AssistantConversation(user_id=other_user.id, title="Confidential Architecture")
    db_session.add(foreign_conv)
    db_session.commit()

    # Attempt to read
    res_get = client.get(f"/api/v1/assistant/conversations/{foreign_conv.id}")
    assert res_get.status_code == 403

    # Attempt to rename
    res_patch = client.patch(f"/api/v1/assistant/conversations/{foreign_conv.id}", json={"title": "Hacked Title"})
    assert res_patch.status_code == 403

    # Attempt to delete
    res_del = client.delete(f"/api/v1/assistant/conversations/{foreign_conv.id}")
    assert res_del.status_code == 403

    # Attempt to append message
    res_msg = client.post(
        f"/api/v1/assistant/conversations/{foreign_conv.id}/messages",
        json={"content": "Malicious message", "repository_id": 1}
    )
    assert res_msg.status_code in (403, 404)


def test_handle_missing_conversation_id(client: TestClient):
    """Verify proper 404 responses for non-existent conversations."""
    res_get = client.get("/api/v1/assistant/conversations/999999")
    assert res_get.status_code == 404

    res_patch = client.patch("/api/v1/assistant/conversations/999999", json={"title": "New"})
    assert res_patch.status_code == 404

    res_del = client.delete("/api/v1/assistant/conversations/999999")
    assert res_del.status_code == 404


def test_preserve_user_question_if_llm_fails(client: TestClient, db_session: Session, monkeypatch):
    """Verify that if LLM raises a connection or timeout error, the user question is preserved."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="fail-test-repo", full_name="acme/fail-test-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/app.py",
        code_symbol="run",
        chunk_index=0,
        chunk_text="def run(): pass",
        content_hash="h_run",
        language="python",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Failing Conv")
    db_session.add(conv)
    db_session.commit()

    async def mock_generate_llm_error(*args, **kwargs):
        from backend.app.integrations.llm.base import LLMConnectionError
        raise LLMConnectionError("Ollama service unreachable on port 11434")

    monkeypatch.setattr(AssistantService, "_generate_llm_answer", mock_generate_llm_error)

    # Send message to conversation
    res = client.post(
        f"/api/v1/assistant/conversations/{conv.id}/messages",
        json={"content": "Will this fail gracefully?", "repository_id": repo.id}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"

    # User message must be in DB
    msgs = db_session.query(AssistantMessage).filter_by(conversation_id=conv.id).order_by(AssistantMessage.id).all()
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].content == "Will this fail gracefully?"
    assert msgs[1].role == "assistant"
    assert msgs[1].status == "failed"


def test_repository_and_branch_context_preserved(client: TestClient, db_session: Session):
    """Verify repository and branch context is preserved across conversation lifecycle."""
    repo = Repository(name="context-repo", full_name="acme/context-repo", default_branch="develop", status="ready")
    db_session.add(repo)
    db_session.commit()

    res = client.post("/api/v1/assistant/conversations", json={
        "title": "Context Test",
        "repository_id": repo.id,
        "branch": "develop"
    })
    assert res.status_code == 201
    conv_id = res.json()["id"]

    res_get = client.get(f"/api/v1/assistant/conversations/{conv_id}")
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["repository_id"] == repo.id
    assert data["repository_name"] == "context-repo"
    assert data["branch"] == "develop"


def test_deterministic_title_generation():
    """Verify deterministic title generation extracts 3-8 words and cleans conversational filler."""
    t1 = AssistantService.generate_conversation_title("How does Flask handle routing and the Blueprint class?")
    assert "How does" not in t1
    assert "?" not in t1
    assert "Flask" in t1
    assert len(t1.split()) <= 8

    t2 = AssistantService.generate_conversation_title("Where is the Flask application class implemented?")
    assert "Where is" not in t2
    assert "?" not in t2
    assert "Flask" in t2

    t3 = AssistantService.generate_conversation_title("Can you please explain the database migration schema?")
    assert "Can you please" not in t3
    assert "Database migration" in t3 or "database migration" in t3.lower()

    t4 = AssistantService.generate_conversation_title("")
    assert t4 == "New Conversation"


def test_multi_turn_single_conversation_and_history_grouping(client: TestClient, db_session: Session):
    """Verify asking multiple questions in one conversation maintains single conversation ID and exactly 1 history entry."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="grouping-repo", full_name="acme/grouping-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/flask/app.py",
        code_symbol="Flask",
        chunk_index=0,
        chunk_text="class Flask: pass",
        content_hash="h_flask",
        language="python",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    # 1. Create a conversation
    create_res = client.post("/api/v1/assistant/conversations", json={
        "repository_id": repo.id,
        "branch": "main"
    })
    assert create_res.status_code == 201
    conv_id = create_res.json()["id"]

    # 2. Ask 3 questions in the same conversation
    q1 = client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "Where is the Flask application class implemented?",
        "repository_id": repo.id
    })
    assert q1.status_code == 200
    assert q1.json()["conversation_id"] == conv_id

    q2 = client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "How does Flask handle routing and the Blueprint class?",
        "repository_id": repo.id
    })
    assert q2.status_code == 200
    assert q2.json()["conversation_id"] == conv_id

    q3 = client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "Which files define the request and application lifecycle?",
        "repository_id": repo.id
    })
    assert q3.status_code == 200
    assert q3.json()["conversation_id"] == conv_id

    # 3. Verify exactly 1 history entry exists for this conversation in the listing
    list_res = client.get(f"/api/v1/assistant/conversations?repository_id={repo.id}")
    assert list_res.status_code == 200
    conv_items = [c for c in list_res.json() if c["id"] == conv_id]
    assert len(conv_items) == 1
    assert conv_items[0]["messages_count"] == 6

    # 4. Verify all 6 messages exist in chronological order under that single conversation
    detail_res = client.get(f"/api/v1/assistant/conversations/{conv_id}")
    assert detail_res.status_code == 200
    msgs = detail_res.json()["messages"]
    assert len(msgs) == 6
    assert msgs[0]["role"] == "user"
    assert "Where is the Flask application" in msgs[0]["content"]
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "user"
    assert "How does Flask handle routing" in msgs[2]["content"]
    assert msgs[3]["role"] == "assistant"
    assert msgs[4]["role"] == "user"
    assert "Which files define" in msgs[4]["content"]
    assert msgs[5]["role"] == "assistant"


def test_title_is_manual_preservation_across_messages(client: TestClient, db_session: Session):
    """Verify renaming a conversation sets title_is_manual=True and prevents overwriting by subsequent messages."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="manual-title-repo", full_name="acme/manual-title-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/app.py",
        code_symbol="init",
        chunk_index=0,
        chunk_text="def init(): pass",
        content_hash="h_init",
        language="python",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    # Create conversation
    create_res = client.post("/api/v1/assistant/conversations", json={"repository_id": repo.id})
    conv_id = create_res.json()["id"]

    # Manually rename conversation
    rename_res = client.patch(f"/api/v1/assistant/conversations/{conv_id}", json={
        "title": "Core Architecture Deep Dive"
    })
    assert rename_res.status_code == 200
    assert rename_res.json()["title"] == "Core Architecture Deep Dive"
    assert rename_res.json()["title_is_manual"] is True

    # Send first question
    client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "Where is the main entry point defined?",
        "repository_id": repo.id
    })

    # Verify manual title was NOT replaced by automatic question title
    detail_res = client.get(f"/api/v1/assistant/conversations/{conv_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["title"] == "Core Architecture Deep Dive"
    assert detail_res.json()["title_is_manual"] is True

    # Send second question
    client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "How are signals dispatched?",
        "repository_id": repo.id
    })

    detail_res2 = client.get(f"/api/v1/assistant/conversations/{conv_id}")
    assert detail_res2.json()["title"] == "Core Architecture Deep Dive"


def test_automatic_title_generated_once_on_first_message(client: TestClient, db_session: Session):
    """Verify automatic title is generated once from the first question and not updated on follow-ups."""
    user = _get_or_create_user(db_session)
    repo = Repository(name="auto-title-repo", full_name="acme/auto-title-repo", user_id=user.id, status="ready")
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="src/router.py",
        code_symbol="route",
        chunk_index=0,
        chunk_text="def route(): pass",
        content_hash="h_route",
        language="python",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    # Create conversation with default title
    create_res = client.post("/api/v1/assistant/conversations", json={"repository_id": repo.id})
    conv_id = create_res.json()["id"]
    assert create_res.json()["title"] == "New Conversation"
    assert create_res.json()["title_is_manual"] is False

    # Send first question
    client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "How does Flask handle routing and the Blueprint class?",
        "repository_id": repo.id
    })

    first_detail = client.get(f"/api/v1/assistant/conversations/{conv_id}").json()
    first_title = first_detail["title"]
    assert first_title != "New Conversation"
    assert "Flask" in first_title

    # Send follow-up question
    client.post(f"/api/v1/assistant/conversations/{conv_id}/messages", json={
        "content": "Can you explain how url_for works?",
        "repository_id": repo.id
    })

    second_detail = client.get(f"/api/v1/assistant/conversations/{conv_id}").json()
    # Title must remain unchanged from the first question
    assert second_detail["title"] == first_title


def test_delete_conversation_cascades_and_removes_from_history(client: TestClient, db_session: Session):
    """Verify delete endpoint cascades to all messages and removes conversation from listing."""
    user = _get_or_create_user(db_session)
    conv = AssistantConversation(user_id=user.id, title="Conversation to be deleted")
    db_session.add(conv)
    db_session.commit()

    # Add 3 messages with citations metadata
    m1 = AssistantMessage(conversation_id=conv.id, role="user", content="Question 1")
    m2 = AssistantMessage(conversation_id=conv.id, role="assistant", content="Answer 1", citations='[{"file_path": "a.py", "source_index": 1}]')
    m3 = AssistantMessage(conversation_id=conv.id, role="user", content="Question 2")
    db_session.add_all([m1, m2, m3])
    db_session.commit()

    assert db_session.query(AssistantMessage).filter_by(conversation_id=conv.id).count() == 3

    # Delete conversation
    del_res = client.delete(f"/api/v1/assistant/conversations/{conv.id}")
    assert del_res.status_code == 204

    # Verify conversation is gone from DB
    assert db_session.query(AssistantConversation).filter_by(id=conv.id).first() is None

    # Verify messages cascaded and removed
    assert db_session.query(AssistantMessage).filter_by(conversation_id=conv.id).count() == 0

    # Verify listing does not contain deleted conversation
    list_res = client.get("/api/v1/assistant/conversations")
    assert list_res.status_code == 200
    ids = [c["id"] for c in list_res.json()]
    assert conv.id not in ids

    # Verify subsequent GET returns 404
    get_res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert get_res.status_code == 404


def test_delete_other_user_conversation_forbidden(client: TestClient, db_session: Session):
    """Verify a user cannot delete another user's conversation (403 Forbidden)."""
    _get_or_create_user(db_session)

    other = User(email="other2@user.dev", full_name="Other User 2", is_active=False)
    db_session.add(other)
    db_session.commit()

    other_conv = AssistantConversation(user_id=other.id, title="Other's Secret Chat")
    db_session.add(other_conv)
    db_session.commit()

    other_msg = AssistantMessage(conversation_id=other_conv.id, role="user", content="Private question")
    db_session.add(other_msg)
    db_session.commit()

    # Attempt to delete foreign conversation
    res = client.delete(f"/api/v1/assistant/conversations/{other_conv.id}")
    assert res.status_code == 403

    # Verify foreign conversation and messages were NOT deleted
    assert db_session.query(AssistantConversation).filter_by(id=other_conv.id).first() is not None
    assert db_session.query(AssistantMessage).filter_by(conversation_id=other_conv.id).count() == 1


def test_delete_conversation_preserves_active_and_other_conversations(client: TestClient, db_session: Session):
    """Verify deleting one conversation leaves other conversations and active chats completely intact."""
    user = _get_or_create_user(db_session)

    active_conv = AssistantConversation(user_id=user.id, title="Active Chat Conversation")
    unrelated_conv = AssistantConversation(user_id=user.id, title="Unrelated Stale Conversation")
    db_session.add_all([active_conv, unrelated_conv])
    db_session.commit()

    active_msg = AssistantMessage(conversation_id=active_conv.id, role="user", content="Active query")
    unrelated_msg = AssistantMessage(conversation_id=unrelated_conv.id, role="user", content="Old query")
    db_session.add_all([active_msg, unrelated_msg])
    db_session.commit()

    # Delete unrelated conversation
    del_res = client.delete(f"/api/v1/assistant/conversations/{unrelated_conv.id}")
    assert del_res.status_code == 204

    # Verify unrelated is deleted
    assert db_session.query(AssistantConversation).filter_by(id=unrelated_conv.id).first() is None
    assert db_session.query(AssistantMessage).filter_by(conversation_id=unrelated_conv.id).count() == 0

    # Verify active conversation is completely preserved with all its messages
    preserved = db_session.query(AssistantConversation).filter_by(id=active_conv.id).first()
    assert preserved is not None
    assert preserved.title == "Active Chat Conversation"
    assert db_session.query(AssistantMessage).filter_by(conversation_id=active_conv.id).count() == 1


def test_delete_nonexistent_conversation_returns_404(client: TestClient, db_session: Session):
    """Verify deleting a nonexistent conversation returns 404."""
    _get_or_create_user(db_session)
    res = client.delete("/api/v1/assistant/conversations/9999999")
    assert res.status_code == 404


