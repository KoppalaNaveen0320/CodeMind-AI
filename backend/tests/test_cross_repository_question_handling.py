import asyncio
import hashlib
import json
import uuid
import pytest
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService


# ==============================================================================
# Helper Factories
# ==============================================================================

def create_test_user(db: Session, email: str = "cross_repo_user@example.com") -> User:
    user = User(email=email, full_name="Cross Repo User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_chunk(
    repository_id: int,
    file_path: str,
    chunk_index: int,
    start_line: int,
    end_line: int,
    chunk_text: str,
    code_symbol: str = None,
    language: str = "python"
) -> CodeChunk:
    return CodeChunk(
        repository_id=repository_id,
        file_path=file_path,
        chunk_index=chunk_index,
        start_line=start_line,
        end_line=end_line,
        chunk_text=chunk_text,
        content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        code_symbol=code_symbol,
        language=language,
    )


def setup_fincell_and_codemind_repos(db: Session, user: User):
    """Sets up FinCell and CodeMind-AI repositories in the test database."""
    fincell = Repository(
        name="FinCell",
        full_name="testorg/fincell",
        status="ready",
        files_count=10,
        default_branch="main",
        user_id=user.id,
    )
    codemind = Repository(
        name="CodeMind-AI",
        full_name="KoppalaNaveen0320/CodeMind-AI",
        status="ready",
        files_count=50,
        default_branch="main",
        user_id=user.id,
    )
    db.add_all([fincell, codemind])
    db.commit()
    db.refresh(fincell)
    db.refresh(codemind)

    # FinCell files (Flutter mobile app without retrieval engine)
    f_pub = IndexedFile(repository_id=fincell.id, path="pubspec.yaml", language="yaml", lines_count=40)
    f_main = IndexedFile(repository_id=fincell.id, path="lib/main.dart", language="dart", lines_count=60)
    db.add_all([f_pub, f_main])
    db.commit()

    c_pub = make_chunk(
        repository_id=fincell.id,
        file_path="pubspec.yaml",
        chunk_index=0,
        start_line=1,
        end_line=40,
        chunk_text="name: fincell\ndependencies:\n  flutter:\n    sdk: flutter\n  dio: ^5.0.0\n",
        language="yaml",
    )
    c_main = make_chunk(
        repository_id=fincell.id,
        file_path="lib/main.dart",
        chunk_index=0,
        start_line=1,
        end_line=60,
        chunk_text="void main() => runApp(const FinCellApp());\nclass FinCellApp extends StatelessWidget {}\n",
        code_symbol="FinCellApp",
        language="dart",
    )
    db.add_all([c_pub, c_main])
    db.commit()

    # CodeMind-AI files (Contains HybridRetrievalEngine)
    f_engine = IndexedFile(repository_id=codemind.id, path="backend/app/retrieval/hybrid_engine.py", language="python", lines_count=200)
    db.add(f_engine)
    db.commit()

    c_engine = make_chunk(
        repository_id=codemind.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        chunk_index=0,
        start_line=1,
        end_line=100,
        chunk_text=(
            "class HybridRetrievalEngine:\n"
            "    # Multi-channel retrieval combining vector embeddings and keyword search\n"
            "    async def retrieve(cls, db, repository_id, query):\n"
            "        vector_matches = await cls._retrieve_vector_matches(db, repository_id, query)\n"
            "        keyword_matches = cls._retrieve_keyword_matches(db, repository_id, query)\n"
            "        return cls._rank_fusion(vector_matches, keyword_matches)\n"
        ),
        code_symbol="HybridRetrievalEngine",
        language="python",
    )
    db.add(c_engine)
    db.commit()

    return fincell, codemind


# ==============================================================================
# Tests
# ==============================================================================

@pytest.mark.anyio
async def test_ask_about_fincell_while_bound_to_fincell(db_session: Session):
    """
    When bound to FinCell and asking about FinCell,
    the assistant must answer normally using FinCell's source evidence
    (identifying that FinCell does not implement hybrid retrieval).
    """
    db = db_session
    user = create_test_user(db, "fincell_self@example.com")
    fincell, codemind = setup_fincell_and_codemind_repos(db, user)

    response = await AssistantService.answer_question(
        db=db,
        repository_id=fincell.id,
        question="Does FinCell implement a hybrid retrieval engine?",
        user_id=user.id,
    )

    assert response["status"] == "success"
    assert response["repository_id"] == fincell.id
    # Must NOT be a repository mismatch clarification
    assert response["retrieval_strategy"] != "repository_mismatch_clarification"
    # Genuinely absent feature in FinCell
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in response["answer"]
    assert response["facts"]["confirmed"] >= 1
    assert response["facts"]["unknowns"] == 0


@pytest.mark.anyio
async def test_ask_about_codemind_while_bound_to_codemind(db_session: Session):
    """
    When bound to CodeMind-AI and asking about CodeMind-AI,
    the assistant must answer normally using CodeMind-AI's source evidence
    (identifying hybrid_engine.py and its implementation).
    """
    db = db_session
    user = create_test_user(db, "codemind_self@example.com")
    fincell, codemind = setup_fincell_and_codemind_repos(db, user)

    response = await AssistantService.answer_question(
        db=db,
        repository_id=codemind.id,
        question="Explain how CodeMind AI implements hybrid retrieval",
        user_id=user.id,
    )

    assert response["status"] == "success"
    assert response["repository_id"] == codemind.id
    # Must NOT be a repository mismatch clarification
    assert response["retrieval_strategy"] != "repository_mismatch_clarification"
    # Evidence from CodeMind-AI must be cited
    cit_paths = [c["file_path"] for c in response["citations"]]
    assert any("hybrid_engine.py" in p for p in cit_paths)
    assert not any("pubspec.yaml" in p for p in cit_paths)


@pytest.mark.anyio
async def test_ask_explicitly_about_codemind_while_bound_to_fincell(db_session: Session):
    """
    When the conversation is bound to FinCell and the user explicitly asks about CodeMind AI,
    the assistant must NOT answer as though it only asks about FinCell,
    must NOT claim CodeMind AI lacks the feature,
    and must return a clear repository-mismatch clarification instructing the user to select CodeMind-AI.
    """
    db = db_session
    user = create_test_user(db, "cross_repo_test@example.com")
    fincell, codemind = setup_fincell_and_codemind_repos(db, user)

    response = await AssistantService.answer_question(
        db=db,
        repository_id=fincell.id,
        question="Explain how CodeMind AI implements hybrid retrieval",
        user_id=user.id,
    )

    assert response["status"] == "success"
    assert response["repository_id"] == fincell.id
    assert response["retrieval_strategy"] == "repository_mismatch_clarification"

    answer = response["answer"]
    # 1. Clear mismatch clarification
    assert "Repository Context Mismatch" in answer
    assert "FinCell" in answer
    assert "CodeMind-AI" in answer
    assert "Select **CodeMind-AI**" in answer or "select CodeMind-AI" in answer.lower()
    assert "Start a new conversation" in answer or "start a new conversation" in answer.lower()

    # 2. Must NEVER claim CodeMind-AI lacks the feature
    assert "NOT_FOUND_IN_INDEXED_SOURCE" not in answer
    assert "UNVERIFIED / ABSENT" not in answer
    assert "does not implement" not in answer.lower()

    # 3. Citations must be empty (strict repository isolation)
    assert response["citations"] == []
    # 4. Counters: not reported as a negative finding
    assert response["facts"]["unknowns"] == 0
    assert response["facts"]["confirmed"] == 0


@pytest.mark.anyio
async def test_ask_about_unknown_repository(db_session: Session):
    """
    When the user asks about an unknown / unindexed repository,
    the assistant returns a clear clarification explaining that the requested repository
    is not the currently bound repository and is not indexed.
    """
    db = db_session
    user = create_test_user(db, "unknown_repo@example.com")
    fincell, codemind = setup_fincell_and_codemind_repos(db, user)

    response = await AssistantService.answer_question(
        db=db,
        repository_id=fincell.id,
        question="How does repository kubernetes/kubernetes implement container scheduling?",
        user_id=user.id,
    )

    assert response["status"] == "success"
    assert response["retrieval_strategy"] == "repository_mismatch_clarification"

    answer = response["answer"]
    assert "Repository Context Mismatch" in answer
    assert "FinCell" in answer
    assert "kubernetes/kubernetes" in answer
    assert "not currently indexed" in answer.lower() or "not indexed" in answer.lower()

    # Must not claim kubernetes lacks scheduling
    assert "NOT_FOUND_IN_INDEXED_SOURCE" not in answer
    assert response["citations"] == []
    assert response["facts"]["unknowns"] == 0


@pytest.mark.anyio
async def test_switching_repositories_does_not_reuse_conversation_id(db_session: Session):
    """
    When switching repositories, the previous conversation ID must NOT be reused.
    A fresh conversation bound to the new repository must be created.
    """
    db = db_session
    user = create_test_user(db, "switch_reuse@example.com")
    fincell, codemind = setup_fincell_and_codemind_repos(db, user)

    # 1. Start a conversation on FinCell
    res_fincell = await AssistantService.answer_question(
        db=db,
        repository_id=fincell.id,
        question="What is the entry point of FinCell?",
        user_id=user.id,
    )
    fincell_conv_id = res_fincell["conversation_id"]

    # 2. Switch to CodeMind-AI and pass fincell_conv_id
    res_codemind = await AssistantService.answer_question(
        db=db,
        repository_id=codemind.id,
        question="Where is hybrid retrieval implemented in CodeMind-AI?",
        user_id=user.id,
        conversation_id=fincell_conv_id,
    )

    # The previous conversation ID must NOT be reused
    codemind_conv_id = res_codemind["conversation_id"]
    assert codemind_conv_id != fincell_conv_id

    # The original FinCell conversation must remain bound to FinCell
    orig_conv = db.query(AssistantConversation).filter(AssistantConversation.id == fincell_conv_id).first()
    assert orig_conv.repository_id == fincell.id

    # The new conversation must be bound to CodeMind-AI
    new_conv = db.query(AssistantConversation).filter(AssistantConversation.id == codemind_conv_id).first()
    assert new_conv.repository_id == codemind.id


@pytest.mark.anyio
async def test_streaming_cross_repository_clarification_parity(db_session: Session):
    """
    Verifies that streaming (stream_answer_question) produces the identical
    repository-mismatch clarification with citation: [] and facts unknowns == 0.
    """
    db = db_session
    user = create_test_user(db, "streaming_cross@example.com")
    fincell, codemind = setup_fincell_and_codemind_repos(db, user)

    events = []
    async for chunk in AssistantService.stream_answer_question(
        db=db,
        repository_id=fincell.id,
        question="Explain how CodeMind AI implements hybrid retrieval",
        user_id=user.id,
    ):
        lines = chunk.strip().split("\n")
        event_type = None
        event_data = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line.replace("event: ", "").strip()
            elif line.startswith("data: "):
                try:
                    event_data = json.loads(line.replace("data: ", "").strip())
                except Exception:
                    event_data = line.replace("data: ", "").strip()
        if event_type:
            events.append((event_type, event_data))

    event_types = [e[0] for e in events]
    assert "meta" in event_types
    assert "citation" in event_types
    assert "token" in event_types
    assert "done" in event_types

    citation_event = next(e[1] for e in events if e[0] == "citation")
    assert citation_event["citations"] == []

    done_event = next(e[1] for e in events if e[0] == "done")
    assert done_event["repository_id"] == fincell.id
    assert done_event["retrieval_strategy"] == "repository_mismatch_clarification"
    assert "Repository Context Mismatch" in done_event["answer"]
    assert "NOT_FOUND_IN_INDEXED_SOURCE" not in done_event["answer"]
    assert done_event["facts"]["unknowns"] == 0
    assert done_event["facts"]["confirmed"] == 0
