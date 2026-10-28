import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.user import User
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.assistant_service import AssistantService


@pytest.fixture
def p51_user(db_session: Session) -> User:
    user = db_session.query(User).filter(User.email == "test_phase51@codemind.dev").first()
    if not user:
        user = User(
            email="test_phase51@codemind.dev",
            full_name="Phase 5.1 Test User",
            workspace_name="Phase 5.1 Workspace",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
    return user


# =========================================================================
# Issue 1: Explicit File-Path Retrieval & Repository Isolation Tests
# =========================================================================
@pytest.mark.anyio
async def test_explicit_file_path_prioritization(db_session: Session, p51_user: User):
    """
    Verifies that when a question explicitly mentions a file (e.g. `indexing_service.py`),
    retrieval prioritizes chunks from that file and includes complete functions/ranges.
    """
    repo = Repository(name="indexer-app", full_name="org/indexer-app", user_id=p51_user.id)
    db_session.add(repo)
    db_session.commit()

    f_generic = IndexedFile(repository_id=repo.id, path="backend/app/db/session.py", lines_count=50)
    f_target = IndexedFile(repository_id=repo.id, path="backend/app/services/indexing_service.py", lines_count=120)
    db_session.add_all([f_generic, f_target])
    db_session.commit()

    # Generic session chunk with high keyword match for "session"
    c_generic = CodeChunk(
        repository_id=repo.id,
        file_id=f_generic.id,
        file_path="backend/app/db/session.py",
        code_symbol="get_db",
        chunk_index=0,
        chunk_text=(
            "def get_db():\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        yield db\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        content_hash="h_db_session",
        language="python",
        start_line=20,
        end_line=30,
    )

    # Explicit target file chunk with transaction & incremental indexing logic
    c_target = CodeChunk(
        repository_id=repo.id,
        file_id=f_target.id,
        file_path="backend/app/services/indexing_service.py",
        code_symbol="execute_incremental_indexing",
        chunk_index=0,
        chunk_text=(
            "def execute_incremental_indexing(repo_id: int, db: Session):\n"
            "    # Manage database sessions and transactions during incremental indexing\n"
            "    try:\n"
            "        db.commit()\n"
            "    except Exception:\n"
            "        db.rollback()\n"
            "        raise\n"
        ),
        content_hash="h_idx_svc",
        language="python",
        start_line=45,
        end_line=75,
    )
    db_session.add_all([c_generic, c_target])
    db_session.commit()

    # Query explicitly mentioning indexing_service.py
    query = "How are database sessions and transactions managed during incremental indexing in `indexing_service.py`?"
    chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo.id,
        query=query,
        user_id=p51_user.id,
        top_k=5,
    )

    assert len(chunks) >= 1
    # Target file chunk must be retrieved and ranked at the top
    top_chunk = chunks[0]
    assert top_chunk.file_path == "backend/app/services/indexing_service.py"
    assert "execute_incremental_indexing" in (top_chunk.symbol_name or top_chunk.chunk_text)


@pytest.mark.anyio
async def test_explicit_file_repository_isolation(db_session: Session, p51_user: User):
    """
    Verifies that explicit file paths in repo B are never leaked when querying repo A.
    """
    repo_a = Repository(name="isolated-repo-a", full_name="org/isolated-repo-a", user_id=p51_user.id)
    repo_b = Repository(name="isolated-repo-b", full_name="org/isolated-repo-b", user_id=p51_user.id)
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    f_b = IndexedFile(repository_id=repo_b.id, path="services/indexing_service.py", lines_count=60)
    db_session.add(f_b)
    db_session.commit()

    c_b = CodeChunk(
        repository_id=repo_b.id,
        file_id=f_b.id,
        file_path="services/indexing_service.py",
        chunk_index=0,
        chunk_text="def repo_b_secret_indexer(): return True",
        content_hash="h_b_secret",
        language="python",
        start_line=1,
        end_line=10,
    )
    db_session.add(c_b)
    db_session.commit()

    # Query repo A asking for indexing_service.py: must NOT return repo B chunk
    chunks_a = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo_a.id,
        query="Explain transactions in `indexing_service.py`",
        user_id=p51_user.id,
        top_k=5,
    )
    assert not any(c.repository_id == repo_b.id for c in chunks_a)
    assert not any("repo_b_secret" in c.chunk_text for c in chunks_a)


@pytest.mark.anyio
async def test_explicit_file_missing_clarification_no_absent_conclusion(db_session: Session, p51_user: User):
    """
    If the explicitly requested file does not exist, the assistant notes the file is absent/unindexed,
    without asserting that the entire feature is absent from the project.
    """
    repo = Repository(name="cli-tool", full_name="org/cli-tool", user_id=p51_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="main.py", lines_count=20)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="main.py", chunk_index=0,
        chunk_text="print('CLI tool started')\n", content_hash="h_cli_main", language="python", start_line=1, end_line=5
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain how transactions are committed in `nonexistent_service.py`.",
        user_id=p51_user.id,
    )

    answer = res["answer"].lower()
    # Explicitly reports file not found/not indexed
    assert "nonexistent_service.py" in answer
    assert "not exist" in answer or "not indexed" in answer or "not found" in answer or "unverified" in answer
    # Unknowns must be incremented because explicit file was missing
    assert res["facts"]["unknowns"] >= 1


# =========================================================================
# Issue 2: Evidence Counter Consistency Tests (False-Zero & False-Positive)
# =========================================================================
@pytest.mark.anyio
async def test_counter_indeterminate_evidence_increments_unknowns(db_session: Session, p51_user: User):
    """
    Regression Test (False-Zero Fix):
    When the answer states that requested information (e.g. CDN edge caching or SSL renewal)
    cannot be determined from available evidence, `unknowns` must be >= 1.
    """
    repo = Repository(name="edge-service", full_name="org/edge-service", user_id=p51_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="main.py", lines_count=30)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="main.py", chunk_index=0,
        chunk_text="from fastapi import FastAPI\napp = FastAPI()\n",
        content_hash="h_edge_main", language="python", start_line=1, end_line=10
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="How does this project handle external production CDN edge caching and SSL certificate renewal?",
        user_id=p51_user.id,
    )

    answer = res["answer"].lower()
    assert (
        "cannot be determined" in answer
        or "does not contain" in answer
        or "not found" in answer
        or "no information" in answer
        or "unverified" in answer
        or "no evidence" in answer
        or "no identifiers" in answer
        or "does not handle" in answer
        or "does not have any specific handling" in answer
    )
    # Must NOT be zero when requested information cannot be determined
    assert res["facts"]["unknowns"] >= 1


@pytest.mark.anyio
async def test_counter_complete_supported_answer_preserves_zero_unknowns(db_session: Session, p51_user: User):
    """
    Regression Test (False-Positive Fix):
    A complete, fully supported programming explanation of an exception handler that contains
    phrases such as 'Transaction not found' or 'not found in rates' must retain `unknowns == 0`.
    """
    repo = Repository(name="wallet-service", full_name="org/wallet-service", user_id=p51_user.id)
    db_session.add(repo)
    db_session.commit()

    f = IndexedFile(repository_id=repo.id, path="services/payment.py", lines_count=40)
    db_session.add(f)
    db_session.commit()
    db_session.add(CodeChunk(
        repository_id=repo.id, file_id=f.id, file_path="services/payment.py", chunk_index=0,
        code_symbol="process_refund",
        chunk_text=(
            "def process_refund(tx_id: str, amount: float):\n"
            "    tx = get_transaction(tx_id)\n"
            "    if tx is None:\n"
            "        raise ValueError(f'Transaction {tx_id} not found')\n"
            "    if amount > tx.amount:\n"
            "        raise ValueError('Refund amount exceeds original charge')\n"
            "    return execute_gateway_refund(tx.gateway_id, amount)\n"
        ),
        content_hash="h_refund_p51", language="python", start_line=1, end_line=15
    ))
    db_session.commit()

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Why would `process_refund` in `services/payment.py` raise a ValueError?",
        user_id=p51_user.id,
    )

    answer = res["answer"].lower()
    assert "valueerror" in answer
    # Citations exist and evidence is complete
    assert len(res["citations"]) >= 1
    assert res["citations"][0]["file_path"] == "services/payment.py"
    assert res["facts"]["confirmed"] >= 1
    # Unknowns must be exactly 0 because no repository evidence is missing
    assert res["facts"]["unknowns"] == 0
