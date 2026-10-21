import asyncio
import pytest
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.user import User
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.core.config import settings


def test_hybrid_retrieval_exact_and_keyword(db_session: Session, monkeypatch):
    """Verify hybrid retrieval matches exact symbols and keywords with valid scores."""
    # Ensure mock provider is active for unit testing
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "mock")

    repo = Repository(name="retrieval-repo", full_name="acme/retrieval-repo", is_private=False)
    db_session.add(repo)
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id,
        file_path="src/auth.py",
        code_symbol="validate_session",
        chunk_index=0,
        chunk_text="def validate_session(token):\n    # Core session verification\n    return verify(token)",
        content_hash="h1",
        language="python",
        start_line=10,
        end_line=13,
    )
    c2 = CodeChunk(
        repository_id=repo.id,
        file_path="src/billing.py",
        code_symbol="process_payment",
        chunk_index=0,
        chunk_text="def process_payment(amount):\n    # Stripe billing handler\n    return charge(amount)",
        content_hash="h2",
        language="python",
        start_line=20,
        end_line=23,
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # Query for "validate_session"
    results = asyncio.run(HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo.id,
        query="validate_session",
        top_k=5,
    ))

    assert len(results) >= 1
    top = results[0]
    assert top.symbol_name == "validate_session"
    assert top.file_path == "src/auth.py"
    assert top.start_line == 10
    assert top.end_line == 13
    assert top.score > 0.0


def test_retrieval_authorization_enforcement(db_session: Session):
    """Verify hybrid engine prevents unauthorized users from retrieving code from private repos."""
    user1 = User(email="owner@acme.dev", full_name="Owner", workspace_name="Acme", is_active=True)
    user2 = User(email="intruder@other.dev", full_name="Intruder", workspace_name="Other", is_active=True)
    db_session.add_all([user1, user2])
    db_session.commit()

    repo = Repository(name="secret-repo", full_name="acme/secret-repo", user_id=user1.id, is_private=True)
    db_session.add(repo)
    db_session.commit()

    chunk = CodeChunk(
        repository_id=repo.id,
        file_path="secret.py",
        chunk_index=0,
        chunk_text="API_SECRET_KEY = 'secret'",
        content_hash="sec1",
        start_line=1,
        end_line=2,
    )
    db_session.add(chunk)
    db_session.commit()

    # User 2 attempts retrieval -> must return empty list
    results = asyncio.run(HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo.id,
        query="API_SECRET_KEY",
        user_id=user2.id,
    ))

    assert results == []

    # User 1 attempts retrieval -> returns matching chunk
    results_owner = asyncio.run(HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo.id,
        query="API_SECRET_KEY",
        user_id=user1.id,
    ))
    assert len(results_owner) == 1
    assert results_owner[0].file_path == "secret.py"
