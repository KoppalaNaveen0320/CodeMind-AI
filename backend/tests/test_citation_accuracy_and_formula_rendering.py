import ast
import json
from pathlib import Path
import subprocess
import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.repository import Repository
from backend.app.models.indexed_file import IndexedFile
from backend.app.models.code_chunk import CodeChunk
from backend.app.models.code_symbol import CodeSymbol
from backend.app.models.assistant import AssistantConversation, AssistantMessage
from backend.app.retrieval.hybrid_engine import HybridRetrievalEngine, RetrievedChunk
from backend.app.services.assistant_service import AssistantService


def create_test_codemind_repo(db: Session) -> Repository:
    """Creates a sample CodeMind-AI repository with actual chunks matching runtime code."""
    import hashlib

    repo = Repository(
        name="CodeMind-AI",
        full_name="KoppalaNaveen0320/CodeMind-AI",
        description="AI code intelligence platform",
        default_branch="main",
        current_revision="rev-cm-test-1",
        files_count=12,
        status="ready",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    f_engine = IndexedFile(
        repository_id=repo.id,
        path="backend/app/retrieval/hybrid_engine.py",
        language="python",
        lines_count=721,
    )
    f_config = IndexedFile(
        repository_id=repo.id,
        path="backend/app/core/config.py",
        language="python",
        lines_count=141,
    )
    db.add_all([f_engine, f_config])
    db.commit()

    def make_chunk(**kwargs):
        txt = kwargs.get("chunk_text", "")
        h = hashlib.sha256(txt.encode()).hexdigest()
        return CodeChunk(content_hash=h, **kwargs)

    # 1. Main orchestration method chunk: retrieve (lines 99-350)
    c_orchestration = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine.retrieve",
        start_line=99,
        end_line=350,
        chunk_text=(
            "async def retrieve(cls, db: Session, repository_id: int, query: str, ...) -> List[RetrievedChunk]:\n"
            "    # Executes hybrid retrieval across vector, keyword, exact, and graph channels.\n"
            "    # Verifies user repository authorization before querying.\n"
            "    pass"
        ),
        language="python",
    )

    # 2. Exact match channel chunk (lines 353-473)
    c_exact = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_exact_matches",
        start_line=353,
        end_line=473,
        chunk_text=(
            "def _retrieve_exact_matches(cls, db: Session, repo_id: int, query: str, language: Optional[str], ...) -> List[CodeChunk]:\n"
            "    # Finds chunks with exact matching symbol names, file paths, or explicitly requested files.\n"
            "    pass"
        ),
        language="python",
    )

    # 3. Keyword match channel chunk (lines 476-549)
    c_kw = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_keyword_matches",
        start_line=476,
        end_line=549,
        chunk_text=(
            "def _retrieve_keyword_matches(cls, db: Session, repo_id: int, query: str, language: Optional[str]) -> List[tuple]:\n"
            "    # Finds chunks using keyword match or PostgreSQL full text, filtering out English stopwords.\n"
            "    pass"
        ),
        language="python",
    )

    # 4. Semantic vector channel chunk: PostgreSQL path (lines 552-620)
    c_vec = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._retrieve_vector_matches",
        start_line=552,
        end_line=620,
        chunk_text=(
            "async def _retrieve_vector_matches(cls, db: Session, repo_id: int, query: str, language: Optional[str]) -> List[tuple]:\n"
            "    # Use native pgvector cosine distance: 1 - cosine_distance = cosine similarity\n"
            "    distance = CodeChunk.embedding.cosine_distance(query_vector)\n"
            "    # Fallback to _cosine_similarity\n"
            "    return [(chunk, max(0.0, 1.0 - float(dist))) for chunk, dist in chunks_with_dist]"
        ),
        language="python",
    )

    # 5. Knowledge graph channel chunk (lines 622-695)
    c_graph = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._expand_via_knowledge_graph",
        start_line=622,
        end_line=695,
        chunk_text=(
            "def _expand_via_knowledge_graph(cls, db: Session, repo_id: int, initial_candidates: Dict[int, RetrievedChunk]) -> List[tuple]:\n"
            "    # Finds related code chunks via Knowledge Graph relationships: CALLS, IMPORTS, DEFINES\n"
            "    pass"
        ),
        language="python",
    )

    # 6. Rank fusion calculation chunk (lines 230-268)
    c_fusion = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine.retrieve",
        start_line=230,
        end_line=268,
        chunk_text=(
            "# 6. Rank Fusion (Weighted Combination with Code-Over-Documentation Prioritization)\n"
            "w_vec = settings.RETRIEVAL_VECTOR_WEIGHT\n"
            "w_kw = settings.RETRIEVAL_KEYWORD_WEIGHT\n"
            "w_exact = settings.RETRIEVAL_EXACT_WEIGHT\n"
            "w_graph = 0.15\n"
            "final_score = (\n"
            "    scores.get('vector', 0.0) * w_vec\n"
            "    + scores.get('keyword', 0.0) * w_kw\n"
            "    + scores.get('exact', 0.0) * w_exact\n"
            "    + scores.get('graph', 0.0) * w_graph\n"
            ")"
        ),
        language="python",
    )

    # 7. In-memory cosine similarity fallback chunk (lines 698-706)
    c_cos = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/retrieval/hybrid_engine.py",
        code_symbol="HybridRetrievalEngine._cosine_similarity",
        start_line=698,
        end_line=706,
        chunk_text=(
            "def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:\n"
            "    dot = sum(a * b for a, b in zip(vec_a, vec_b))\n"
            "    norm_a = math.sqrt(sum(a * a for a in vec_a))\n"
            "    norm_b = math.sqrt(sum(b * b for b in vec_b))\n"
            "    return max(0.0, min(1.0, dot / (norm_a * norm_b)))"
        ),
        language="python",
    )

    # 8. Weight configuration definitions chunk in config.py (lines 80-86)
    c_config = make_chunk(
        repository_id=repo.id,
        file_path="backend/app/core/config.py",
        code_symbol="Settings",
        start_line=80,
        end_line=86,
        chunk_text=(
            "# Chunking & Hybrid Retrieval\n"
            "CHUNK_SIZE_LINES: int = 60\n"
            "CHUNK_OVERLAP_LINES: int = 15\n"
            "RETRIEVAL_TOP_K: int = 8\n"
            "RETRIEVAL_VECTOR_WEIGHT: float = 0.5\n"
            "RETRIEVAL_KEYWORD_WEIGHT: float = 0.3\n"
            "RETRIEVAL_EXACT_WEIGHT: float = 0.2\n"
        ),
        language="python",
    )

    db.add_all([c_orchestration, c_exact, c_kw, c_vec, c_graph, c_fusion, c_cos, c_config])

    # Add symbols
    symbols = [
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="HybridRetrievalEngine", kind="class", start_line=36, end_line=721),
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="retrieve", kind="method", start_line=99, end_line=350),
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="_retrieve_exact_matches", kind="method", start_line=353, end_line=473),
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="_retrieve_keyword_matches", kind="method", start_line=476, end_line=549),
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="_retrieve_vector_matches", kind="method", start_line=552, end_line=620),
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="_expand_via_knowledge_graph", kind="method", start_line=622, end_line=695),
        CodeSymbol(repository_id=repo.id, file_id=f_engine.id, name="_cosine_similarity", kind="method", start_line=698, end_line=706),
        CodeSymbol(repository_id=repo.id, file_id=f_config.id, name="Settings", kind="class", start_line=7, end_line=141),
    ]
    db.add_all(symbols)
    db.commit()

    return repo


# ==============================================================================
# Part 3: Retrieval and Citation Tests
# ==============================================================================

@pytest.mark.anyio
async def test_score_combination_retrieves_actual_fusion_formula_and_cites_correct_lines(db_session: Session):
    """
    Test 1: Score-combination questions retrieve the actual fusion formula (lines 230-268)
    and cite both the fusion calculation in hybrid_engine.py and weight definitions in config.py.
    """
    repo = create_test_codemind_repo(db_session)
    q = "How are vector and keyword scores combined?"

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    citations = res["citations"]
    cit_files = [c["file_path"] for c in citations]

    # Must cite both hybrid_engine.py and config.py
    assert any("hybrid_engine.py" in f for f in cit_files)
    assert any("config.py" in f for f in cit_files)

    # Citations for hybrid_engine.py must cover the actual fusion calculation (lines 230-268)
    fusion_cit = next(c for c in citations if "hybrid_engine.py" in c["file_path"])
    assert fusion_cit["start_line"] <= 235 and fusion_cit["end_line"] >= 265

    # Citations for config.py must cover the weight definitions (lines 80-86)
    config_cit = next(c for c in citations if "config.py" in c["file_path"])
    assert config_cit["start_line"] <= 85 and config_cit["end_line"] >= 83

    # Answer must render the formula using display math notation
    assert "\\[" in ans and "\\]" in ans
    assert "0.50" in ans or "0.5" in ans
    assert "0.30" in ans or "0.3" in ans
    assert "0.20" in ans or "0.2" in ans
    assert "0.15" in ans


@pytest.mark.anyio
async def test_weight_values_match_runtime_settings_and_configuration_definitions(db_session: Session):
    """
    Test 2: Weight values match the runtime settings and configuration definitions.
    """
    assert settings.RETRIEVAL_VECTOR_WEIGHT == 0.5
    assert settings.RETRIEVAL_KEYWORD_WEIGHT == 0.3
    assert settings.RETRIEVAL_EXACT_WEIGHT == 0.2

    # Verify AST of backend/app/core/config.py
    with open("backend/app/core/config.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    config_vars = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant):
                config_vars[node.target.id] = node.value.value

    assert config_vars.get("RETRIEVAL_VECTOR_WEIGHT") == 0.5
    assert config_vars.get("RETRIEVAL_KEYWORD_WEIGHT") == 0.3
    assert config_vars.get("RETRIEVAL_EXACT_WEIGHT") == 0.2


@pytest.mark.anyio
async def test_which_file_implements_hybrid_retrieval_cites_orchestration_and_channels(db_session: Session):
    """
    Test 3: 'Which file implements hybrid retrieval?' identifies backend/app/retrieval/hybrid_engine.py,
    cites the orchestration method (lines 99-350) and channel implementations, and does not rely on
    explicit filename matching (_detect_explicit_file_paths) alone.
    """
    repo = create_test_codemind_repo(db_session)
    q = "Which file implements hybrid retrieval in this repository?"

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    citations = res["citations"]

    # Must identify hybrid_engine.py
    assert "hybrid_engine.py" in ans
    assert any("hybrid_engine.py" in c["file_path"] for c in citations)

    # First citation must be the orchestration method or class, NOT _detect_explicit_file_paths alone
    top_cit = citations[0]
    assert "_detect_explicit_file_paths" not in (top_cit.get("symbol_name") or "")
    assert top_cit["start_line"] <= 100 or top_cit["end_line"] >= 340


@pytest.mark.anyio
async def test_vector_similarity_explains_both_pgvector_and_in_memory_fallback(db_session: Session):
    """
    Test 4: Vector similarity answers explain both PostgreSQL cosine distance (1 - cosine_distance)
    and the in-memory fallback (_cosine_similarity) with separate citations, and do not describe it as keyword search.
    """
    repo = create_test_codemind_repo(db_session)
    q = "How does this repository calculate vector similarity?"

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    citations = res["citations"]

    # Must explain PostgreSQL path
    assert "pgvector" in ans.lower() or "postgresql" in ans.lower()
    assert "cosine_distance" in ans or "cosine_distance" in ans.replace(r"\_", "_")
    assert "1.0 - cosine_distance" in ans or "1 - cosine_distance" in ans or "cosine distance" in ans.lower()

    # Must explain in-memory fallback
    assert "_cosine_similarity" in ans
    assert "dot product" in ans.lower() or "norms" in ans.lower()

    # Must NOT describe vector similarity as keyword search
    assert "is used for keyword search" not in ans
    assert "implements keyword search" not in ans.replace("`_retrieve_keyword_matches` implements keyword search", "")

    # Citations must cover both vector matches (552-620) and cosine similarity (698-706)
    cit_symbols = [c.get("symbol_name") or "" for c in citations]
    assert any("_retrieve_vector_matches" in s for s in cit_symbols)
    assert any("_cosine_similarity" in s for s in cit_symbols)


@pytest.mark.anyio
async def test_citation_ranges_correspond_to_retrieved_source_chunks(db_session: Session):
    """
    Test 5: Citation ranges correspond to retrieved source chunks and support the claims made.
    """
    repo = create_test_codemind_repo(db_session)
    q = "What is the formula used for hybrid retrieval scoring?"

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    for cit in res["citations"]:
        assert cit["start_line"] > 0
        assert cit["end_line"] >= cit["start_line"]
        # Verify chunk exists in DB
        matching_chunk = db_session.query(CodeChunk).filter(
            CodeChunk.repository_id == repo.id,
            CodeChunk.file_path == cit["file_path"],
            CodeChunk.start_line == cit["start_line"],
            CodeChunk.end_line == cit["end_line"],
        ).first()
        assert matching_chunk is not None, f"Citation {cit} not found in repository database"


@pytest.mark.anyio
async def test_general_python_questions_remain_independent_of_repo_evidence(db_session: Session):
    """
    Test 6: General Python questions remain independent of repository-specific evidence.
    """
    repo = create_test_codemind_repo(db_session)
    q = "Explain Python list comprehensions with a simple example."

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    assert res["citations"] == []
    assert res["related_components"] == []
    assert "list comprehension" in res["answer"].lower()
    assert "```python" in res["answer"]
    assert "hybrid_engine.py" not in res["answer"]


@pytest.mark.anyio
async def test_multiturn_repo_to_general_to_repo_context_preservation(db_session: Session):
    """
    Test 7: Multi-turn conversations preserve context across repo -> general -> repo transitions.
    """
    repo = create_test_codemind_repo(db_session)

    conv = AssistantConversation(repository_id=repo.id, branch="main", title="Context Preservation Test")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Turn 1: Repo question
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Which file implements hybrid retrieval in this repository?",
        conversation_id=conv.id,
    )
    assert len(res1["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res1["citations"])

    # Turn 2: General question
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="What is a Python dictionary?",
        conversation_id=conv.id,
    )
    assert res2["citations"] == []
    assert "key-value" in res2["answer"].lower() or "key: value" in res2["answer"].lower()

    # Turn 3: Back to Repo question
    res3 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="How are vector and keyword scores combined?",
        conversation_id=conv.id,
    )
    assert len(res3["citations"]) > 0
    assert any("hybrid_engine.py" in c["file_path"] for c in res3["citations"])
    assert "\\[" in res3["answer"] and "\\]" in res3["answer"]


# ==============================================================================
# Part 3: Universal Formula Rendering Tests (Node.js Execution of Frontend Markdown Parser)
# ==============================================================================

def run_js_markdown_test(js_code: str) -> dict:
    """Executes a test snippet against api.js renderMarkdown in Node.js."""
    runner_script = f"""
const fs = require('fs');
const katex = require('{Path("frontend/static/vendor/katex/katex.min.js").resolve().as_posix()}');

// Mock browser globals for api.js
global.katex = katex;
function createMockElement() {{
    let _text = '';
    return {{
        setAttribute: () => {{}},
        appendChild: () => {{}},
        style: {{}},
        set textContent(v) {{ _text = v; }},
        get textContent() {{ return _text; }},
        get innerHTML() {{
            return String(_text)
                .split('&').join('&amp;')
                .split('<').join('&lt;')
                .split('>').join('&gt;')
                .split('"').join('&quot;')
                .split("'").join('&#039;');
        }}
    }};
}}
global.document = {{
    addEventListener: () => {{}},
    removeEventListener: () => {{}},
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    createElement: () => createMockElement(),
    head: {{ appendChild: () => {{}} }},
    body: {{ appendChild: () => {{}} }}
}};
global.window = {{
    addEventListener: () => {{}},
    removeEventListener: () => {{}},
    location: {{ pathname: '/' }},
    localStorage: {{ getItem: () => null, setItem: () => {{}} }}
}};
global.localStorage = global.window.localStorage;
global.navigator = {{ userAgent: 'node' }};

// Load api.js
const apiCode = fs.readFileSync('{Path("frontend/static/js/api.js").resolve().as_posix()}', 'utf-8');
eval(apiCode);

{js_code}
"""
    result = subprocess.run(["node", "-e", runner_script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout.strip())


def test_frontend_display_equations_using_brackets_render_correctly():
    """
    Formula Test 1: Display equations using \[ ... \] render correctly via KaTeX.
    """
    js = r"""
    const input = 'Equation:\n\\[\n\\text{final_score} = 0.50V + 0.30K + 0.20E + 0.15G\n\\]';
    const output = renderMarkdown(input);
    const hasKaTeX = output.includes('katex-display') && output.includes('katex');
    const noRawDelimiters = !output.includes('\\[') && !output.includes('\\]');
    console.log(JSON.stringify({ success: hasKaTeX && noRawDelimiters, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_inline_equations_using_parentheses_render_correctly():
    """
    Formula Test 2: Inline equations using \( ... \) render correctly via KaTeX.
    """
    js = r"""
    const input = 'Where \\(V\\) is vector similarity and \\(E = mc^2\\) is energy.';
    const output = renderMarkdown(input);
    const hasInline = output.includes('math-inline') && output.includes('katex');
    const noRawDelimiters = !output.includes('\\(') && !output.includes('\\)');
    console.log(JSON.stringify({ success: hasInline && noRawDelimiters, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_common_operators_render_correctly():
    """
    Formula Test 3: Common operators (\times, \cdot, \frac, \text, superscripts, subscripts) render correctly.
    """
    js = r"""
    const input = '\\[ x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a} \\quad \\text{and} \\quad a \\times b \\cdot c_{i} \\]';
    const output = renderMarkdown(input);
    const hasKaTeX = output.includes('katex-display') && output.includes('katex');
    const noRawDelimiters = !output.includes('\\[') && !output.includes('\\]');
    console.log(JSON.stringify({ success: hasKaTeX && noRawDelimiters, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_ordinary_markdown_remains_intact_with_equations():
    """
    Formula Test 4: Ordinary Markdown (headings, lists, bold, links) remains intact when equations are present.
    """
    js = r"""
    const input = '# Heading 1\n\n**Bold text** and [Link](https://example.com)\n\n- List item 1\n- List item 2\n\n\\[ a^2 + b^2 = c^2 \\]';
    const output = renderMarkdown(input);
    const hasHeading = output.includes('<h1>Heading 1</h1>');
    const hasBold = output.includes('<strong>Bold text</strong>');
    const hasLink = output.includes('href="https://example.com"');
    const hasList = output.includes('<ul>') && output.includes('<li>List item 1</li>');
    const hasMath = output.includes('katex-display');
    console.log(JSON.stringify({ success: hasHeading && hasBold && hasLink && hasList && hasMath, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_code_blocks_with_formula_text_remain_code_blocks():
    """
    Formula Test 5: Code blocks containing formula-like text remain code blocks rather than being parsed as equations.
    """
    js = r"""
    const input = '```python\n# Formula: [x] = a + b\nprint("\\[ a^2 + b^2 = c^2 \\]")\n```';
    const output = renderMarkdown(input);
    const isCode = output.includes('<pre><code class="language-python">') && output.includes('print(') && output.includes('a^2 + b^2 = c^2');
    const noMath = !output.includes('katex-display');
    console.log(JSON.stringify({ success: isCode && noMath }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_streaming_partial_formula_across_chunks():
    """
    Formula Test 6: Streaming responses that split a formula across multiple chunks render safely during streaming
    and fully upon completion.
    """
    js = r"""
    // 1. Partial chunk during streaming (unclosed display delimiter)
    const streamChunk = 'Calculating score:\n\\[\\text{final_score} = 0.50V';
    const partialOutput = renderMarkdown(streamChunk);
    const partialSafe = !partialOutput.includes('undefined') && !partialOutput.includes('NaN');

    // 2. Completed chunk
    const completeChunk = 'Calculating score:\n\\[\\text{final_score} = 0.50V + 0.30K\\]';
    const completeOutput = renderMarkdown(completeChunk);
    const completeKaTeX = completeOutput.includes('katex-display');

    console.log(JSON.stringify({ success: partialSafe && completeKaTeX }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_citation_markers_adjacent_to_equations_do_not_break():
    """
    Formula Test 7: Citation markers adjacent to equations do not break equation rendering.
    """
    js = r"""
    const input = '\\[ a^2 + b^2 = c^2 \\] [1]\n\nWhere \\(E = mc^2\\) [Source 2] holds true.';
    const output = renderMarkdown(input, [{ source_index: 1 }, { source_index: 2 }]);
    const hasMath = output.includes('katex-display') && output.includes('math-inline');
    const hasCitation1 = output.includes('data-source-index="1"');
    const hasCitation2 = output.includes('data-source-index="2"');
    console.log(JSON.stringify({ success: hasMath && hasCitation1 && hasCitation2, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_general_math_formulas_render_without_repo_prompts():
    """
    Formula Test 8: General mathematical formulas render cleanly without requiring repository prompts.
    """
    js = r"""
    const input = 'The Pythagorean theorem states:\n\\[ a^2 + b^2 = c^2 \\]\nAnd mass-energy equivalence is \\(E = mc^2\\).';
    const output = renderMarkdown(input);
    const hasDisplay = output.includes('katex-display');
    const hasInline = output.includes('math-inline');
    console.log(JSON.stringify({ success: hasDisplay && hasInline, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_malformed_math_does_not_crash_or_hide_response():
    """
    Formula Test 9: Malformed math does not crash or hide the rest of the response.
    """
    js = r"""
    const input = 'Start prose.\n\\[ \\frac{1}{ \\]\nRemaining prose continues uninterrupted.';
    const output = renderMarkdown(input);
    const hasStart = output.includes('Start prose.');
    const hasEnd = output.includes('Remaining prose continues uninterrupted.');
    console.log(JSON.stringify({ success: hasStart && hasEnd, output }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


# ==============================================================================
# Part 4: Phase 2 Comprehensive Regression Scenarios
# ==============================================================================

@pytest.mark.anyio
async def test_multiturn_pythagorean_then_multipart_educational_question(db_session: Session):
    """
    Scenario 1: A Pythagorean theorem question followed by a new question requesting
    Einstein's equation, a fraction, the sum of squares, and a binomial expansion.
    The second response must answer all four requested items without irrelevant repetition
    of the first response.
    """
    repo = create_test_codemind_repo(db_session)

    conv = AssistantConversation(repository_id=repo.id, branch="main", title="Math Continuity Test")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    # Turn 1: Pythagorean Theorem
    res1 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the Pythagorean theorem.",
        conversation_id=conv.id,
    )
    ans1 = res1["answer"]
    assert "pythagorean" in ans1.lower()
    assert ("\\[" in ans1 or "\\(" in ans1) and ("a^2 + b^2" in ans1 or "c^2" in ans1)

    # Turn 2: Multi-part request (Einstein, fraction, sum of squares, binomial expansion)
    res2 = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Now explain Einstein's equation, a fraction, a sum of squares, and a binomial expansion.",
        conversation_id=conv.id,
    )
    ans2 = res2["answer"]

    # Must cover ALL four requested items
    assert "einstein" in ans2.lower() or "mc^2" in ans2.lower()
    assert "fraction" in ans2.lower()
    assert "sum of squares" in ans2.lower() or "a^2 + b^2" in ans2
    assert "binomial" in ans2.lower()

    # Must NOT lead with or repeat the Pythagorean theorem from Turn 1
    assert not ans2.strip().lower().startswith("the pythagorean theorem")
    assert not ans2.strip().lower().startswith("### 1. pythagorean theorem")
    lines = [line.strip().lower() for line in ans2.splitlines() if line.strip()]
    first_heading = next((l for l in lines if l.startswith("#")), "")
    assert "pythagorean" not in first_heading

    # Must have proper math formatting and no repo citations
    assert "\\[" in ans2 or "\\(" in ans2
    assert res2["citations"] == []


@pytest.mark.anyio
async def test_standalone_quadratic_formula_educational_routing(db_session: Session):
    """
    Scenario 2: A standalone quadratic-formula question must receive an educational answer
    without repository-absence disclaimers.
    """
    repo = create_test_codemind_repo(db_session)

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question="Explain the quadratic formula.",
    )

    ans = res["answer"]
    assert "quadratic formula" in ans.lower()
    assert "\\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}" in ans or "-b" in ans
    assert "\\[" in ans and "\\]" in ans

    # Must NOT contain repository absence disclaimers
    assert "no relevant source code" not in ans.lower()
    assert "unverified" not in ans.lower()
    assert "not found in the indexed source" not in ans.lower()
    assert res["citations"] == []


def test_intent_classification_routing_safeguards():
    """
    Scenario 3: Intent classification correctly separates GENERAL_EDUCATIONAL,
    GENERAL_PROGRAMMING, and repository-specific inquiries.
    """
    # 1. General Educational (math/science)
    assert AssistantService.classify_query_intent("Explain the Pythagorean theorem.") == ["GENERAL_EDUCATIONAL"]
    assert AssistantService.classify_query_intent("Explain Einstein's equation.") == ["GENERAL_EDUCATIONAL"]
    assert AssistantService.classify_query_intent("Explain fractions and the sum of squares.") == ["GENERAL_EDUCATIONAL"]
    assert AssistantService.classify_query_intent("Expand (a + b)^2.") == ["GENERAL_EDUCATIONAL"]
    assert AssistantService.classify_query_intent("Explain the quadratic formula.") == ["GENERAL_EDUCATIONAL"]

    # 2. General Programming (CS/language)
    assert AssistantService.classify_query_intent("What is the difference between a Python list and tuple?") == ["GENERAL_PROGRAMMING"]
    assert AssistantService.classify_query_intent("Explain Python list comprehensions with a simple example.") == ["GENERAL_PROGRAMMING"]
    assert AssistantService.classify_query_intent("What is a Python dictionary?") == ["GENERAL_PROGRAMMING"]

    # 3. Repository-specific questions
    repo_vec = AssistantService.classify_query_intent("Where does this repository calculate vector similarity?")
    assert "GENERAL_EDUCATIONAL" not in repo_vec
    assert "GENERAL_PROGRAMMING" not in repo_vec

    repo_scores = AssistantService.classify_query_intent("How are vector and keyword scores combined?")
    assert "INDEXING_AND_EMBEDDINGS" in repo_scores
    assert "GENERAL_EDUCATIONAL" not in repo_scores

    repo_file = AssistantService.classify_query_intent("Which file implements hybrid retrieval in this repository?")
    assert "INDEXING_AND_EMBEDDINGS" in repo_file
    assert "GENERAL_EDUCATIONAL" not in repo_file


def test_frontend_streaming_incomplete_inline_delimiter_across_chunks():
    """
    Scenario 5: Streaming responses that split an inline math delimiter \\( ... \\) across chunks
    do not leak broken expressions or malformed HTML during streaming.
    """
    js = r"""
    // 1. Partial chunk during streaming with unclosed inline delimiter
    const partialChunk = 'Energy is defined as \\(E = mc^2';
    const partialOutput = renderMarkdown(partialChunk);
    const partialSafe = !partialOutput.includes('undefined') && !partialOutput.includes('NaN');

    // 2. Trailing unclosed delimiter without body
    const trailingChunk = 'Energy is defined as \\(';
    const trailingOutput = renderMarkdown(trailingChunk);
    const trailingSafe = !trailingOutput.includes('\\(');

    // 3. Completed chunk
    const completeChunk = 'Energy is defined as \\(E = mc^2\\) in relativity.';
    const completeOutput = renderMarkdown(completeChunk);
    const completeKaTeX = completeOutput.includes('math-inline') && completeOutput.includes('katex');

    console.log(JSON.stringify({ success: partialSafe && trailingSafe && completeKaTeX, partialOutput, completeOutput }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_streaming_incomplete_double_dollar_delimiter_across_chunks():
    """
    Scenario 6: Streaming responses with $$ ... $$ display math preserve safety during streaming.
    """
    js = r"""
    // 1. Partial chunk during streaming with unclosed $$
    const partialChunk = 'Equation:\n$$a^2 + b^2';
    const partialOutput = renderMarkdown(partialChunk);
    const partialSafe = !partialOutput.includes('undefined') && !partialOutput.includes('NaN');

    // 2. Completed chunk
    const completeChunk = 'Equation:\n$$a^2 + b^2 = c^2$$';
    const completeOutput = renderMarkdown(completeChunk);
    const completeKaTeX = completeOutput.includes('katex-display');

    console.log(JSON.stringify({ success: partialSafe && completeKaTeX }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


def test_frontend_multiple_equations_and_fractions():
    """
    Scenario 7: Multiple equations with fractions, square roots, and superscripts in a single response
    render cleanly through KaTeX.
    """
    js = r"""
    const input = [
        '### 1. Quadratic Formula',
        '\\[ x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a} \\]',
        '### 2. Binomial Expansion',
        '\\[ (a + b)^2 = a^2 + 2ab + b^2 \\]',
        '### 3. Fraction and Inline',
        'Where \\(\\frac{1}{2}\\) is half and \\(E = mc^2\\).'
    ].join('\n\n');

    const output = renderMarkdown(input);
    const displayCount = (output.match(/class="math-display"/g) || []).length;
    const inlineCount = (output.match(/class="math-inline"/g) || []).length;
    const hasKaTeX = output.includes('katex-display') && output.includes('katex');

    console.log(JSON.stringify({ success: displayCount === 2 && inlineCount >= 2 && hasKaTeX }));
    """
    res = run_js_markdown_test(js)
    assert res["success"] is True


# ==============================================================================
# Phase 4 Regression Tests: Grounding, Retrieval Accuracy, and Intent Safeguards
# ==============================================================================

@pytest.mark.anyio
async def test_phase4_hybrid_retrieval_formula_factual_accuracy_and_weights_grounding(db_session: Session):
    """
    Phase 4 - Issue 1:
    Query: 'How is the final hybrid retrieval score calculated? Explain every weight and cite both the runtime formula and configuration.'
    Verifies that:
    1. Linear weighted rank fusion formula is rendered using LaTeX display math.
    2. Vector (0.50), keyword (0.30), and exact-match (0.20) weights are cited from backend/app/core/config.py (lines 83-85).
    3. Graph weight (0.15) is documented as HARDCODED in hybrid_engine.py (line 234) and NOT defined in config.py (no RETRIEVAL_GRAPH_WEIGHT).
    4. Weights sum to 1.15 and are NOT claimed to be normalized to 1.0.
    5. Scoring channels are described independently (vector cosine distance/similarity, keyword SQL token hit ratio, exact 1.0/0.85, graph 0.65); cosine similarity is NOT applied across keyword, exact, or graph scores.
    6. Runtime fusion (hybrid_engine.py:230-268) and configuration weights (config.py:83-85) are cited separately.
    """
    repo = create_test_codemind_repo(db_session)
    q = "How is the final hybrid retrieval score calculated? Explain every weight and cite both the runtime formula and configuration."

    res = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q,
    )

    ans = res["answer"]
    citations = res["citations"]
    cit_files = [c["file_path"] for c in citations]

    # Must cite both runtime engine and configuration files separately
    assert any("hybrid_engine.py" in f for f in cit_files)
    assert any("config.py" in f for f in cit_files)

    # Runtime fusion citation covers lines 230-268
    fusion_cit = next(c for c in citations if "hybrid_engine.py" in c["file_path"])
    assert fusion_cit["start_line"] <= 235 and fusion_cit["end_line"] >= 265

    # Configuration citation covers lines 80-86
    config_cit = next(c for c in citations if "config.py" in c["file_path"])
    assert config_cit["start_line"] <= 85 and config_cit["end_line"] >= 83

    # Formula display math
    assert "\\[" in ans and "\\]" in ans
    assert "final_score" in ans or r"\text{final\_score}" in ans

    # Weights
    assert "0.50" in ans or "0.5" in ans
    assert "0.30" in ans or "0.3" in ans
    assert "0.20" in ans or "0.2" in ans
    assert "0.15" in ans

    # Graph weight must be explicitly identified as hardcoded in hybrid_engine.py, not in config.py
    ans_lower = ans.lower()
    assert "hardcoded" in ans_lower or "line 234" in ans_lower or "w_graph = 0.15" in ans
    assert "retrieval_graph_weight" not in ans

    # Weights sum to 1.15 and are not normalized to 1.0
    assert "1.15" in ans
    assert "not normalized" in ans_lower or "not normalized to 1.0" in ans_lower

    # Independent channel scoring
    assert "pgvector" in ans_lower or "cosine_distance" in ans_lower or "dot product" in ans_lower
    assert "ilike" in ans_lower or "token hit ratio" in ans_lower or "substring" in ans_lower


@pytest.mark.anyio
async def test_phase4_keyword_matching_function_logic_and_paraphrases(db_session: Session):
    """
    Phase 4 - Issue 2:
    Tests the exact query and two distinct paraphrases for keyword matching logic:
    1. 'Which function performs keyword matching? Explain its actual matching logic and distinguish it from vector similarity.'
    2. 'How does keyword matching work in this codebase, and how is it different from vector search?'
    3. 'Where is the keyword retrieval logic defined, and what matching operations does it execute compared to vector similarity?'

    Verifies that:
    1. Cites HybridRetrievalEngine._retrieve_keyword_matches in backend/app/retrieval/hybrid_engine.py (Lines 476-549).
    2. Explains token extraction (>=3 chars, stopwords, repo tokens) and SQL CodeChunk.chunk_text.ilike(...) matching.
    3. Explains token hit ratio scoring.
    4. Refutes / does not hallucinate KeywordMatcher, keyword_matching.py, Jaccard, Levenshtein, or fuzzywuzzy.
    5. Distinguishes from vector similarity (dense embeddings, pgvector cosine distance, fallback dot product/norms).
    """
    repo = create_test_codemind_repo(db_session)

    queries = [
        "Which function performs keyword matching? Explain its actual matching logic and distinguish it from vector similarity.",
        "How does keyword matching work in this codebase, and how is it different from vector search?",
        "Where is the keyword retrieval logic defined, and what matching operations does it execute compared to vector similarity?",
    ]

    for q in queries:
        # Intent classification must recognize retrieval / search, NOT general programming
        intents = AssistantService.classify_query_intent(q)
        assert "INDEXING_AND_EMBEDDINGS" in intents
        assert "GENERAL_PROGRAMMING" not in intents
        assert "GENERAL_EDUCATIONAL" not in intents

        res = await AssistantService.answer_question(
            db=db_session,
            repository_id=repo.id,
            question=q,
        )

        ans = res["answer"]
        citations = res["citations"]

        # Must cite hybrid_engine.py
        assert any("hybrid_engine.py" in c["file_path"] for c in citations)
        top_cit = citations[0]
        assert "_retrieve_keyword_matches" in (top_cit.get("symbol_name") or "")

        # Must mention the actual function and file
        assert "_retrieve_keyword_matches" in ans
        assert "hybrid_engine.py" in ans

        # Must explain SQL ilike matching and token hit ratio
        ans_lower = ans.lower()
        assert "ilike" in ans_lower or "substring" in ans_lower
        assert "hit" in ans_lower or "token" in ans_lower or "words" in ans_lower

        # Must NOT hallucinate unsupported classes or files
        assert "KeywordMatcher" not in ans
        assert "keyword_matching.py" not in ans
        assert "fuzzywuzzy" not in ans.lower()
        assert "levenshtein" not in ans.lower()
        assert "jaccard" not in ans.lower()

        # Must distinguish from vector similarity
        assert "vector" in ans_lower
        assert any(k in ans_lower for k in ["cosine", "embedding", "dense", "pgvector"])


@pytest.mark.anyio
async def test_phase4_unspecified_feature_clarification_vs_named_feature_audits(db_session: Session):
    """
    Phase 4 - Issue 3:
    Verifies that:
    1. Vague feature questions without a named feature ('Is a particular feature implemented in this repository? ...')
       ask a concise clarification question and make NO presence or absence claims.
    2. Named implemented feature ('Is hybrid retrieval implemented in this repository? ...')
       correctly returns IMPLEMENTED and cites source files.
    3. Named feature not present in repo ('Is email notifications implemented in this repository? ...')
       correctly returns NOT_FOUND_IN_INDEXED_SOURCE or negative finding.
    4. Repo with insufficient coverage returns UNVERIFIED.
    """
    repo = create_test_codemind_repo(db_session)

    # 1. Unspecified feature query: must ask clarification, not claim absence or presence
    q_vague = "Is a particular feature implemented in this repository? Search the relevant source files before deciding. If evidence is insufficient, state that clearly."
    res_vague = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q_vague,
    )
    ans_vague = res_vague["answer"]
    assert "Which feature do you want me to check?" in ans_vague
    assert "Please specify the feature" in ans_vague
    # Must NOT claim IMPLEMENTED, NOT_FOUND_IN_INDEXED_SOURCE, or UNVERIFIED/ABSENT
    assert "NOT_FOUND_IN_INDEXED_SOURCE" not in ans_vague
    assert "UNVERIFIED" not in ans_vague
    assert "IMPLEMENTED" not in ans_vague
    assert res_vague["citations"] == []
    assert res_vague["retrieval_strategy"] == "clarification"

    # Streaming path for unspecified feature query
    events = []
    async for chunk in AssistantService.stream_answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q_vague,
    ):
        events.append(chunk)

    done_event = next(e for e in events if "event: done" in e)
    done_payload = json.loads(done_event.split("data: ")[1].split("\n")[0])
    assert "Which feature do you want me to check?" in done_payload["answer"]
    assert "NOT_FOUND_IN_INDEXED_SOURCE" not in done_payload["answer"]
    assert "IMPLEMENTED" not in done_payload["answer"]

    # 2. Named implemented feature: hybrid retrieval
    q_impl = "Is hybrid retrieval implemented in this repository? Search the relevant source files before deciding. If evidence is insufficient, state that clearly."
    res_impl = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q_impl,
    )
    assert "implemented" in res_impl["answer"].lower()
    assert any("hybrid_engine.py" in c["file_path"] for c in res_impl["citations"])

    # 3. Named non-existent feature: email notifications
    q_missing = "Is email notifications implemented in this repository? Search the relevant source files before deciding. If evidence is insufficient, state that clearly."
    res_missing = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo.id,
        question=q_missing,
    )
    ans_missing_lower = res_missing["answer"].lower()
    assert any(k in ans_missing_lower for k in ["not found", "unverified", "not implemented", "does not implement", "absent"])
    assert "smtp" not in res_missing["answer"] or "not implemented" in ans_missing_lower

    # 4. Repo with insufficient coverage / indexing in progress
    repo_indexing = Repository(
        name="IndexingRepo",
        full_name="org/indexing-repo",
        description="Repo being indexed",
        status="indexing",
        files_count=100,
    )
    db_session.add(repo_indexing)
    db_session.commit()
    db_session.refresh(repo_indexing)

    res_unverified = await AssistantService.answer_question(
        db=db_session,
        repository_id=repo_indexing.id,
        question="Is hybrid retrieval implemented in this repository? Search the relevant source files before deciding.",
    )
    assert "UNVERIFIED" in res_unverified["answer"] or "indexing" in res_unverified["answer"].lower()
