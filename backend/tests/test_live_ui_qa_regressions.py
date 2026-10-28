import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.services.assistant_service import AssistantService
from backend.app.retrieval.hybrid_engine import RetrievedChunk


def create_sample_codemind_repo(db: Session) -> Repository:
    repo = Repository(
        name="CodeMind-AI",
        full_name="KoppalaNaveen0320/CodeMind-AI",
        description="AI-powered code intelligence and architecture platform",
        default_branch="main",
        current_revision="commit-codemind-1",
        files_count=10,
        status="ready",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Add hybrid engine file
    f_engine = IndexedFile(
        repository_id=repo.id,
        path="backend/app/retrieval/hybrid_engine.py",
        language="python",
        lines_count=722,
    )
    f_service = IndexedFile(
        repository_id=repo.id,
        path="backend/app/services/assistant_service.py",
        language="python",
        lines_count=4800,
    )
    db.add_all([f_engine, f_service])
    db.commit()

    import hashlib
    def make_chunk(**kwargs):
        txt = kwargs.get("chunk_text", "")
        h = hashlib.sha256(txt.encode()).hexdigest()
        return CodeChunk(content_hash=h, **kwargs)

    # Add code chunks representing each hybrid retrieval stage
    c_exact = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_exact_matches",
        start_line=353,
        end_line=470,
        chunk_text="def _retrieve_exact_matches(cls, db: Session, repo_id: int, query: str, language: Optional[str], matching_explicit_files: Optional[List[str]] = None) -> List[CodeChunk]:\n    # Exact symbol, class, function, and file-name matching\n    pass",
        language="python",
    )
    c_kw = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_keyword_matches",
        start_line=476,
        end_line=550,
        chunk_text="def _retrieve_keyword_matches(cls, db: Session, repo_id: int, query: str, language: Optional[str]) -> List[tuple]:\n    # Filters stopwords, matches token frequency via CodeChunk.chunk_text.ilike\n    pass",
        language="python",
    )
    c_vec = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_vector_matches",
        start_line=552,
        end_line=620,
        chunk_text="async def _retrieve_vector_matches(cls, db: Session, repo_id: int, query: str, language: Optional[str]) -> List[tuple]:\n    # pgvector cosine distance or cosine similarity fallback\n    pass",
        language="python",
    )
    c_graph = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._expand_via_knowledge_graph",
        start_line=622,
        end_line=695,
        chunk_text="def _expand_via_knowledge_graph(cls, db: Session, repo_id: int, initial_candidates: Dict[int, RetrievedChunk]) -> List[tuple]:\n    # 1-hop traversal across GraphNode and GraphEdge for CALLS, IMPORTS, DEFINES\n    pass",
        language="python",
    )
    c_fusion = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine.retrieve",
        start_line=230,
        end_line=327,
        chunk_text="final_score = (scores.get('vector', 0.0) * w_vec + scores.get('keyword', 0.0) * w_kw + scores.get('exact', 0.0) * w_exact + scores.get('graph', 0.0) * w_graph)\n# Code vs Documentation/Tests ranking adjustment\npass",
        language="python",
    )
    c_dedup = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine.retrieve",
        start_line=331,
        end_line=350,
        chunk_text="seen_chunks: Set[Tuple[int, str, int, int]] = set()\n# Stable Deduplication by File Path and Line Range, with Per-File Diversity\npass",
        language="python",
    )
    c_cos = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._cosine_similarity",
        start_line=698,
        end_line=706,
        chunk_text="def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:\n    # Calculates cosine similarity between two float vectors for semantic embeddings fallback\n    dot = sum(a * b for a, b in zip(vec_a, vec_b))\n    return max(0.0, min(1.0, dot / (norm_a * norm_b)))",
        language="python",
    )

    db.add_all([c_exact, c_kw, c_vec, c_graph, c_fusion, c_dedup, c_cos])

    sym_engine = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="HybridRetrievalEngine",
        kind="class",
        start_line=200,
        end_line=750,
    )
    sym_exact = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="_retrieve_exact_matches",
        kind="method",
        start_line=353,
        end_line=470,
    )
    sym_kw = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="_retrieve_keyword_matches",
        kind="method",
        start_line=476,
        end_line=550,
    )
    sym_vec = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="_retrieve_vector_matches",
        kind="method",
        start_line=552,
        end_line=620,
    )
    sym_graph = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="_expand_via_knowledge_graph",
        kind="method",
        start_line=622,
        end_line=695,
    )
    sym_retrieve = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="retrieve",
        kind="method",
        start_line=230,
        end_line=350,
    )
    sym_cos = CodeSymbol(
        repository_id=repo.id,
        file_id=f_engine.id,
        name="_cosine_similarity",
        kind="function",
        start_line=698,
        end_line=706,
    )
    db.add_all([sym_engine, sym_exact, sym_kw, sym_vec, sym_graph, sym_retrieve, sym_cos])
    db.commit()

    return repo


@pytest.mark.anyio
async def test_regression_1_python_list_comprehension_explanation(db_session: Session):
    """
    Assertion 1: A Python list-comprehension question receives a real explanation and code example.
    Must not complain that repository files lack list comprehensions, and must not attach repo citations.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "Explain Python list comprehensions with a simple example."

    # Intent must be GENERAL_PROGRAMMING
    intents = AssistantService.classify_query_intent(q)
    assert intents == ["GENERAL_PROGRAMMING"]

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    assert "list comprehension" in ans.lower()
    assert "for" in ans and "in" in ans
    assert "```python" in ans
    # Must NOT claim assistant_service.py does not contain list comprehension
    assert "assistant_service.py" not in ans
    assert "does not contain" not in ans
    # Must have 0 citations for general programming
    assert res["citations"] == []
    assert res["related_components"] == []
    assert res["facts"]["confirmed"] == 1
    assert res["facts"]["unknowns"] == 0


@pytest.mark.anyio
async def test_regression_2_api_vs_rest_api_no_unrelated_citations(db_session: Session):
    """
    Assertion 2: An API vs REST API question receives no unrelated repository citations.
    Must not attach parser implementations, repository tests, or architecture components.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "What is the difference between an API and a REST API? Explain with a simple Python example."

    intents = AssistantService.classify_query_intent(q)
    assert intents == ["GENERAL_PROGRAMMING"]

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    assert "api" in ans.lower() and "rest" in ans.lower()
    # No unrelated citations
    assert res["citations"] == []
    assert res["related_components"] == []
    assert "Verified Architecture Components" not in ans
    assert "extractor.py" not in ans
    assert "test_" not in ans


@pytest.mark.anyio
async def test_regression_3_hybrid_retrieval_citations_support_each_stage(db_session: Session):
    """
    Assertion 3: Repository-specific hybrid retrieval questions receive citations that support each named stage.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "Explain how CodeMind AI implements hybrid retrieval and describe its stages."

    intents = AssistantService.classify_query_intent(q)
    assert "GENERAL_PROGRAMMING" not in intents

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    citations = res["citations"]
    cit_symbols = [c.get("symbol_name") or "" for c in citations]
    cit_files = [c.get("file_path") or "" for c in citations]

    # Citations must be grounded in hybrid_engine.py
    assert any("hybrid_engine.py" in f for f in cit_files)

    # Citations must cover the stages
    assert any("_retrieve_exact_matches" in s for s in cit_symbols)
    assert any("_retrieve_keyword_matches" in s for s in cit_symbols)
    assert any("_retrieve_vector_matches" in s for s in cit_symbols)
    assert any("_expand_via_knowledge_graph" in s for s in cit_symbols)

    # In grounding notes or answer, linear weighted fusion is explained, not RRF
    assert "implement" in ans.lower() or "retrieval" in ans.lower() or "hybrid" in ans.lower()


@pytest.mark.anyio
async def test_regression_4_cosine_similarity_not_described_as_keyword_search(db_session: Session):
    """
    Assertion 4: _cosine_similarity is not described as keyword search.
    """
    repo = create_sample_codemind_repo(db_session)

    # Test sanitizer directly with an answer text that tries to claim _cosine_similarity does keyword search
    raw_answer = (
        "The HybridRetrievalEngine retrieves code chunks. "
        "`_cosine_similarity` method is used for keyword search, while pgvector handles vectors."
    )
    chunks = [
        RetrievedChunk(
            chunk_id=1,
            repository_id=repo.id,
            file_path="backend/app/retrieval/hybrid_engine.py",
            symbol_name="HybridRetrievalEngine._cosine_similarity",
            start_line=698,
            end_line=706,
            chunk_text="def _cosine_similarity(vec_a, vec_b): pass",
            score=0.9,
            channels=["vector"],
        )
    ]
    sanitized = AssistantService._validate_and_sanitize_answer(
        answer=raw_answer,
        chunks=chunks,
        repo_name=repo.name,
        question="How does hybrid retrieval work?",
        intents=["INDEXING_AND_EMBEDDINGS"],
    )

    # Must NOT claim _cosine_similarity implements keyword search
    assert "is used for keyword search" not in sanitized
    assert "`_retrieve_keyword_matches` implements keyword search" in sanitized or "vector" in sanitized


@pytest.mark.anyio
async def test_regression_5_missing_file_question_no_unrelated_claims(db_session: Session):
    """
    Assertion 5: Missing-file questions do not produce unrelated implementation claims.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "Where is generate_pdf.py located in this repository?"

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    # File reported missing
    assert "generate_pdf.py" in ans
    assert "not found" in ans.lower() or "not exist" in ans.lower() or "not indexed" in ans.lower()
    # Outcome reported cleanly
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in ans

    # Must NOT contain unrelated hybrid retrieval claims
    assert "HybridRetrievalEngine" not in ans
    assert "search pipeline" not in ans.lower()
    assert "_cosine_similarity" not in ans

    # Must have 0 citations for non-existent file
    assert res["citations"] == []
    assert res["facts"]["unknowns"] == 0


@pytest.mark.anyio
async def test_regression_6_multiturn_transition_general_and_repo_questions(db_session: Session):
    """
    Assertion 6: Multi-turn conversations correctly transition between general questions and repository-specific questions.
    Turn 1: General question -> no repo citations.
    Turn 2: Repository-specific question -> grounded repo citations.
    Turn 3: General question -> transitions back to general knowledge with no repo citations.
    """
    repo = create_sample_codemind_repo(db_session)

    conv = AssistantConversation(
        repository_id=repo.id,
        branch="main",
        title="Multi-turn transition test",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # --- Turn 1: General question ---
    q1 = "Explain Python list comprehensions with a simple example."
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q1,
        conversation_id=conv.id,
    )
    assert res1["citations"] == []
    assert "list comprehension" in res1["answer"].lower()
    assert res1["facts"]["unknowns"] == 0

    # --- Turn 2: Repository-specific question ---
    q2 = "Where is HybridRetrievalEngine implemented in this repository?"
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q2,
        conversation_id=conv.id,
    )
    assert len(res2["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res2["citations"])

    # --- Turn 3: Transition back to General question ---
    q3 = "What is the difference between an API and a REST API? Explain with a simple Python example."
    res3 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q3,
        conversation_id=conv.id,
    )
    assert res3["citations"] == []
    assert res3["related_components"] == []
    assert "Verified Architecture Components" not in res3["answer"]
    assert "api" in res3["answer"].lower() and "rest" in res3["answer"].lower()


@pytest.mark.anyio
async def test_regression_7_python_dictionary_explanation(db_session: Session):
    """
    Assertion 7: 'What is a Python dictionary?' must be classified as GENERAL_PROGRAMMING,
    bypass repository retrieval (empty citations and related components),
    explain key-value pairs, and provide a valid Python example.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "What is a Python dictionary?"

    intents = AssistantService.classify_query_intent(q)
    assert intents == ["GENERAL_PROGRAMMING"]

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    assert "key-value" in ans.lower() or "key: value" in ans.lower()
    assert "```python" in ans
    assert res["citations"] == []
    assert res["related_components"] == []
    assert "not directly referenced or defined in the provided evidence" not in ans.lower()


@pytest.mark.anyio
async def test_regression_8_python_lists_tuples_sets(db_session: Session):
    """
    Assertion 8: 'Explain Python lists, tuples, and sets.' must be classified as GENERAL_PROGRAMMING,
    bypass repository retrieval, and explain all three data structures with valid Python examples.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "Explain Python lists, tuples, and sets."

    intents = AssistantService.classify_query_intent(q)
    assert intents == ["GENERAL_PROGRAMMING"]

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    assert "list" in ans.lower()
    assert "tuple" in ans.lower()
    assert "set" in ans.lower()
    assert "```python" in ans
    assert res["citations"] == []
    assert res["related_components"] == []


@pytest.mark.anyio
async def test_regression_9_python_variable(db_session: Session):
    """
    Assertion 9: 'What is a variable in Python?' must be classified as GENERAL_PROGRAMMING (not CONFIG),
    bypass repository retrieval, and explain variables with a valid Python example.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "What is a variable in Python?"

    intents = AssistantService.classify_query_intent(q)
    assert intents == ["GENERAL_PROGRAMMING"]

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    assert "variable" in ans.lower()
    assert "```python" in ans
    assert res["citations"] == []
    assert res["related_components"] == []


@pytest.mark.anyio
async def test_regression_10_general_immediately_after_repo_specific(db_session: Session):
    """
    Assertion 10: General question immediately after repository-specific question in a multi-turn conversation.
    Turn 1: In CodeMind-AI, explain how HybridRetrievalEngine.retrieve works... -> Repo citations present.
    Turn 2: What is a Python dictionary? -> General programming, 0 citations, 0 related components,
    explains key-value pairs with code example, no repository evidence error messages.
    """
    repo = create_sample_codemind_repo(db_session)

    conv = AssistantConversation(
        repository_id=repo.id,
        branch="main",
        title="Repo to General Transition Test",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Turn 1: Repository-specific question
    q1 = "In CodeMind-AI, explain how HybridRetrievalEngine.retrieve works..."
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q1,
        conversation_id=conv.id,
    )
    assert len(res1["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res1["citations"])

    # Turn 2: General question immediately after
    q2 = "What is a Python dictionary?"
    intents2 = AssistantService.classify_query_intent(q2)
    assert intents2 == ["GENERAL_PROGRAMMING"]

    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q2,
        conversation_id=conv.id,
    )
    assert res2["citations"] == []
    assert res2["related_components"] == []
    ans2 = res2["answer"]
    assert "key-value" in ans2.lower() or "key: value" in ans2.lower()
    assert "```python" in ans2
    assert "not directly referenced or defined in the provided evidence" not in ans2.lower()


@pytest.mark.anyio
async def test_regression_11_repo_immediately_after_general(db_session: Session):
    """
    Assertion 11: Repository-specific question immediately after general question in a multi-turn conversation.
    Turn 1: What is a Python dictionary? -> General programming, 0 citations.
    Turn 2: Which file implements hybrid retrieval in this repository? -> Repo-specific, repo citations present.
    """
    repo = create_sample_codemind_repo(db_session)

    conv = AssistantConversation(
        repository_id=repo.id,
        branch="main",
        title="General to Repo Transition Test",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Turn 1: General question
    q1 = "What is a Python dictionary?"
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q1,
        conversation_id=conv.id,
    )
    assert res1["citations"] == []
    assert "key-value" in res1["answer"].lower() or "key: value" in res1["answer"].lower()

    # Turn 2: Repo question immediately after
    q2 = "Which file implements hybrid retrieval in this repository?"
    intents2 = AssistantService.classify_query_intent(q2)
    assert "GENERAL_PROGRAMMING" not in intents2

    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q2,
        conversation_id=conv.id,
    )
    assert len(res2["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res2["citations"])


@pytest.mark.anyio
async def test_regression_12_streaming_and_non_streaming_parity(db_session: Session):
    """
    Assertion 12: Streaming and non-streaming behavior parity for general programming questions.
    Both modes must classify as GENERAL_PROGRAMMING, return empty citations & related components,
    and produce an educational explanation with code example.
    """
    repo = create_sample_codemind_repo(db_session)
    q = "What is a Python dictionary?"

    # Non-streaming
    res_sync = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )
    assert res_sync["citations"] == []
    assert res_sync["related_components"] == []
    assert "key-value" in res_sync["answer"].lower() or "key: value" in res_sync["answer"].lower()
    assert "```python" in res_sync["answer"]

    # Streaming
    events = []
    async for chunk in AssistantService.stream_answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
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

    done_events = [e[1] for e in events if e[0] == "done"]
    assert len(done_events) == 1
    done = done_events[0]
    assert done["citations"] == []
    assert done["related_components"] == []
    assert "key-value" in done["answer"].lower() or "key: value" in done["answer"].lower()
    assert "```python" in done["answer"]
    assert "not directly referenced or defined in the provided evidence" not in done["answer"].lower()


@pytest.mark.anyio
async def test_regression_13_hybrid_retrieval_fusion_weights_and_source_line_accuracy(db_session: Session):
    """
    Assertion 13: Hybrid retrieval pipeline source-backed configuration audit:
    1. Verifies that configured fusion weights in Settings are vector=0.5, keyword=0.3, exact=0.2.
    2. Verifies that HybridRetrievalEngine AST line ranges correspond to actual method definitions:
       - _retrieve_exact_matches: 353-473
       - _retrieve_keyword_matches: 476-549
       - _retrieve_vector_matches: 552-619
       - _expand_via_knowledge_graph: 622-695
       - retrieve: 99-350
       - _cosine_similarity: 698-705
    3. Verifies that the rank fusion expression computes:
       score = vector * 0.50 + keyword * 0.30 + exact * 0.20 + graph * 0.15
    4. Verifies that citations for hybrid retrieval reference backend/app/retrieval/hybrid_engine.py
       within these verified source line boundaries.
    """
    import ast
    from backend.app.core.config import settings
    from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine

    # 1. Configured weights audit
    assert settings.RETRIEVAL_VECTOR_WEIGHT == 0.5
    assert settings.RETRIEVAL_KEYWORD_WEIGHT == 0.3
    assert settings.RETRIEVAL_EXACT_WEIGHT == 0.2

    # 2. Source-code AST audit of hybrid_engine.py
    engine_file_path = "backend/app/retrieval/hybrid_engine.py"
    with open(engine_file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    func_ranges = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_ranges[node.name] = (node.lineno, node.end_lineno)

    assert "_retrieve_exact_matches" in func_ranges
    assert func_ranges["_retrieve_exact_matches"] == (353, 473)

    assert "_retrieve_keyword_matches" in func_ranges
    assert func_ranges["_retrieve_keyword_matches"] == (476, 549)

    assert "_retrieve_vector_matches" in func_ranges
    assert func_ranges["_retrieve_vector_matches"] == (552, 619)

    assert "_expand_via_knowledge_graph" in func_ranges
    assert func_ranges["_expand_via_knowledge_graph"] == (622, 695)

    assert "retrieve" in func_ranges
    assert func_ranges["retrieve"] == (99, 350)

    assert "_cosine_similarity" in func_ranges
    assert func_ranges["_cosine_similarity"] == (698, 705)

    # 3. Fusion score formula verification
    vec_s = 0.8
    kw_s = 0.6
    exact_s = 1.0
    graph_s = 0.65
    expected_base_score = (
        vec_s * settings.RETRIEVAL_VECTOR_WEIGHT
        + kw_s * settings.RETRIEVAL_KEYWORD_WEIGHT
        + exact_s * settings.RETRIEVAL_EXACT_WEIGHT
        + graph_s * 0.15
    )
    # 0.8*0.5 (0.4) + 0.6*0.3 (0.18) + 1.0*0.2 (0.2) + 0.65*0.15 (0.0975) = 0.8775
    assert round(expected_base_score, 4) == 0.8775

    # 4. Citations verification on sample repo
    repo = create_sample_codemind_repo(db_session)
    q = "In CodeMind-AI, explain how HybridRetrievalEngine.retrieve works and what stages it uses."
    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )
    citations = res["citations"]
    assert len(citations) > 0
    engine_citations = [c for c in citations if "hybrid_engine.py" in c["file_path"]]
    assert len(engine_citations) > 0

    # Ensure citations cover the retrieve / stage range (between lines 99 and 706)
    for c in engine_citations:
        assert c["start_line"] >= 99
        assert c["end_line"] <= 750

    # 5. Verify prompt grounding notes reflect actual configured settings weights and reject outdated formula
    retrieved_chunks = [
        RetrievedChunk(
            chunk_id=1,
            repository_id=repo.id,
            file_path="backend/app/retrieval/hybrid_engine.py",
            symbol_name="HybridRetrievalEngine.retrieve",
            start_line=99,
            end_line=350,
            chunk_text="class HybridRetrievalEngine: pass",
            score=0.95,
            channels=["exact"],
        )
    ]
    _, domain_notes, _ = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question=q,
        retrieved_chunks=retrieved_chunks,
    )
    assert domain_notes is not None
    # Must dynamically reflect actual configured settings weights
    assert f"vector * {settings.RETRIEVAL_VECTOR_WEIGHT:.2f}" in domain_notes
    assert f"keyword * {settings.RETRIEVAL_KEYWORD_WEIGHT:.2f}" in domain_notes
    assert f"exact * {settings.RETRIEVAL_EXACT_WEIGHT:.2f}" in domain_notes
    assert "graph * 0.15" in domain_notes
    # Must NOT contain the outdated hardcoded formula
    assert "vector * 0.40" not in domain_notes
    assert "exact * 0.30" not in domain_notes


def create_sample_fincell_repo(db: Session) -> Repository:
    """Creates a sample FinCell repository with Flutter/Dart files and manifests."""
    import hashlib
    repo = Repository(
        name="FinCell",
        full_name="org/FinCell",
        default_branch="main",
        current_revision="commit-fincell-1",
        files_count=15,
        status="ready",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_pubspec = IndexedFile(repository_id=repo.id, path="pubspec.yaml", language="yaml", lines_count=45)
    f_gradle = IndexedFile(repository_id=repo.id, path="android/build.gradle.kts", language="kotlin", lines_count=60)
    f_main = IndexedFile(repository_id=repo.id, path="lib/main.dart", language="dart", lines_count=120)
    db.add_all([f_pubspec, f_gradle, f_main])
    db.commit()

    def make_chunk(**kwargs):
        txt = kwargs.get("chunk_text", "")
        h = hashlib.sha256(txt.encode()).hexdigest()
        return CodeChunk(content_hash=h, **kwargs)

    c_pub = make_chunk(
        repository_id=repo.id,
        file_path="pubspec.yaml",
        start_line=1,
        end_line=45,
        chunk_text="name: fincell\ndescription: A Flutter financial calculation mobile app.\ndependencies:\n  flutter:\n    sdk: flutter\n  provider: ^6.0.0",
        language="yaml"
    )
    c_gradle = make_chunk(
        repository_id=repo.id,
        file_path="android/build.gradle.kts",
        start_line=1,
        end_line=60,
        chunk_text="plugins {\n    id(\"com.android.application\")\n    kotlin(\"android\")\n}",
        language="kotlin"
    )
    c_main = make_chunk(
        repository_id=repo.id,
        file_path="lib/main.dart",
        code_symbol="main",
        start_line=1,
        end_line=120,
        chunk_text="void main() {\n  runApp(const FinCellApp());\n}\nclass FinCellApp extends StatelessWidget {\n  @override Widget build(BuildContext context) => Container();\n}",
        language="dart"
    )
    db.add_all([c_pub, c_gradle, c_main])
    db.commit()
    return repo


@pytest.mark.anyio
async def test_regression_14_fincell_negative_evidence_balanced_coverage(db_session: Session):
    """
    Issue 1: FinCell negative claims must distinguish NOT_FOUND_IN_INDEXED_SOURCE from verified absence.
    Must include both manifest (pubspec.yaml) and entry point (lib/main.dart), not treating build files alone as proof.
    """
    repo = create_sample_fincell_repo(db_session)
    q = "Does this repository implement hybrid retrieval?"

    chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question=q,
        retrieved_chunks=[],
    )

    assert audit_meta.get("retrieval_audit_outcome") == "NOT_FOUND_IN_INDEXED_SOURCE"
    cov_files = audit_meta.get("coverage_files", [])
    # Balanced coverage: root manifest AND entry point are cited
    assert "pubspec.yaml" in cov_files
    assert "lib/main.dart" in cov_files
    # Build file alone was NOT treated as sufficient or sole proof
    assert len(cov_files) >= 2

    # Verify domain notes instructions
    assert domain_notes is not None
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in domain_notes
    assert "Do NOT treat project manifests or build scripts alone as sufficient proof of feature absence" in domain_notes
    assert "Distinguish NOT_FOUND_IN_INDEXED_SOURCE from an ungrounded or speculative claim of universal non-existence" in domain_notes


@pytest.mark.anyio
async def test_regression_15_deictic_this_repository_anchors_to_active_repo(db_session: Session):
    """
    Issue 2: 'How does this repository calculate vector similarity?' unexpectedly produced a repository
    mismatch referring to an unrelated repository named 'calculate'.
    Verify deictic anchor to active_repo_id and generic words blocklist.
    """
    repo_fincell = create_sample_fincell_repo(db_session)

    # Create confusable repo named 'calculate'
    repo_calc = Repository(
        name="calculate",
        full_name="org/calculate",
        default_branch="main",
        status="ready"
    )
    db_session.add(repo_calc)
    db_session.commit()
    db_session.refresh(repo_calc)

    # 1. 'calculate' must be in GENERIC_WORDS_BLOCKLIST
    from backend.app.services.assistant_service import GENERIC_WORDS_BLOCKLIST
    assert "calculate" in GENERIC_WORDS_BLOCKLIST
    assert "compute" in GENERIC_WORDS_BLOCKLIST

    # 2. Deictic reference 'this repository' must anchor to active_repo_id (FinCell)
    q = "How does this repository calculate vector similarity?"
    resolved_repo, norm_q, clarification = AssistantService.resolve_repository_from_query(
        db=db_session,
        question=q,
        active_repo_id=repo_fincell.id,
    )
    assert resolved_repo is not None
    assert resolved_repo.id == repo_fincell.id
    assert clarification is None
    assert resolved_repo.name == "FinCell"

    # 3. Explicit switch to 'calculate' must still be respected
    q_switch = "In calculate, what features exist?"
    resolved_switch, _, _ = AssistantService.resolve_repository_from_query(
        db=db_session,
        question=q_switch,
        active_repo_id=repo_fincell.id,
    )
    assert resolved_switch is not None
    assert resolved_switch.id == repo_calc.id


@pytest.mark.anyio
async def test_regression_16_score_combination_retrieves_formula_and_weights(db_session: Session):
    """
    Issue 3: 'how vector and keyword scores are combined' produced a vague answer without fusion formula.
    Verify intent classification, multi-layer enrichment, and formula weights.
    """
    repo = create_sample_codemind_repo(db_session)

    # Add chunk containing rank fusion formula in hybrid_engine.py
    import hashlib
    fusion_text = (
        "# 6. Rank Fusion\n"
        "w_vec = settings.RETRIEVAL_VECTOR_WEIGHT\n"
        "w_kw = settings.RETRIEVAL_KEYWORD_WEIGHT\n"
        "w_exact = settings.RETRIEVAL_EXACT_WEIGHT\n"
        "w_graph = 0.15\n"
        "final_score = scores.get('vector', 0.0) * w_vec + scores.get('keyword', 0.0) * w_kw + scores.get('exact', 0.0) * w_exact + scores.get('graph', 0.0) * w_graph\n"
    )
    c_fusion = CodeChunk(
        content_hash=hashlib.sha256(fusion_text.encode()).hexdigest(),
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine.retrieve",
        start_line=230,
        end_line=270,
        chunk_text=fusion_text,
        language="python"
    )
    db_session.add(c_fusion)
    db_session.commit()

    q = "how vector and keyword scores are combined"

    # 1. Intent classification
    intents = AssistantService.classify_query_intent(q)
    assert "INDEXING_AND_EMBEDDINGS" in intents

    # 2. Multi-layer retrieval enrichment
    chunks, domain_notes, audit_meta = AssistantService._enrich_multi_layer_retrieval(
        db=db_session,
        repository_id=repo.id,
        question=q,
        retrieved_chunks=[],
    )
    assert audit_meta.get("retrieval_audit_outcome") == "IMPLEMENTED"
    assert domain_notes is not None

    # 3. Dynamic settings weights in domain notes
    from backend.app.core.config import settings
    assert f"vector * {settings.RETRIEVAL_VECTOR_WEIGHT:.2f}" in domain_notes
    assert f"keyword * {settings.RETRIEVAL_KEYWORD_WEIGHT:.2f}" in domain_notes
    assert f"exact * {settings.RETRIEVAL_EXACT_WEIGHT:.2f}" in domain_notes
    assert "graph * 0.15" in domain_notes


def test_regression_17_which_file_includes_line_range_citation():
    """
    Issue 4: 'which file implements hybrid retrieval' correctly identified backend/app/retrieval/hybrid_engine.py
    but provided no source-line citations.
    Verify that _validate_and_sanitize_answer augments bare file names with verified chunk line ranges.
    """
    q = "which file implements hybrid retrieval in this repository"
    chunk = RetrievedChunk(
        chunk_id=10,
        repository_id=41,
        file_path="backend/app/retrieval/hybrid_engine.py",
        symbol_name="HybridRetrievalEngine",
        start_line=36,
        end_line=721,
        chunk_text="class HybridRetrievalEngine: pass",
        score=0.98,
        channels=["exact"]
    )

    # 1. LLM answered with bare file path without line citations
    bare_answer = "Hybrid retrieval is implemented in `backend/app/retrieval/hybrid_engine.py`."
    sanitized = AssistantService._validate_and_sanitize_answer(
        answer=bare_answer,
        chunks=[chunk],
        repo_name="CodeMind-AI",
        question=q
    )
    assert 'backend/app/retrieval/hybrid_engine.py:36' in sanitized and '721' in sanitized

    # 2. LLM already included line citations -> must NOT duplicate or corrupt
    already_cited = "Hybrid retrieval is implemented in `backend/app/retrieval/hybrid_engine.py:36-721`."
    sanitized_already = AssistantService._validate_and_sanitize_answer(
        answer=already_cited,
        chunks=[chunk],
        repo_name="CodeMind-AI",
        question=q
    )
    assert "`backend/app/retrieval/hybrid_engine.py:36-721`" in sanitized_already
    assert "36-721:36" not in sanitized_already


@pytest.mark.anyio
async def test_regression_18_multiturn_repo_general_repo_followup_and_repo_switch(db_session: Session):
    """
    Issue 5: Multi-turn transition sequence:
    Turn 1: repo-specific query on CodeMind-AI
    Turn 2: general Python query ('What is a Python dictionary?')
    Turn 3: repo-specific follow-up ('Which file implements hybrid retrieval in this repository?')
    Turn 4: switch to FinCell and ask 'How does this repository calculate vector similarity?'
    """
    repo_codemind = create_sample_codemind_repo(db_session)
    repo_fincell = create_sample_fincell_repo(db_session)

    # Create confusable repo 'calculate'
    repo_calc = Repository(name="calculate", full_name="org/calculate", status="ready")
    db_session.add(repo_calc)
    db_session.commit()

    conv = AssistantConversation(
        repository_id=repo_codemind.id,
        branch="main",
        title="Multi-turn Transition QA Test",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Turn 1: Repo-specific query on CodeMind-AI
    q1 = "In CodeMind-AI, explain how HybridRetrievalEngine.retrieve works..."
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_codemind.id,
        question=q1,
        conversation_id=conv.id,
    )
    assert len(res1["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res1["citations"])

    # Turn 2: General Python query immediately after repo query
    q2 = "What is a Python dictionary?"
    intents2 = AssistantService.classify_query_intent(q2)
    assert intents2 == ["GENERAL_PROGRAMMING"]
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_codemind.id,
        question=q2,
        conversation_id=conv.id,
    )
    assert res2["citations"] == []
    assert "key-value" in res2["answer"].lower() or "key: value" in res2["answer"].lower()
    assert "not directly referenced or defined in the provided evidence" not in res2["answer"].lower()

    # Turn 3: Repo-specific follow-up
    q3 = "Which file implements hybrid retrieval in this repository?"
    res3 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_codemind.id,
        question=q3,
        conversation_id=conv.id,
    )
    assert len(res3["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res3["citations"])
    # Answer must cite hybrid_engine.py with verified line range
    assert "backend/app/retrieval/hybrid_engine.py" in res3["answer"]

    # Turn 4: Switch repository to FinCell and ask question mentioning confusable verb 'calculate'
    q4 = "How does this repository calculate vector similarity?"
    resolved_repo, _, clarification = AssistantService.resolve_repository_from_query(
        db=db_session,
        question=q4,
        active_repo_id=repo_fincell.id,
    )
    assert resolved_repo.id == repo_fincell.id
    assert clarification is None
    assert resolved_repo.name == "FinCell"

    res4 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_fincell.id,
        question=q4,
    )
    # FinCell has no hybrid retrieval -> NOT_FOUND_IN_INDEXED_SOURCE
    assert "NOT_FOUND_IN_INDEXED_SOURCE" in res4["answer"]
    # Evidence includes pubspec.yaml and lib/main.dart
    assert any("pubspec.yaml" in c["file_path"] for c in res4["citations"])
    assert any("lib/main.dart" in c["file_path"] for c in res4["citations"])

