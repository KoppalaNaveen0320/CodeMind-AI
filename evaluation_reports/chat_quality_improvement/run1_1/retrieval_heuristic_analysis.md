# CodeMind AI — Run 1 Retrieval Heuristics Critical Analysis

**Evaluation Phase**: Run 1.1 — Retrieval Stabilization & Precision Improvement  
**Target File**: `backend/app/retrieval/hybrid_engine.py`  
**Focus**: Critical inspection of heuristics introduced during Run 1, risks of benchmark overfitting, negative transfer, and architectural side-effects.

---

## 1. Executive Overview

In Run 1, seven specific heuristics were implemented in `HybridRetrievalEngine` to rapidly improve target recall and file discovery on 20 benchmark questions across `expertdecision` (Repo 46) and `RewardPoints Transfer` (Repo 47). 

While these changes increased relevant source coverage from 38.89% to 44.44%, static inspection and empirical profiling reveal that several heuristics are:
1. **Heavily overfitted** to standard 2-tier Python/FastAPI + React project directory layouts.
2. **Fragile and brittle** when applied to polyglot, monorepo, or differently structured codebases (such as Go microservices, CLI tools, or Java enterprise systems).
3. **Harmful to general precision and recall balance**, resulting in unintended double-penalties and rank inversions.

---

## 2. In-Depth Analysis of Individual Heuristics

### Heuristic 1: Entrypoint Hardcoded Path Injection & Score Boost (+0.45)

**Implementation (`hybrid_engine.py:88-90, 379-380`)**:
```python
# In _extract_file_path_candidates:
if re.search(r'\b(entrypoint|entry\s*point|application\s*entrypoint|fastapi\s*(?:app|application)\s*(?:is\s*)?initialized|where\s+routers\s+are\s+included)\b', query, re.IGNORECASE):
    candidates.update(["backend/app/main.py", "app/main.py", "main.py", "frontend/src/main.tsx", "src/main.tsx", "main.tsx", "App.tsx", "src/App.tsx"])

# In retrieve scoring:
if is_entrypoint_query and any(ep in p_lower for ep in ["main.py", "main.tsx", "app.py", "app.tsx"]):
    final_score += 0.45
```

**Critical Flaws & Overfitting Risks**:
1. **Assumption of Conventional Framework Paths**:
   Hardcoding `backend/app/main.py` and `frontend/src/main.tsx` succeeds for `expertdecision` and `RewardPoints Transfer`, but fails completely for:
   - Go repositories (e.g. `cmd/server/main.go`, `cmd/cli/main.go`).
   - Rust projects (`src/main.rs`, `src/lib.rs`).
   - Java / Spring Boot applications (`src/main/java/com/app/Application.java`).
   - Repositories where the backend is in `server/index.ts` or `src/server.py`.
2. **Artificial Candidate Hallucination**:
   Injecting 8 candidate paths into `explicit_file_candidates` queries `IndexedFile` for non-existent files. If a repository has a file named `src/App.tsx` that is a UI component, an entrypoint query about backend initialization erroneously matches and boosts the React UI entrypoint.
3. **Disproportionate Score Boost (+0.45)**:
   On a normalized [0.0, 1.0] scale, a +0.45 boost guarantees that any file matching `main.py` or `main.tsx` jumps to the absolute top of the results, even if the user asked a nuanced question (e.g., "Where are Celery worker tasks initialized?").

**Universal Remediation**:
Replace hardcoded path string injection with a database-backed entrypoint detector that queries indexed files for standard language-agnostic root files (`main.*`, `app.*`, `index.*`, `server.*`, `application.*`, `manage.py`, `wsgi.py`) matching the repository's detected primary languages, and apply a moderate, normalized boost (+0.20) rather than +0.45.

---

### Heuristic 2: Compounded Test File Penalties (0.20 * 0.20 = 0.04)

**Implementation (`hybrid_engine.py:353-354, 370-372`)**:
```python
# First occurrence (line 353-354):
if is_code_query:
    if is_test_or_upload and not is_test_query:
        final_score *= 0.20

# Second occurrence (line 370-372):
# Universal test file penalty: unless the question explicitly asks about tests, down-weight test files
if is_test_or_upload and not is_test_query:
    final_score *= 0.20
```

**Critical Flaws & Overfitting Risks**:
1. **Accidental Compounded Down-Weighting**:
   Because `is_code_query` is true for virtually all queries, both conditional blocks execute in sequence. The test chunk score is multiplied by `0.20 * 0.20 = 0.04` — a **96% penalty**.
2. **Suppression of Essential Implementation Evidence**:
   In code intelligence, test files are often the *most accurate* documentation of:
   - Expected error conditions and status codes (e.g., "What happens if a user submits negative transfer points?").
   - Service invocation patterns and parameter signatures.
   - Database schema fixtures and constraint validations.
   A 96% penalty completely eliminates tests from the context, preventing CodeMind from providing verifiable citations for questions regarding edge cases and validation rules.

**Universal Remediation**:
Remove the duplicate penalty block. Consolidate into a single, moderate, intent-aware penalty (`* 0.60`) when the query does not ask about tests, and provide a positive boost (`+0.25`) when the query explicitly inquires about tests, fixtures, or mocks.

---

### Heuristic 3: Compounded Documentation Penalties (0.25 * 0.20 = 0.05)

**Implementation (`hybrid_engine.py:364-365, 374-376`)**:
```python
# First occurrence (line 364-365):
elif is_doc:
    final_score *= 0.25

# Second occurrence (line 374-376):
# Universal doc file penalty: down-weight documentation/markdown for implementation inquiries
if is_doc and not is_doc_query:
    final_score *= 0.20
```

**Critical Flaws & Overfitting Risks**:
1. **Accidental Compounded Down-Weighting**:
   Similar to the test penalty, markdown and documentation files are multiplied by `0.25 * 0.20 = 0.05` — a **95% penalty**.
2. **Suppression of Architectural Overviews**:
   Queries like "Describe the high-level architecture of this system" or "How is the token marketplace structured?" benefit significantly from `README.md`, `ARCHITECTURE.md`, and design specifications. A 95% penalty guarantees that no documentation chunk can ever enter the top 8 context chunks if any code file matched a single keyword.

**Universal Remediation**:
Eliminate the duplicate penalty. Apply a single intent-aware factor: `* 0.70` when the query seeks concrete code implementation, but `+0.30` when the query is high-level, conceptual, or asks about system architecture, PRDs, or setups.

---

### Heuristic 4: Directional Layer Scoring (+0.35 / * 0.40)

**Implementation (`hybrid_engine.py:387-396`)**:
```python
if is_frontend_target and not is_backend_target:
    if p_lower.startswith(("frontend/", "src/")) or "/frontend/" in p_lower:
        final_score += 0.35
    elif p_lower.startswith(("backend/", "app/")) or "/backend/" in p_lower:
        final_score *= 0.40
elif is_backend_target and not is_frontend_target:
    if p_lower.startswith(("backend/", "app/")) or "/backend/" in p_lower:
        final_score += 0.25
    elif p_lower.startswith(("frontend/", "src/")) or "/frontend/" in p_lower:
        final_score *= 0.40
```

**Critical Flaws & Overfitting Risks**:
1. **False Dichotomy of Frontend vs. Backend**:
   Software features often span both layers. For instance, an authentication question ("How does login work?") involves `frontend/src/pages/LoginPage.tsx` AND `backend/app/routers/auth.py`. Classifying this query as purely frontend or purely backend suppresses half of the execution chain by 60% (`* 0.40`).
2. **Hardcoded Directory Assumption**:
   The logic checks `startswith(("frontend/", "src/"))` and `startswith(("backend/", "app/"))`. Many architectures do not use these directory names:
   - Monorepos with `packages/client`, `packages/server`, `services/api`, `services/web`.
   - Single-language backend repos (such as `TokenPool`, Repo 45) where `backend/app` exists but no frontend exists, meaning a frontend-related query term will heavily penalize valid backend code.
   - Mobile projects (`android/`, `ios/`, `lib/`).

**Universal Remediation**:
Use layer classification as a mild soft re-ranking signal (+0.10) rather than a destructive 60% penalty (* 0.40). Allow vector and symbol similarity to govern chunk relevance without artificially suppressing opposing layer evidence.

---

### Heuristic 5: Fullstack Round-Robin Interleaving

**Implementation (`hybrid_engine.py:406-417`)**:
```python
if is_fullstack_flow:
    fe_cands = [c for c in scored_results if c.file_path.lower().startswith(("frontend/", "src/")) or "/frontend/" in c.file_path.lower()]
    be_cands = [c for c in scored_results if c.file_path.lower().startswith(("backend/", "app/")) or "/backend/" in c.file_path.lower()]
    other_cands = [c for c in scored_results if c not in fe_cands and c not in be_cands]
    interleaved = []
    for i in range(max(len(fe_cands), len(be_cands))):
        if i < len(fe_cands):
            interleaved.append(fe_cands[i])
        if i < len(be_cands):
            interleaved.append(be_cands[i])
    interleaved.extend(other_cands)
    scored_results = interleaved
```

**Critical Flaws & Overfitting Risks**:
1. **Score Rank Inversion**:
   Round-robin interleaving forces alternation regardless of confidence scores. If backend has 4 perfect chunks with score `1.0` and frontend has only 1 weak chunk with score `0.25`, the interleaving places the 0.25 frontend chunk at index 1, displacing a 1.0 backend chunk.
2. **Failure When One Layer Dominates**:
   If a user asks "Trace how a user submits a transfer from the UI down to the database ledger", and 80% of the complexity is in backend transaction serialization, the engine forces 50% frontend chunks, pushing critical SQL/ledger models out of the retrieval window.

**Universal Remediation**:
Maintain strict fused-score ordering. Guarantee diversity by reserving at most 1 slot for an under-represented layer if and only if that layer's top chunk exceeds a minimum confidence threshold (> 0.50).

---

### Heuristic 6: Broad Directory Stem Exclusions (`DIR_STEM_EXCLUSIONS`)

**Implementation (`hybrid_engine.py:485-489`)**:
```python
DIR_STEM_EXCLUSIONS = {"backend", "frontend", "src", "app", "apps", "lib", "packages", "upload", "uploads"}
clean_words = re.findall(r"[a-zA-Z0-9_]+", query.lower())
meaningful_stems = [
    w for w in set(clean_words)
    if len(w) >= 4 and w not in excluded_words and w not in DIR_STEM_EXCLUSIONS
]
```

**Critical Flaws & Overfitting Risks**:
1. **Brittle Stopword List**:
   While excluding "app" or "src" prevents `IndexedFile.path.ilike("%app%")` from matching all files in `backend/app`, hardcoding generic folder names fails if a repository has a domain concept matching that stem (e.g., an application managing "packages" or an image processing service with "upload" models).
2. **Remediation**:
   Rather than excluding words from search entirely, require file-path substring matches to have higher specificity (e.g. matching path segments `f"/{w}/"` or `f"/{w}."` or requiring file extensions) rather than doing broad `%word%` wildcard matching.

---

### Heuristic 7: Identifier Text ILIKE Full-Table Scans

**Implementation (`hybrid_engine.py:550-553`)**:
```python
ident_chunks = (
    db.query(CodeChunk.id)
    .filter(
        CodeChunk.repository_id == repo_id,
        or_(
            CodeChunk.code_symbol.in_(code_identifiers),
            *[CodeChunk.chunk_text.ilike(f"%{ci}%") for ci in list(code_identifiers)[:6]]
        )
    )
    .limit(15)
    .all()
)
```

**Critical Flaws & Latency Regression**:
1. **Severe Latency Regression (+180 ms to +3,600 ms)**:
   As proven in Section 4 of the Metric Verification Report, searching `CodeChunk.chunk_text.ilike(...)` across 6 identifiers forces PostgreSQL into unindexed sequential table scans of multi-megabyte text fields on every query.
2. **False Positive Pollution**:
   Matching identifiers inside arbitrary chunk text catches comments, debug logs, import statements, and incidental mentions, pulling irrelevant chunks into exact candidates and diluting precision.

**Universal Remediation**:
Eliminate `chunk_text.ilike` from `_retrieve_exact_matches`. Limit exact identifier lookups strictly to indexed fields: `CodeChunk.code_symbol.in_(code_identifiers)` and `CodeSymbol.name.in_(code_identifiers)`.

---

## 3. Heuristic Overfitting Summary Matrix

| Heuristic | Benchmark Question Target | Overfitting Severity | Negative Transfer Risk | Production Remediation |
|---|---|---|---|---|
| **Entrypoint Path List** | ED-01, RP-01 | **High** | Fails on Go, Rust, Java, CLI tools | Query indexed files for repo-specific entrypoints; boost +0.20 |
| **Double Test Penalty** | ED-08, RP-06 | **Severe** | 96% penalty suppresses edge-case & contract tests | Single `* 0.60` penalty; boost `+0.25` if testing intent |
| **Double Doc Penalty** | ED-12, RP-12 | **Severe** | 95% penalty suppresses system architecture specs | Single `* 0.70` penalty; boost `+0.30` if doc/architecture intent |
| **Directional Layer Scoring** | RP-04, RP-10 | **High** | 60% penalty suppresses cross-layer auth/API flows | Gentle `+0.10` soft re-ranking; no layer suppression |
| **Fullstack Interleaving** | RP-04 | **High** | Rank inversion (displaces 1.0 score chunks with 0.2 score chunks) | Strict score ordering with minimum confidence floor |
| **Dir Stem Exclusions** | General queries | **Medium** | Collateral exclusion of domain models named 'upload' or 'package' | Enforce slash-bounded path segment matching |
| **Identifier ILIKE Scan** | ED-04, ED-06 | **Severe** | Full table scans cause +180ms latency regression | Restrict to indexed `code_symbol` and `CodeSymbol` tables |

---

## 4. Conclusion & Next Steps

All 7 heuristics implemented in Run 1 require refactoring to transition CodeMind AI from an overfitted benchmark patch into a robust, universal, repository-independent code intelligence engine.

In Phase C (Precision & Recall Stabilization), these heuristics will be replaced with:
1. **Concept-Level Stem Aliasing**: Language-agnostic code concept mapping (`authentication` $\rightarrow$ `auth`, `config` $\rightarrow$ `config/settings`, etc.).
2. **Adaptive Score Thresholding**: Dynamic pruning of low-scoring tail distractors to directly boost precision from 40.12% to > 48%.
3. **Indexed Symbol Search**: Sub-5ms indexed lookups eliminating the 180ms table scan latency penalty.
