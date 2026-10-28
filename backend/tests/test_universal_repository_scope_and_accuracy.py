import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.knowledge_graph import GraphNode, GraphEdge
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.assistant_service import AssistantService


# ==============================================================================
# Multi-Language & Multi-Architecture Fixture Helpers
# ==============================================================================

def create_flutter_repo(db: Session, user_id: int = None) -> Repository:
    """Fixture 1: Flutter/Dart + Android Kotlin mobile repository."""
    repo = Repository(
        name="flutter-ecommerce",
        full_name="mobile-org/flutter-ecommerce",
        is_private=False,
        default_branch="main",
        user_id=user_id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_main = IndexedFile(repository_id=repo.id, path="lib/main.dart", language="dart", lines_count=45)
    f_cart = IndexedFile(repository_id=repo.id, path="lib/views/cart_screen.dart", language="dart", lines_count=80)
    f_kt = IndexedFile(repository_id=repo.id, path="android/app/src/main/kotlin/MainActivity.kt", language="kotlin", lines_count=35)
    db.add_all([f_main, f_cart, f_kt])
    db.commit()

    c_main = CodeChunk(
        repository_id=repo.id,
        file_path=f_main.path,
        chunk_index=0,
        start_line=1,
        end_line=25,
        chunk_text="import 'package:flutter/material.dart';\nvoid main() => runApp(const MyApp());\nclass MyApp extends StatelessWidget {\n  Widget build(BuildContext context) => const MaterialApp(home: CartScreen());\n}",
        code_symbol="MyApp",
        content_hash="hash_flutter_main",
        language="dart",
    )
    c_cart = CodeChunk(
        repository_id=repo.id,
        file_path=f_cart.path,
        chunk_index=0,
        start_line=1,
        end_line=40,
        chunk_text="class CartScreen extends StatefulWidget {\n  @override\n  State<CartScreen> createState() => _CartScreenState();\n}\nclass _CartScreenState extends State<CartScreen> {\n  void checkout() {\n    // processes local cart items\n  }\n}",
        code_symbol="CartScreen",
        content_hash="hash_flutter_cart",
        language="dart",
    )
    c_kt = CodeChunk(
        repository_id=repo.id,
        file_path=f_kt.path,
        chunk_index=0,
        start_line=1,
        end_line=20,
        chunk_text="package com.example.ecommerce\nimport io.flutter.embedding.android.FlutterActivity\nclass MainActivity: FlutterActivity() {\n}",
        code_symbol="MainActivity",
        content_hash="hash_android_main",
        language="kotlin",
    )
    db.add_all([c_main, c_cart, c_kt])
    db.commit()
    return repo


def create_fastapi_repo(db: Session, user_id: int = None) -> Repository:
    """Fixture 2: Python / FastAPI backend repository."""
    repo = Repository(
        name="fastapi-backend",
        full_name="backend-org/fastapi-backend",
        is_private=False,
        default_branch="master",
        user_id=user_id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_app = IndexedFile(repository_id=repo.id, path="src/main.py", language="python", lines_count=50)
    f_items = IndexedFile(repository_id=repo.id, path="src/routes/items.py", language="python", lines_count=60)
    db.add_all([f_app, f_items])
    db.commit()

    c_app = CodeChunk(
        repository_id=repo.id,
        file_path=f_app.path,
        chunk_index=0,
        start_line=1,
        end_line=30,
        chunk_text="from fastapi import FastAPI\nfrom src.routes.items import router as item_router\napp = FastAPI(title='ItemService')\napp.include_router(item_router, prefix='/items')",
        code_symbol="app",
        content_hash="hash_fastapi_app",
        language="python",
    )
    c_items = CodeChunk(
        repository_id=repo.id,
        file_path=f_items.path,
        chunk_index=0,
        start_line=1,
        end_line=35,
        chunk_text="from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/')\ndef list_items():\n    return [{'id': 1, 'name': 'Widget'}]",
        code_symbol="list_items",
        content_hash="hash_fastapi_items",
        language="python",
    )
    db.add_all([c_app, c_items])
    db.commit()
    return repo


def create_react_ts_repo(db: Session, user_id: int = None) -> Repository:
    """Fixture 3: JavaScript / TypeScript React Single Page Application."""
    repo = Repository(
        name="react-dashboard",
        full_name="frontend-org/react-dashboard",
        is_private=False,
        default_branch="main",
        user_id=user_id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_idx = IndexedFile(repository_id=repo.id, path="src/index.tsx", language="typescript", lines_count=30)
    f_hook = IndexedFile(repository_id=repo.id, path="src/hooks/useAuth.ts", language="typescript", lines_count=45)
    db.add_all([f_idx, f_hook])
    db.commit()

    c_idx = CodeChunk(
        repository_id=repo.id,
        file_path=f_idx.path,
        chunk_index=0,
        start_line=1,
        end_line=25,
        chunk_text="import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport App from './App';\nconst root = ReactDOM.createRoot(document.getElementById('root')!);\nroot.render(<App />);",
        code_symbol="root",
        content_hash="hash_react_idx",
        language="typescript",
    )
    c_hook = CodeChunk(
        repository_id=repo.id,
        file_path=f_hook.path,
        chunk_index=0,
        start_line=1,
        end_line=35,
        chunk_text="import { useState, useEffect } from 'react';\nexport function useAuth() {\n  const [user, setUser] = useState(null);\n  useEffect(() => {\n    // fetch current session\n  }, []);\n  return { user };\n}",
        code_symbol="useAuth",
        content_hash="hash_react_hook",
        language="typescript",
    )
    db.add_all([c_idx, c_hook])
    db.commit()
    return repo


def create_monorepo(db: Session, user_id: int = None) -> Repository:
    """Fixture 4: Monorepo with Go microservice, Python service, and TS package."""
    repo = Repository(
        name="enterprise-monorepo",
        full_name="corp/enterprise-monorepo",
        is_private=False,
        default_branch="main",
        user_id=user_id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_go = IndexedFile(repository_id=repo.id, path="services/billing/main.go", language="go", lines_count=50)
    f_py = IndexedFile(repository_id=repo.id, path="services/notifications/worker.py", language="python", lines_count=40)
    db.add_all([f_go, f_py])
    db.commit()

    c_go = CodeChunk(
        repository_id=repo.id,
        file_path=f_go.path,
        chunk_index=0,
        start_line=1,
        end_line=30,
        chunk_text="package main\nimport 'fmt'\nfunc ProcessInvoice(id string) error {\n  fmt.Println('Processing invoice', id)\n  return nil\n}",
        code_symbol="ProcessInvoice",
        content_hash="hash_monorepo_go",
        language="go",
    )
    c_py = CodeChunk(
        repository_id=repo.id,
        file_path=f_py.path,
        chunk_index=0,
        start_line=1,
        end_line=25,
        chunk_text="def dispatch_push_notification(user_id: int, payload: dict):\n    print(f'Sending notification to {user_id}')",
        code_symbol="dispatch_push_notification",
        content_hash="hash_monorepo_py",
        language="python",
    )
    db.add_all([c_go, c_py])
    db.commit()
    return repo


def create_misleading_function_repo(db: Session, user_id: int = None) -> Repository:
    """Fixture 5: Repository containing a function whose name is misleading relative to its body."""
    repo = Repository(
        name="pdf-export-tool",
        full_name="tools/pdf-export-tool",
        is_private=False,
        default_branch="main",
        user_id=user_id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_rep = IndexedFile(repository_id=repo.id, path="src/reports/exporter.py", language="python", lines_count=45)
    db.add(f_rep)
    db.commit()

    c_rep = CodeChunk(
        repository_id=repo.id,
        file_path=f_rep.path,
        chunk_index=0,
        start_line=10,
        end_line=30,
        chunk_text="def generate_report(data: list, output_filename: str = 'out.csv') -> str:\n    \"\"\"Writes raw table data into a local CSV string.\"\"\"\n    import csv, io\n    buf = io.StringIO()\n    writer = csv.writer(buf)\n    for row in data:\n        writer.writerow(row)\n    return buf.getvalue()",
        code_symbol="generate_report",
        content_hash="hash_misleading_rep",
        language="python",
    )
    db.add(c_rep)
    db.commit()
    return repo


def create_python_hybrid_retrieval_repo(db: Session, user_id: int = None) -> Repository:
    """Fixture 6: Python repository containing its own hybrid retrieval engine."""
    repo = Repository(
        name="custom-search-service",
        full_name="search-org/custom-search-service",
        is_private=False,
        default_branch="main",
        user_id=user_id,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_eng = IndexedFile(repository_id=repo.id, path="app/search/hybrid_search.py", language="python", lines_count=90)
    db.add(f_eng)
    db.commit()

    c_eng = CodeChunk(
        repository_id=repo.id,
        file_path=f_eng.path,
        chunk_index=0,
        start_line=1,
        end_line=45,
        chunk_text="class MultiChannelSearchEngine:\n    def hybrid_search(self, query: str):\n        \"\"\"Combines vector similarity and bm25 keyword scoring.\"\"\"\n        vector_res = self.vector_search(query)\n        keyword_res = self.bm25_search(query)\n        return self.reciprocal_rank_fusion(vector_res, keyword_res)",
        code_symbol="MultiChannelSearchEngine",
        content_hash="hash_search_engine",
        language="python",
    )
    db.add(c_eng)
    db.commit()
    return repo


# ==============================================================================
# Tests
# ==============================================================================

@pytest.mark.anyio
async def test_repository_isolation_between_flutter_and_fastapi(db_session: Session):
    """
    Scenario: Verify that retrieval for a Flutter repository never leaks FastAPI chunks,
    and vice-versa, even if queried with cross-framework terminology.
    """
    flutter_repo = create_flutter_repo(db_session)
    fastapi_repo = create_fastapi_repo(db_session)

    # Query Flutter repo asking about FastAPI routing
    flutter_chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=flutter_repo.id,
        query="Explain the API routes and APIRouter in this project",
    )
    assert all(c.file_path.startswith("lib/") or c.file_path.startswith("android/") for c in flutter_chunks)
    assert not any("fastapi" in c.chunk_text.lower() for c in flutter_chunks)

    # Query FastAPI repo asking about Flutter widgets
    fastapi_chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=fastapi_repo.id,
        query="Explain StatefulWidget and MaterialApp in this project",
    )
    assert all(c.file_path.startswith("src/") for c in fastapi_chunks)
    assert not any("flutter" in c.chunk_text.lower() for c in fastapi_chunks)


@pytest.mark.anyio
async def test_general_programming_classification_across_languages(db_session: Session):
    """
    Scenario: Verify that generic language and CS queries are classified as GENERAL_PROGRAMMING
    and do not force repository retrieval across Flutter, React, Go, and Python concepts.
    """
    questions = [
        "What is the difference between StatefulWidget and StatelessWidget?",
        "Difference between abstract class and interface in Java",
        "What is a goroutine in Go and how does it differ from a thread?",
        "Explain the React useEffect hook and its dependency array",
        "How to reverse a linked list in Python?",
        "What is Big O notation?",
        "Explain ACID properties in database management",
    ]

    for q in questions:
        intents = AssistantService.classify_query_intent(q)
        assert "GENERAL_PROGRAMMING" in intents, f"Expected GENERAL_PROGRAMMING for query: '{q}', got {intents}"


@pytest.mark.anyio
async def test_explicit_repo_reference_overrides_general_programming(db_session: Session):
    """
    Scenario: If the user explicitly asks about the current repository ('in this repo', 'our project'),
    it must NOT be classified as pure GENERAL_PROGRAMMING.
    """
    q = "What is the difference between the classes in this repo?"
    intents = AssistantService.classify_query_intent(q)
    assert "GENERAL_PROGRAMMING" not in intents


@pytest.mark.anyio
async def test_switching_repositories_conversation_isolation(db_session: Session):
    """
    Scenario: Ensure conversation history from Repo A does not leak or contaminate Repo B when switching.
    """
    flutter_repo = create_flutter_repo(db_session)
    fastapi_repo = create_fastapi_repo(db_session)

    # Conv 1 on Flutter repo
    conv1 = AssistantConversation(repository_id=flutter_repo.id, branch="main", title="Flutter chat")
    db_session.add(conv1)
    db_session.commit()

    msg1 = AssistantMessage(
        conversation_id=conv1.id,
        role="assistant",
        content="The Flutter mobile application defines MyApp in lib/main.dart.",
        status="success",
    )
    db_session.add(msg1)
    db_session.commit()

    # Conv 2 on FastAPI repo
    conv2 = AssistantConversation(repository_id=fastapi_repo.id, branch="master", title="FastAPI chat")
    db_session.add(conv2)
    db_session.commit()

    # Resolve context for conv2
    follow_up = AssistantService._resolve_follow_up_context(
        db=db_session,
        repository_id=fastapi_repo.id,
        conversation_id=conv2.id,
        question="What does the entry point do?",
    )

    # History turns of conv2 must be empty
    assert len(follow_up.get("history_turns", [])) == 0
    assert "Flutter" not in str(follow_up)


@pytest.mark.anyio
async def test_function_responsibility_not_assumed_from_name(db_session: Session):
    """
    Scenario: Fixture 5 has generate_report which only formats CSV text.
    Verify that the system prompt and sanitization prevent hallucinating that it generates AI responses
    or accesses an unverified database.
    """
    repo = create_misleading_function_repo(db_session)

    chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo.id,
        query="What does generate_report do?",
    )
    assert len(chunks) > 0
    assert chunks[0].symbol_name == "generate_report"
    assert "csv" in chunks[0].chunk_text

    # Sanitization test
    raw_answer = "generate_report likely handles generating the AI assistant answers and connects to postgresql://localhost/db."
    sanitized = AssistantService._validate_and_sanitize_answer(
        answer=raw_answer,
        chunks=chunks,
        repo_name=repo.name,
        question="What does generate_report do?",
    )

    # 'likely' should be removed, and grounded facts preserved
    assert "likely" not in sanitized.lower()


@pytest.mark.anyio
async def test_unauthorized_private_repository_access_denied(db_session: Session):
    """
    Scenario: Verify that a private repository assigned to user_id=10 cannot be retrieved by user_id=20.
    """
    owner_id = 10
    attacker_id = 20

    private_repo = Repository(
        name="private-vault",
        full_name="secret/private-vault",
        is_private=True,
        default_branch="main",
        user_id=owner_id,
    )
    db_session.add(private_repo)
    db_session.commit()

    f = IndexedFile(repository_id=private_repo.id, path="secrets.py", language="python", lines_count=10)
    db_session.add(f)
    db_session.commit()

    c = CodeChunk(
        repository_id=private_repo.id,
        file_path=f.path,
        chunk_index=0,
        start_line=1,
        end_line=5,
        chunk_text="API_KEY = 'top-secret-token'",
        content_hash="hash_secret_key",
        language="python",
    )
    db_session.add(c)
    db_session.commit()

    # Query as attacker (user_id=20)
    denied_chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=private_repo.id,
        query="What is the API key?",
        user_id=attacker_id,
    )
    assert denied_chunks == []


@pytest.mark.anyio
async def test_codemind_host_platform_query_scoping(db_session: Session):
    """
    Scenario: When user asks 'How does CodeMind AI work?' while another repo is selected,
    the assistant should answer clearly or qualify scope without fabricating that the current repo is CodeMind AI.
    """
    flutter_repo = create_flutter_repo(db_session)
    chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=flutter_repo.id,
        query="How does CodeMind AI index files?",
    )
    # The flutter repo chunks must NOT be fabricated as CodeMind AI host chunks
    assert all(c.repository_id == flutter_repo.id for c in chunks)


@pytest.mark.anyio
async def test_diagnostics_structure_completeness(db_session: Session):
    """
    Scenario: Verify that diagnostics emitted during an assistant turn include all required observability fields:
    repository_id, branch, current_question, detected_intents, query_rewritten, explicit_file_matched,
    retrieval_strategy, facts, status, and request_duration_ms.
    """
    repo = create_fastapi_repo(db_session)
    conv = AssistantConversation(repository_id=repo.id, branch="master", title="FastAPI Test")
    db_session.add(conv)
    db_session.commit()

    # Mock the LLM provider to return deterministic response
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "test-model:latest"
        async def mock_gen(*args, **kwargs):
            return "In `src/main.py`, the `item_router` is included with prefix `/items`."
        mock_provider.generate_chat_response = mock_gen
        mock_get_llm.return_value = mock_provider

        result = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question="What routes are registered in src/main.py?",
            conversation_id=conv.id,
        )

        assert result["status"] == "success"
        diag = result.get("diagnostics")
        assert diag is not None
        assert diag["repository_id"] == repo.id
        assert diag["branch"] == "master"
        assert "API_ROUTES" in diag["detected_intents"]
        assert "explicit_file_matched" in diag
        assert "retrieval_strategy" in diag
        assert "facts" in diag
        assert diag["model_name"] == "test-model:latest"
        assert diag["status"] == "success"


@pytest.mark.anyio
async def test_evidence_counters_correctness(db_session: Session):
    """
    Scenario: Ensure evidence counters distinguish confirmed facts from unknowns.
    """
    repo = create_fastapi_repo(db_session)
    chunks = await HybridRetrievalEngine.retrieve(
        db=db_session,
        repository_id=repo.id,
        query="items",
    )
    citations = [{"file_path": "src/routes/items.py", "start_line": 1, "end_line": 35}]

    # Answer stating verified route
    answer = "The endpoint `GET /` is defined in `src/routes/items.py:1-35`."
    counters = AssistantService._calculate_evidence_counters(
        answer=answer,
        citations=citations,
        retrieved_chunks=chunks,
        impact=None,
        audit_meta=None,
        intents=["API_ROUTES"],
    )
    assert counters["confirmed"] >= 1
    assert counters["unknowns"] == 0

    # Answer stating feature is absent / unverified
    answer_unverified = "Email notification support is UNVERIFIED / ABSENT in the indexed source code."
    counters_unverified = AssistantService._calculate_evidence_counters(
        answer=answer_unverified,
        citations=citations,
        retrieved_chunks=chunks,
        impact=None,
        audit_meta=None,
        intents=["SERVICES"],
    )
    assert counters_unverified["unknowns"] >= 1


@pytest.mark.anyio
async def test_cross_repository_hybrid_retrieval_presence_and_absence(db_session: Session):
    """
    Scenario: Cross-repository feature presence and absence regression test.
    - Python hybrid repo: answers with its own citations, confirmed facts >= 1.
    - Flutter/Dart repo: accurately reports hybrid retrieval is UNVERIFIED / ABSENT, unknowns >= 1.
    - React repo: retrieves only its own evidence (useAuth), confirmed facts >= 1.
    - Monorepo: retrieves only its own evidence (ProcessInvoice), confirmed facts >= 1.
    """
    python_repo = create_python_hybrid_retrieval_repo(db_session)
    flutter_repo = create_flutter_repo(db_session)
    react_repo = create_react_ts_repo(db_session)
    monorepo = create_monorepo(db_session)

    # 1. Python repo with hybrid retrieval
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "test-model"
        async def mock_gen_py(*args, **kwargs):
            return "Hybrid retrieval is implemented by `MultiChannelSearchEngine.hybrid_search()` in `app/search/hybrid_search.py:1-45` combining vector and keyword scoring."
        mock_provider.generate_chat_response = mock_gen_py
        mock_get_llm.return_value = mock_provider

        py_res = await AssistantService.answer_question(
            db=db_session,
            repository_id=python_repo.id,
            question="Where is hybrid retrieval implemented in this repository?",
        )
        assert py_res["status"] == "success"
        assert len(py_res["citations"]) > 0
        assert all(c["file_path"].startswith("app/search/") for c in py_res["citations"])
        assert any("hybrid_search.py" in c["file_path"] for c in py_res["citations"])
        assert py_res["facts"]["confirmed"] >= 1
        assert "MultiChannelSearchEngine" in py_res["answer"]

    # 2. Flutter repo WITHOUT hybrid retrieval
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "test-model"
        async def mock_gen_flutter(*args, **kwargs):
            return "Hybrid retrieval is UNVERIFIED / ABSENT in the indexed source code of repository flutter-ecommerce. This mobile application does not implement a search engine or hybrid retrieval."
        mock_provider.generate_chat_response = mock_gen_flutter
        mock_get_llm.return_value = mock_provider

        flutter_res = await AssistantService.answer_question(
            db=db_session,
            repository_id=flutter_repo.id,
            question="Where is hybrid retrieval implemented in this repository?",
        )
        assert flutter_res["status"] == "success"
        # Flutter repo must never cite python search files or CodeMind host files
        assert not any("hybrid_search.py" in c["file_path"] for c in flutter_res["citations"])
        assert not any("hybrid_engine.py" in c["file_path"] for c in flutter_res["citations"])
        assert flutter_res["facts"]["unknowns"] >= 1
        assert "unverified" in flutter_res["answer"].lower() or "absent" in flutter_res["answer"].lower() or "not found" in flutter_res["answer"].lower()

    # 3. React / TypeScript repo feature query
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "test-model"
        async def mock_gen_react(*args, **kwargs):
            return "Authentication is managed via the `useAuth` hook in `src/hooks/useAuth.ts:1-35`."
        mock_provider.generate_chat_response = mock_gen_react
        mock_get_llm.return_value = mock_provider

        react_res = await AssistantService.answer_question(
            db=db_session,
            repository_id=react_repo.id,
            question="Where is authentication managed in this project?",
        )
        assert react_res["status"] == "success"
        assert len(react_res["citations"]) > 0
        assert all(c["file_path"].startswith("src/") for c in react_res["citations"])
        assert any("useAuth.ts" in c["file_path"] for c in react_res["citations"])
        assert react_res["facts"]["confirmed"] >= 1

    # 4. Multi-language monorepo feature query
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "test-model"
        async def mock_gen_mono(*args, **kwargs):
            return "Invoices are processed by `ProcessInvoice` in `services/billing/main.go:1-30`."
        mock_provider.generate_chat_response = mock_gen_mono
        mock_get_llm.return_value = mock_provider

        mono_res = await AssistantService.answer_question(
            db=db_session,
            repository_id=monorepo.id,
            question="How does ProcessInvoice process an invoice in services/billing/main.go?",
        )
        assert mono_res["status"] == "success"
        assert len(mono_res["citations"]) > 0
        assert any("services/billing" in c["file_path"] for c in mono_res["citations"])
        assert all(c["file_path"].startswith("services/") for c in mono_res["citations"])
        assert mono_res["facts"]["confirmed"] >= 1


@pytest.mark.anyio
async def test_cross_repo_streaming_and_non_streaming_parity(db_session: Session):
    """
    Scenario: Verify parity between streaming (stream_answer_question) and non-streaming (answer_question)
    responses across different repository types.
    """
    flutter_repo = create_flutter_repo(db_session)
    react_repo = create_react_ts_repo(db_session)

    # 1. Streaming response for Flutter repo
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "stream-model"
        async def mock_chat_stream(*args, **kwargs):
            for token in ["Hybrid ", "retrieval ", "is ", "UNVERIFIED / ABSENT ", "in ", "flutter-ecommerce."]:
                yield token
        mock_provider.generate_chat_stream = mock_chat_stream
        mock_get_llm.return_value = mock_provider

        events = []
        async for chunk in AssistantService.stream_answer_question(
            db=db_session,
            repository_id=flutter_repo.id,
            question="Where is hybrid retrieval implemented?",
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

        done_event = next(e[1] for e in events if e[0] == "done")
        assert done_event["repository_id"] == flutter_repo.id
        assert done_event["status"] == "success"
        assert done_event["facts"]["unknowns"] >= 1
        assert "unverified" in done_event["answer"].lower() or "absent" in done_event["answer"].lower()

    # 2. Streaming response for React repo
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "stream-model"
        async def mock_chat_stream_react(*args, **kwargs):
            for token in ["The ", "useAuth ", "hook ", "is ", "defined ", "in ", "`src/hooks/useAuth.ts:1-35`."]:
                yield token
        mock_provider.generate_chat_stream = mock_chat_stream_react
        mock_get_llm.return_value = mock_provider

        react_events = []
        async for chunk in AssistantService.stream_answer_question(
            db=db_session,
            repository_id=react_repo.id,
            question="Explain the useAuth hook",
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
                react_events.append((event_type, event_data))

        done_react = next(e[1] for e in react_events if e[0] == "done")
        assert done_react["repository_id"] == react_repo.id
        assert len(done_react["citations"]) > 0
        assert any("useAuth.ts" in c["file_path"] for c in done_react["citations"])
        assert done_react["facts"]["confirmed"] >= 1


@pytest.mark.anyio
async def test_cross_repo_conversation_persistence_and_reopening(db_session: Session):
    """
    Scenario: Verify conversation history persistence, structured evidence metadata,
    and reopening across repository boundaries without evidence leakage.
    """
    flutter_repo = create_flutter_repo(db_session)
    react_repo = create_react_ts_repo(db_session)

    # 1. Create and populate conversation on React repo
    with patch("backend.app.services.assistant_service.get_llm_provider") as mock_get_llm:
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.model = "test-model"
        async def mock_gen(*args, **kwargs):
            return "In `src/index.tsx:1-25`, `ReactDOM.createRoot` renders `App`."
        mock_provider.generate_chat_response = mock_gen
        mock_get_llm.return_value = mock_provider

        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=react_repo.id,
            question="What is the React application root?",
        )
        conv_id = res["conversation_id"]

    # 2. Reopen conversation via get_conversation_detail
    conv_detail = AssistantService.get_conversation_detail(
        db=db_session,
        conversation_id=conv_id,
    )
    assert conv_detail["id"] == conv_id
    assert conv_detail["repository_id"] == react_repo.id
    assert conv_detail["repository_name"] == react_repo.name
    assert len(conv_detail["messages"]) == 2

    user_msg = conv_detail["messages"][0]
    asst_msg = conv_detail["messages"][1]
    assert user_msg["role"] == "user"
    assert asst_msg["role"] == "assistant"
    assert len(asst_msg["citations"]) > 0
    assert any("index.tsx" in c["file_path"] for c in asst_msg["citations"])
    assert asst_msg["evidence_metadata"] is not None
    assert "facts" in asst_msg["evidence_metadata"]
    assert asst_msg["evidence_metadata"]["facts"]["confirmed"] >= 1

    # 3. Verify cross-repository isolation: Flutter cannot access React's conversation context
    follow_up_flutter = AssistantService._resolve_follow_up_context(
        db=db_session,
        repository_id=flutter_repo.id,
        conversation_id=conv_id,
        question="What widgets are defined?",
    )
    # The helper strictly scopes to matching repository_id
    assert "index.tsx" not in str(follow_up_flutter.get("augmented_query", ""))

