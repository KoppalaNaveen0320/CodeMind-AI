import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from backend.app.db.session import SessionLocal
from backend.app.models.repository import Repository
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService, RetrievedChunk
from backend.app.integrations.llm.ollama_provider import OllamaLLMProvider
from backend.app.integrations.llm.base import LLMTimeoutError, LLMError
from backend.app.core.config import settings


# 1. A claim that conflicts with the actual source code is sanitized
def test_claim_conflicts_with_actual_source_code():
    chunks = [
        RetrievedChunk(
            chunk_id=1,
            file_path="backend/app/main.py",
            symbol_name="app",
            start_line=1,
            end_line=35,
            chunk_text="from fastapi import FastAPI\napp = FastAPI()\n",
            score=0.95,
            channels=["vector"],
            repository_id=1,
        )
    ]
    raw_response = (
        "In this project, app/main.py is likely the entry point of the application. "
        "Also, get_db is likely defined there. The router is likely initialized in main."
    )
    sanitized = AssistantService._validate_and_sanitize_answer(raw_response, chunks, "TestRepo")
    assert "likely the entry point" not in sanitized
    assert "likely defined there" not in sanitized
    assert "likely initialized" not in sanitized
    assert "is the entry point verified in the codebase" in sanitized


# 2. A function name appearing in multiple files without a verified call relationship
def test_function_name_in_multiple_files_without_call_relationship(db_session):
    repo = Repository(name="RepoCalls", full_name="org/RepoCalls", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/api/user_api.py",
        code_symbol="register",
        start_line=10,
        end_line=30,
        chunk_text="def register():\n    return {'status': 'ok'}\n",
        content_hash="hash_c1",
        chunk_index=0,
        language="python",
    )
    c2 = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/services/other_service.py",
        code_symbol="register",
        start_line=40,
        end_line=60,
        chunk_text="def register():\n    save_employee_id()\n",
        content_hash="hash_c2",
        chunk_index=0,
        language="python",
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # Request flow reconstruction should not infer a call edge between unrelated functions with same name
    flow_chunks, notes = AssistantService._extract_verified_request_flow(
        db=db_session,
        repository_id=repo.id,
        question="trace API request for register",
    )
    # The notes must explicitly instruct against fabricating unverified calls
    assert notes is not None
    assert "Anti-Hallucination Constraints" in notes
    assert "Never invent" in notes


# 3. Incorrect citation file paths (e.g. from uploads or other repos) are excluded
def test_incorrect_citation_file_paths(db_session):
    repo = Repository(name="RepoCit", full_name="org/RepoCit", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    # Layer chunks helper should exclude uploads/, tests/, and alembic/versions/
    c_upload = CodeChunk(
        repository_id=repo.id,
        file_path="backend/uploads/app.py",
        start_line=1,
        end_line=20,
        chunk_text="app = FastAPI()",
        content_hash="hash_upload",
        chunk_index=0,
        language="python",
    )
    c_real = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/main.py",
        start_line=1,
        end_line=20,
        chunk_text="app = FastAPI()",
        content_hash="hash_real",
        chunk_index=0,
        language="python",
    )
    db_session.add_all([c_upload, c_real])
    db_session.commit()

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="explain architecture",
        retrieved_chunks=[],
    )
    file_paths = [c.file_path for c in chunks]
    assert "backend/uploads/app.py" not in file_paths
    assert "backend/app/main.py" in file_paths


# 4. Incorrect citation line ranges (broad placeholder 1-100 replaced by real range)
def test_incorrect_citation_line_ranges():
    chunks = [
        RetrievedChunk(
            chunk_id=1,
            file_path="backend/app/api/decision_api.py",
            symbol_name="bulk_delete",
            start_line=24,
            end_line=73,
            chunk_text="def bulk_delete(): pass\n",
            score=0.9,
            channels=["vector"],
            repository_id=1,
        )
    ]
    raw_answer = (
        "### `backend/app/api/decision_api.py` (Lines 1-100):\n"
        "```python\n"
        "def bulk_delete(): pass\n"
        "```"
    )
    sanitized = AssistantService._validate_and_sanitize_answer(raw_answer, chunks, "TestRepo")
    assert "(Lines 1-100)" not in sanitized
    assert "(Lines 24-73)" in sanitized


# 5. A code example whose contents do not match its labelled file is re-aligned
def test_code_example_contents_mismatch_labelled_file():
    chunks = [
        RetrievedChunk(
            chunk_id=1,
            file_path="backend/app/main.py",
            symbol_name="app",
            start_line=1,
            end_line=35,
            chunk_text="app = FastAPI()\napp.include_router(decision_api.router)\n",
            score=0.95,
            channels=["vector"],
            repository_id=1,
        )
    ]
    # Code contains FastAPI() and include_router, but is erroneously labelled as decision_api.py
    raw_answer = (
        "### `backend/app/api/decision_api.py` (Lines 1-100):\n"
        "```python\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "app.include_router(decision_api.router)\n"
        "```"
    )
    sanitized = AssistantService._validate_and_sanitize_answer(raw_answer, chunks, "TestRepo")
    assert "backend/app/main.py" in sanitized
    assert "(Lines 1-35)" in sanitized


# 6. Duplicate code snippets and duplicate citations
def test_duplicate_code_snippets_and_duplicate_citations():
    chunks = [
        RetrievedChunk(
            chunk_id=1,
            file_path="backend/app/main.py",
            symbol_name="app",
            start_line=1,
            end_line=35,
            chunk_text="app = FastAPI()\n",
            score=0.95,
            channels=["vector"],
            repository_id=1,
        )
    ]
    # Same code snippet repeated under two headings
    raw_answer = (
        "### `backend/app/main.py` (Lines 1-35):\n"
        "```python\n"
        "app = FastAPI()\n"
        "app.include_router(decision_api.router)\n"
        "get_db_session()\n"
        "```\n\n"
        "### `backend/app/api/other.py` (Lines 1-20):\n"
        "```python\n"
        "app = FastAPI()\n"
        "app.include_router(decision_api.router)\n"
        "get_db_session()\n"
        "```"
    )
    sanitized = AssistantService._validate_and_sanitize_answer(raw_answer, chunks, "TestRepo")
    assert "omitted to prevent duplication" in sanitized


# 7. Missing retrieval evidence versus a feature verified absent from indexed source
@pytest.mark.anyio
async def test_missing_retrieval_evidence_vs_verified_absent(db_session):
    repo = Repository(name="EmptyRepo", full_name="org/EmptyRepo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    # Unindexed repository explicitly states action required
    res_unindexed = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What is the architecture?",
    )
    assert res_unindexed["retrieval_strategy"] == "unindexed"
    assert "Action Required" in res_unindexed["answer"]

    # Now add indexed file and symbol, and check a symbol lookup query
    f = IndexedFile(repository_id=repo.id, path="src/main.py", lines_count=10)
    db_session.add(f)
    db_session.commit()

    sym = CodeSymbol(
        repository_id=repo.id,
        file_id=f.id,
        name="actual_function",
        kind="function",
        start_line=1,
        end_line=10,
    )
    db_session.add(sym)
    db_session.commit()

    res_symbol = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Where is `calculate_missing_symbol` defined?",
    )
    assert res_symbol["retrieval_strategy"] == "symbol_lookup"
    assert "was **not found** in the indexed source code" in res_symbol["answer"]


# 8. An actual request flow reconstructed through verified call relationships
def test_actual_request_flow_reconstructed_through_verified_calls(db_session):
    repo = Repository(name="TokenPoolTest", full_name="org/TokenPoolTest", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    main_c = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/main.py",
        start_line=1,
        end_line=30,
        chunk_text="app = FastAPI()\napp.include_router(api_router, prefix='/api')\n",
        content_hash="h_main",
        chunk_index=0,
        language="python",
    )
    ep_c = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/api/endpoints.py",
        code_symbol="login",
        start_line=143,
        end_line=160,
        chunk_text="@router.post('/login')\ndef login(db: Session = Depends(get_db)):\n    user = db.query(User).first()\n",
        content_hash="h_ep",
        chunk_index=0,
        language="python",
    )
    db_c = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/core/database.py",
        code_symbol="get_db",
        start_line=20,
        end_line=30,
        chunk_text="def get_db():\n    db = SessionLocal()\n    try:\n        yield db\n    finally:\n        db.close()\n",
        content_hash="h_db",
        chunk_index=0,
        language="python",
    )
    model_c = CodeChunk(
        repository_id=repo.id,
        file_path="backend/app/models/schema_models.py",
        code_symbol="User",
        start_line=10,
        end_line=40,
        chunk_text="class User(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n",
        content_hash="h_model",
        chunk_index=0,
        language="python",
    )
    db_session.add_all([main_c, ep_c, db_c, model_c])
    db_session.commit()

    chunks, notes = AssistantService._extract_verified_request_flow(
        db=db_session,
        repository_id=repo.id,
        question="Trace an API request from entry point through business logic to database",
    )
    assert len(chunks) >= 3
    paths = [c.file_path for c in chunks]
    assert "backend/app/main.py" in paths
    assert "backend/app/api/endpoints.py" in paths
    assert "backend/app/core/database.py" in paths
    assert "backend/app/models/schema_models.py" in paths
    assert "VERIFIED REQUEST FLOW AUDIT" in notes


# 9. A frontend-only repository without invented backend/database layers
def test_frontend_only_repository_without_invented_backend_db(db_session):
    repo = Repository(name="DesignRepo", full_name="local/CodeMind_AI_UI_UX_Design", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    main_c = CodeChunk(
        repository_id=repo.id,
        file_path="src/main.tsx",
        start_line=1,
        end_line=20,
        chunk_text="ReactDOM.createRoot(document.getElementById('root')!).render(<App />)",
        content_hash="h_main_tsx",
        chunk_index=0,
        language="typescript",
    )
    comp_c = CodeChunk(
        repository_id=repo.id,
        file_path="src/components/Dashboard.tsx",
        start_line=1,
        end_line=50,
        chunk_text="export const Dashboard = () => { return <div>Dashboard</div>; }",
        content_hash="h_comp_tsx",
        chunk_index=0,
        language="typescript",
    )
    db_session.add_all([main_c, comp_c])
    db_session.commit()

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="Explain the architecture of this project",
        retrieved_chunks=[],
    )
    # Entry point & frontend components verified
    assert any("main.tsx" in c.file_path for c in chunks)
    assert any("Dashboard.tsx" in c.file_path for c in chunks)
    # Models and DAO layers must be unverified / absent
    assert "Database models / ORM persistence schemas" in meta["unverified_layers"]
    assert "Dedicated repository / DAO layer" in meta["unverified_layers"]


# 10. A backend repository with a verified route-to-service-to-database flow
def test_backend_repository_with_verified_route_to_service_to_db(db_session):
    repo = Repository(name="ExpertRepo", full_name="org/expertdecision", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    chunks_data = [
        ("backend/app/main.py", 1, 30, "app = FastAPI()"),
        ("backend/app/api/user_api.py", 1, 40, "@router.post('/login')\ndef login(): UserService.authenticate()"),
        ("backend/app/services/user_service.py", 1, 50, "class UserService:\n  @staticmethod\n  def authenticate(): pass"),
        ("backend/app/repositories/user_repository.py", 1, 30, "class UserRepository:\n  def get_by_id(): pass"),
        ("backend/app/models/user.py", 1, 30, "class User(Base):\n  __tablename__ = 'users'"),
    ]
    for idx, (p, s, e, t) in enumerate(chunks_data):
        db_session.add(CodeChunk(
            repository_id=repo.id,
            file_path=p,
            start_line=s,
            end_line=e,
            chunk_text=t,
            content_hash=f"hash_be_{idx}",
            chunk_index=0,
            language="python",
        ))
    db_session.commit()

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="explain the architecture",
        retrieved_chunks=[],
    )
    assert "API routes and request handlers" in meta["verified_layers"]
    assert "Service and business-logic modules" in meta["verified_layers"]
    assert "Data access / repository layer" in meta["verified_layers"]
    assert "Database models, schemas, and persistence" in meta["verified_layers"]


# 11. Repository isolation in citations and source evidence
@pytest.mark.anyio
async def test_repository_isolation_in_citations_and_evidence(db_session):
    repoA = Repository(name="RepoA", full_name="org/RepoA", default_branch="main")
    repoB = Repository(name="RepoB", full_name="org/RepoB", default_branch="main")
    db_session.add_all([repoA, repoB])
    db_session.commit()

    cA = CodeChunk(
        repository_id=repoA.id,
        file_path="src/fileA.py",
        start_line=1,
        end_line=10,
        chunk_text="def a(): pass",
        content_hash="h_a",
        chunk_index=0,
        language="python",
    )
    cB = CodeChunk(
        repository_id=repoB.id,
        file_path="src/fileB.py",
        start_line=1,
        end_line=10,
        chunk_text="def b(): pass",
        content_hash="h_b",
        chunk_index=0,
        language="python",
    )
    db_session.add_all([cA, cB])
    db_session.commit()

    with patch.object(AssistantService, "_generate_llm_answer", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "Answer for RepoA based on src/fileA.py:1-10."
        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=repoA.id,
            question="what does fileA do?",
        )
        assert res["repository_id"] == repoA.id
        for cit in res["citations"]:
            assert cit["repository_name"] == repoA.name
            assert "fileB.py" not in cit["file_path"]


# 12. Evidence counts matching the final answer
@pytest.mark.anyio
async def test_evidence_counts_matching_final_answer(db_session):
    repo = Repository(name="RepoCounts", full_name="org/RepoCounts", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    c1 = CodeChunk(
        repository_id=repo.id,
        file_path="src/main.py",
        start_line=1,
        end_line=10,
        chunk_text="def main(): pass",
        content_hash="h_cnt",
        chunk_index=0,
        language="python",
    )
    db_session.add(c1)
    db_session.commit()

    with patch.object(AssistantService, "_generate_llm_answer", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "Verified main in src/main.py. However, database models are unverified."
        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question="explain architecture",
        )
        facts = res["facts"]
        assert facts["confirmed"] >= 1
        assert facts["unknowns"] >= 1  # Unverified database model captured in unknowns


# 13. Context-budget enforcement without removing essential evidence
def test_context_budget_enforcement_without_removing_essential_evidence(db_session):
    repo = Repository(name="BudgetRepo", full_name="org/BudgetRepo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    # Add 15 chunks across different files
    for i in range(15):
        c = CodeChunk(
            repository_id=repo.id,
            file_path=f"src/file_{i // 2}.py",
            start_line=1 + (i % 2) * 50,
            end_line=40 + (i % 2) * 50,
            chunk_text=f"# Chunk {i}\n" * 10,
            content_hash=f"h_budget_{i}",
            chunk_index=i,
            language="python",
        )
        db_session.add(c)
    db_session.commit()

    chunks, notes, meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question="explain architecture",
        retrieved_chunks=[],
    )
    # Total chunks capped at <= 10
    assert len(chunks) <= 10
    # No single file has > 2 chunks
    file_counts = {}
    for c in chunks:
        file_counts[c.file_path] = file_counts.get(c.file_path, 0) + 1
    assert all(cnt <= 2 for cnt in file_counts.values())


# 14. Ollama timeout behavior and retry handling
@pytest.mark.anyio
async def test_ollama_timeout_behavior_and_retry_handling():
    provider = OllamaLLMProvider(base_url="http://127.0.0.1:11434", model="qwen2.5:3b")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Ollama request timed out after 90s")
        with pytest.raises(LLMTimeoutError) as exc_info:
            await provider.generate_chat_response([{"role": "user", "content": "hello"}])
        assert "timed out after" in str(exc_info.value)
        # Verify it did not retry in an expensive loop
        assert mock_post.call_count == 1


# 15. Preventing a timeout or failed generation from being represented as a successful answer
@pytest.mark.anyio
async def test_failed_generation_not_represented_as_successful(db_session):
    repo = Repository(name="TimeoutRepo", full_name="org/TimeoutRepo", default_branch="main")
    db_session.add(repo)
    db_session.commit()

    c = CodeChunk(
        repository_id=repo.id,
        file_path="src/main.py",
        start_line=1,
        end_line=10,
        chunk_text="def main(): pass",
        content_hash="h_timeout",
        chunk_index=0,
        language="python",
    )
    db_session.add(c)
    db_session.commit()

    with patch.object(AssistantService, "_generate_llm_answer", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = LLMTimeoutError("Ollama LLM request timed out after 90s.")
        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question="explain architecture",
        )
        assert res["status"] == "failed"
        assert "AI Assistant Error" in res["answer"]
        assert "timed out after" in res["answer"]
        assert len(res["citations"]) >= 1  # Citations preserved for user evidence
