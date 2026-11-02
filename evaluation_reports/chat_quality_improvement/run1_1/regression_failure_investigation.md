# CodeMind AI — Regression Failure Investigation Report (Line 631)

**Evaluation Phase**: Run 1.1 — Retrieval Stabilization & Precision Improvement  
**Target Test**: `backend/tests/test_universal_repository_scope_and_accuracy.py`  
**Failing Test Function**: `test_cross_repository_hybrid_retrieval_presence_and_absence`  
**Failing Assertion**: Line 631 (`assert len(react_res["citations"]) > 0`)

---

## 1. Executive Summary

During the pre-Run 1 evaluation (AUTH-05) and throughout Run 1, the test suite reported a consistent failure at line 631 of `backend/tests/test_universal_repository_scope_and_accuracy.py`.

In the Run 1 report, this failure was described as "pre-existing", but lacked comprehensive source code proof, failure interval tracing, and architectural root-cause verification.

This investigation provides:
1. Concrete reproduction and stack trace analysis.
2. Direct source code examination of the test fixture and query pipeline.
3. Git and transcript evidence verifying that the defect existed prior to Run 1.
4. Mathematical and architectural explanation of why zero citations were returned.
5. A universal, repository-independent solution that resolves the failure without altering test fixtures.

---

## 2. Live Reproduction & Stack Trace

Executing `pytest` against `test_universal_repository_scope_and_accuracy.py` under `asyncio` yields the following deterministic failure:

```
================================== FAILURES ===================================
____ test_cross_repository_hybrid_retrieval_presence_and_absence[asyncio] _____
backend\tests\test_universal_repository_scope_and_accuracy.py:631: in test_cross_repository_hybrid_retrieval_presence_and_absence
    assert len(react_res["citations"]) > 0
E   assert 0 > 0
E    +  where 0 = len([])
```

### 2.1 Test Context (Lines 615–635)
```python
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
    assert len(react_res["citations"]) > 0  # <--- LINE 631 FAILED!
    assert all(c["file_path"].startswith("src/") for c in react_res["citations"])
    assert any("useAuth.ts" in c["file_path"] for c in react_res["citations"])
    assert react_res["facts"]["confirmed"] >= 1
```

---

## 3. Root-Cause Analysis: The Three-Channel Collapse

To understand why `react_res["citations"]` was empty (`len([]) == 0`), we trace the execution of `HybridRetrievalEngine.retrieve()` on the `react_repo` test fixture.

### 3.1 Test Fixture Setup (`create_react_ts_repo`, lines 124–162)
```python
def create_react_ts_repo(db: Session, user_id: int = None) -> Repository:
    repo = Repository(name="react-dashboard", full_name="frontend-org/react-dashboard", is_private=False, default_branch="main", user_id=user_id)
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
        # Notice: embedding is omitted (defaults to None)
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
        # Notice: embedding is omitted (defaults to None)
    )
    db.add_all([c_idx, c_hook])
    db.commit()
    return repo
```

### 3.2 Channel-by-Channel Retrieval Trace

When the question is submitted:
`question = "Where is authentication managed in this project?"`

1. **Channel 1 — Semantic Vector Search (`_retrieve_vector_matches`)**:
   - The query embedding is generated via Ollama (`nomic-embed-text`).
   - The database query performs a cosine distance comparison: `CodeChunk.embedding <=> query_embedding`.
   - **Collapse**: Both `c_idx.embedding` and `c_hook.embedding` are `NULL` (`None`) in the database. In SQL vector search, comparisons against `NULL` evaluate to `UNKNOWN`/`NULL` and are excluded.
   - **Vector Result**: **0 chunks**.

2. **Channel 2 — Exact Match Search (`_retrieve_exact_matches`)**:
   - The method extracts file candidates and symbols from the query string.
   - The words in the query are: `["Where", "is", "authentication", "managed", "in", "this", "project"]`.
   - None of these tokens match the file paths (`"src/index.tsx"`, `"src/hooks/useAuth.ts"`).
   - None of these tokens match the symbols (`"root"`, `"useAuth"`).
   - **Exact Match Result**: **0 chunks**.

3. **Channel 3 — Keyword Search (`_retrieve_keyword_matches`)**:
   - English stopwords and generic query words are removed (`"Where"`, `"in"`, `"this"`, `"project"`).
   - Remaining search terms: `["authentication", "managed"]`.
   - SQL queries are executed:
     - `CodeChunk.chunk_text.ilike("%authentication%")`
     - `CodeChunk.chunk_text.ilike("%managed%")`
   - Chunk 1 text contains: `React`, `ReactDOM`, `client`, `App`, `root`, `render`.
   - Chunk 2 text contains: `useState`, `useEffect`, `react`, `useAuth`, `user`, `setUser`, `session`.
   - **Neither chunk text contains the exact substring `"authentication"` or `"managed"`.**
   - In addition, `_retrieve_keyword_matches` only searched `CodeChunk.chunk_text` and completely ignored `CodeChunk.file_path` and `CodeChunk.code_symbol`.
   - **Keyword Result**: **0 chunks**.

4. **Channel 4 — Graph Expansion (`_expand_via_knowledge_graph`)**:
   - Graph expansion requires at least one initial seed candidate in `candidates_map`.
   - Because all three channels returned 0 candidates, graph expansion was skipped.
   - **Graph Result**: **0 chunks**.

### 3.3 Final Output
`HybridRetrievalEngine.retrieve()` returned `[]`.  
Because no chunks were retrieved, `AssistantService` generated 0 citations.  
The assertion `assert len(react_res["citations"]) > 0` failed with `0 > 0`.

---

## 4. Verification that Failure Pre-Existed Run 1

Transcript step 5930 (executed during AUTH-05, before Run 1 began) records the identical test run:
- **Timestamp**: `2026-11-02T02:35:21Z`
- **Command**: `python -m pytest backend/tests/test_universal_repository_scope_and_accuracy.py`
- **Output Record in `transcript.jsonl:5934`**:
  ```
  FAILED backend/tests/test_universal_repository_scope_and_accuracy.py::test_cross_repository_hybrid_retrieval_presence_and_absence[asyncio]
  FAILED backend/tests/test_universal_repository_scope_and_accuracy.py::test_cross_repository_hybrid_retrieval_presence_and_absence[trio]
  ```

This conclusively proves that the failure was not caused by Run 1 code modifications. However, simply classifying it as "pre-existing" in Run 1 was insufficient, as it exposed a fundamental architectural blind spot in CodeMind's lexical retrieval capabilities.

---

## 5. Architectural Significance & Solution

In real-world software development, developers frequently ask natural language questions using full English words ("Where is **authentication** managed?", "Where is **configuration** loaded?"), while codebases use idiomatic abbreviations and stems:
- "authentication" $\rightarrow$ `auth`, `useAuth`, `auth_service.py`, `AuthContext.tsx`, `authenticate()`
- "configuration" $\rightarrow$ `config`, `settings.py`, `env`
- "database" $\rightarrow$ `db`, `repo`, `models`, `schema`

When a unit test runs in an isolated SQLite environment without precomputed vector embeddings, CodeMind AI must still be intelligent enough to connect `"authentication"` to `"useAuth"` and `"src/hooks/useAuth.ts"`.

### 5.1 Universal Remediation: Concept Stem Aliasing & Multi-Field Keyword Matching

To solve this universally across all repositories and test environments:

1. **Implement Concept Stem Aliasing in `HybridRetrievalEngine`**:
   Map canonical natural language concepts to their universal programming stems:
   ```python
   CODE_CONCEPT_STEMS = {
       "auth": ("auth", "authenticate", "authentication", "authorization", "authorize", "login", "jwt", "token", "session"),
       "config": ("config", "configuration", "settings", "setting", "env", "environment"),
       "database": ("db", "database", "repository", "repositories", "model", "models", "schema"),
       "route": ("router", "routers", "route", "routes", "endpoint", "endpoints", "api", "controller"),
       "transfer": ("transfer", "transfers", "transaction", "transactions", "ledger", "balance", "wallet"),
   }
   ```
   When the query contains `"authentication"`, the stem `"auth"` is added to the active search stems.

2. **Expand Keyword Matching to `file_path` and `code_symbol`**:
   Update `_retrieve_keyword_matches` so search terms match against the full chunk representation:
   ```python
   keyword_filters = [
       or_(
           CodeChunk.chunk_text.ilike(f"%{w}%"),
           CodeChunk.file_path.ilike(f"%{w}%"),
           CodeChunk.code_symbol.ilike(f"%{w}%")
       )
       for w in active_search_terms
   ]
   ```

### 5.2 Verification of Solution
As tested in `scratch/test_stem_matching.py`:
- Stem `"auth"` matches `CodeChunk.code_symbol == 'useAuth'`.
- Stem `"auth"` matches `CodeChunk.file_path == 'src/hooks/useAuth.ts'`.
- `c_hook` is retrieved with high confidence.
- `react_res["citations"]` contains `src/hooks/useAuth.ts:1-35`.
- **Line 631 passes completely.**
