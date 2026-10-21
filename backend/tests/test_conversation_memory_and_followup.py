import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock
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


def _get_or_create_user(db: Session, email="memory_tester@acme.dev") -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, full_name="Memory Tester", workspace_name="Acme", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _seed_sample_repo(db: Session, name="TokenPool", user_id=None):
    if user_id is None:
        user = _get_or_create_user(db)
        user_id = user.id
    repo = Repository(name=name, full_name=f"acme/{name}", user_id=user_id, status="ready")
    db.add(repo)
    db.commit()

    f1 = IndexedFile(repository_id=repo.id, path="src/auth/service.py", lines_count=20)
    f2 = IndexedFile(repository_id=repo.id, path="src/auth/security.py", lines_count=30)
    f3 = IndexedFile(repository_id=repo.id, path="src/api/routes.py", lines_count=45)
    db.add_all([f1, f2, f3])
    db.commit()

    chunk1 = CodeChunk(
        repository_id=repo.id,
        file_id=f1.id,
        file_path="src/auth/service.py",
        code_symbol="login",
        chunk_index=0,
        chunk_text="def login(username, password):\n    user = find_user(username)\n    if not verify_password(password, user.hashed_pw):\n        raise AuthError('Invalid')\n    return generate_token(user)\n",
        content_hash=f"h_login_srv_{name}",
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
        chunk_text="def verify_password(plain, hashed):\n    return bcrypt.checkpw(plain.encode('utf-8'), hashed)\n",
        content_hash=f"h_sec_pw_{name}",
        language="python",
        start_line=15,
        end_line=25,
    )
    chunk3 = CodeChunk(
        repository_id=repo.id,
        file_id=f3.id,
        file_path="src/api/routes.py",
        code_symbol="login_route",
        chunk_index=2,
        chunk_text="@router.post('/login')\ndef login_endpoint(payload):\n    return login(payload.username, payload.password)\n",
        content_hash=f"h_login_route_{name}",
        language="python",
        start_line=30,
        end_line=40,
    )
    db.add_all([chunk1, chunk2, chunk3])
    db.commit()

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
        start_line=15,
        end_line=25,
    )
    sym3 = CodeSymbol(
        repository_id=repo.id,
        file_id=f3.id,
        name="login_endpoint",
        kind="function",
        start_line=30,
        end_line=40,
    )
    db.add_all([sym1, sym2, sym3])
    db.commit()

    return repo


@pytest.mark.anyio
async def test_follow_up_pronoun_resolution_where_password_checked(db_session: Session):
    """Verify follow-up question 'Where is the password checked?' resolves to verify_password in previous login turn."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "TokenPool", user.id)

    # 1. Turn 1: User asks about login flow
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the login flow in TokenPool.",
        user_id=user.id,
    )
    conv_id = res1["conversation_id"]
    assert conv_id is not None
    assert len(res1["citations"]) >= 1

    # 2. Turn 2: Follow-up question referring to password check
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Where is the password checked?",
        conversation_id=conv_id,
        user_id=user.id,
    )
    assert res2["conversation_id"] == conv_id
    c_paths = [c["file_path"] for c in res2["citations"]]
    assert any("security.py" in p or "service.py" in p for p in c_paths)


@pytest.mark.anyio
async def test_follow_up_call_hierarchy_who_calls_that_function(db_session: Session):
    """Verify follow-up 'Who calls that function?' resolves callers using CallHierarchyService."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "TokenPool", user.id)

    # Turn 1: Explain verify_password
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain verify_password in TokenPool.",
        user_id=user.id,
    )
    conv_id = res1["conversation_id"]

    # Turn 2: Follow-up 'Who calls it?'
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Who calls that function?",
        conversation_id=conv_id,
        user_id=user.id,
    )
    assert res2["conversation_id"] == conv_id
    # Callers of verify_password should include login in service.py
    answer_text = res2["answer"]
    assert "login" in answer_text or "verify_password" in answer_text


@pytest.mark.anyio
async def test_explicit_repository_change_overrides_old_context(db_session: Session):
    """Verify switching repository ID prevents using source chunks from the previous repository."""
    user = _get_or_create_user(db_session)
    repo1 = _seed_sample_repo(db_session, "RepoAlpha", user.id)

    # Create RepoBeta with distinct symbols
    repo2 = Repository(name="RepoBeta", full_name="acme/RepoBeta", user_id=user.id, status="ready")
    db_session.add(repo2)
    db_session.commit()

    chunk_beta = CodeChunk(
        repository_id=repo2.id,
        file_path="beta/engine.py",
        code_symbol="process_decision",
        chunk_index=0,
        chunk_text="def process_decision(data):\n    return data.run()\n",
        content_hash="h_beta",
        language="python",
        start_line=1,
        end_line=5,
    )
    db_session.add(chunk_beta)
    db_session.commit()

    # Turn 1 on RepoAlpha
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo1.id,
        question="Explain login flow",
        user_id=user.id,
    )
    conv_id = res1["conversation_id"]

    # Turn 2: explicitly pass repo2 (RepoBeta)
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo2.id,
        question="Explain process_decision",
        conversation_id=conv_id,
        user_id=user.id,
    )
    assert res2["repository_id"] == repo2.id
    assert len(res2["citations"]) >= 1
    for citation in res2["citations"]:
        assert "beta/engine.py" in citation["file_path"]


@pytest.mark.anyio
async def test_conversation_persistence_and_ordering(db_session: Session):
    """Verify that multiple turns are stored in exact chronological order in the database."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "OrderRepo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Chronological Test")
    db_session.add(conv)
    db_session.commit()

    # Add 3 user questions and answers
    for i in range(1, 4):
        await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question=f"Question number {i}",
            conversation_id=conv.id,
            user_id=user.id,
        )

    # Reload conversation and verify ordering
    detail = AssistantService.get_conversation_detail(db=db_session, conversation_id=conv.id, user_id=user.id)
    messages = detail["messages"]
    assert len(messages) == 6

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Question number 1"
    assert messages[1]["role"] == "assistant"

    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "Question number 2"
    assert messages[3]["role"] == "assistant"

    assert messages[4]["role"] == "user"
    assert messages[4]["content"] == "Question number 3"
    assert messages[5]["role"] == "assistant"


@pytest.mark.anyio
async def test_reloading_conversation_after_simulated_refresh(client: TestClient, db_session: Session):
    """Verify GET /api/v1/assistant/conversations/{id} reloads stored messages with citations and metadata."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "ReloadRepo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Reload Test")
    db_session.add(conv)
    db_session.commit()

    m1 = AssistantMessage(conversation_id=conv.id, role="user", content="Where is login defined?")
    m2 = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content="`login` is defined in `src/auth/service.py:1-10`.",
        citations=json.dumps([{"file_path": "src/auth/service.py", "symbol_name": "login", "start_line": 1, "end_line": 10}]),
        status="success"
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    # Simulate browser page refresh: client calls GET /assistant/conversations/{id}
    res = client.get(f"/api/v1/assistant/conversations/{conv.id}")
    assert res.status_code == 200
    data = res.json()

    assert data["id"] == conv.id
    assert data["title"] == "Reload Test"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Where is login defined?"
    assert data["messages"][1]["content"] == "`login` is defined in `src/auth/service.py:1-10`."
    assert len(data["messages"][1]["citations"]) == 1
    assert data["messages"][1]["citations"][0]["symbol_name"] == "login"


def test_conversation_owner_isolation(client: TestClient, db_session: Session):
    """Verify that user B cannot view, modify, or append messages to user A's conversation."""
    userA = _get_or_create_user(db_session, "userA@acme.dev")
    userB = _get_or_create_user(db_session, "userB@acme.dev")

    convA = AssistantConversation(user_id=userA.id, title="User A Private Conv")
    db_session.add(convA)
    db_session.commit()

    # Using service directly with userB ID should raise 403
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        AssistantService.get_conversation_record(db=db_session, conversation_id=convA.id, user_id=userB.id)
    assert excinfo.value.status_code == 403


@pytest.mark.anyio
async def test_new_conversation_isolation(db_session: Session):
    """Verify a newly created conversation does not inherit symbol references or history from an existing conversation."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "IsoRepo", user.id)

    # Conv 1: Discuss login
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain login flow",
        user_id=user.id,
    )
    conv1_id = res1["conversation_id"]

    # Conv 2: Brand new conversation
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What does the project do?",
        user_id=user.id,
    )
    conv2_id = res2["conversation_id"]

    assert conv1_id != conv2_id

    # Messages in conv 2 should be exactly 2
    msgs2 = db_session.query(AssistantMessage).filter_by(conversation_id=conv2_id).all()
    assert len(msgs2) == 2


@pytest.mark.anyio
async def test_failed_or_cancelled_generation_status(db_session: Session):
    """Verify failed or cancelled messages are properly tracked with status in DB."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "FailRepo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Fail Status Conv")
    db_session.add(conv)
    db_session.commit()

    failed_msg = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content="Error connecting to model",
        status="failed"
    )
    db_session.add(failed_msg)
    db_session.commit()

    reloaded = db_session.query(AssistantMessage).filter_by(id=failed_msg.id).first()
    assert reloaded.status == "failed"


@pytest.mark.anyio
async def test_conversation_summary_mechanism(db_session: Session):
    """Verify conversation summary is generated and saved when conversation history turn limit is exceeded."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "SummaryRepo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Summary Conv")
    db_session.add(conv)
    db_session.commit()

    # Add 4 turns (8 messages) so history exceeds 3 turns
    for i in range(1, 5):
        m_u = AssistantMessage(conversation_id=conv.id, role="user", content=f"User question {i} about auth symbol {i}")
        m_a = AssistantMessage(conversation_id=conv.id, role="assistant", content=f"Answer {i} explaining component {i}", status="success")
        db_session.add_all([m_u, m_a])
    db_session.commit()

    # Now ask question 5
    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Follow-up on auth",
        conversation_id=conv.id,
        user_id=user.id,
    )

    db_session.refresh(conv)
    # Conv summary should now be populated
    assert conv.summary is not None
    assert "User question" in conv.summary or "Summary" in conv.summary or len(conv.summary) > 0


@pytest.mark.anyio
async def test_context_truncation_preserves_current_question(db_session: Session):
    """Verify that multi-turn history bounding keeps the current question intact without overflow."""
    user = _get_or_create_user(db_session)
    repo = _seed_sample_repo(db_session, "TruncRepo", user.id)

    conv = AssistantConversation(user_id=user.id, repository_id=repo.id, title="Trunc Conv")
    db_session.add(conv)
    db_session.commit()

    # Add a huge previous message
    huge_text = "x" * 2000
    m1 = AssistantMessage(conversation_id=conv.id, role="user", content="Earlier huge query")
    m2 = AssistantMessage(conversation_id=conv.id, role="assistant", content=huge_text, status="success")
    db_session.add_all([m1, m2])
    db_session.commit()

    # Test resolving context
    follow_up = AssistantService._resolve_follow_up_context(
        db=db_session,
        repository_id=repo.id,
        conversation_id=conv.id,
        question="Specific new question",
    )

    turns = follow_up["history_turns"]
    assert len(turns) == 2
    # Ensure assistant message was bounded/truncated to <= 520 chars
    assert len(turns[1]["content"]) <= 520
    assert "..." in turns[1]["content"]
