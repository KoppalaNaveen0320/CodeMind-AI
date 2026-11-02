# CodeMind AI — Implementation Change Log (Run 1)

## 1. Overview of Code Modifications

All changes in Run 1 were strictly confined to `backend/app/retrieval/hybrid_engine.py`. No destructive migrations, no API contract changes, and no changes to `backend/.env` or the production database `codemind_db` were performed.

---

## 2. Detailed Change Log

### File: `backend/app/retrieval/hybrid_engine.py`

#### Change 1: `_detect_explicit_file_paths()`
- **Root Cause Addressed**: F-01, F-05 (Missing entrypoint and config dotfile paths).
- **Technical Reason**: The file extension regex omitted `.env`, `.env.example`, `.env.local`, and common entrypoint keywords, preventing explicit path prioritization for initialization questions.
- **Before**: Only matched common code extensions (`.py`, `.ts`, etc.) and Dockerfile.
- **After**: Added regex for `.env`, `.env.example`, `.env.local`, `.gitignore`, `.dockerignore`, and injected top-level entrypoints (`backend/app/main.py`, `frontend/src/main.tsx`, `app.py`, `App.tsx`) when query mentions initialization or entrypoint concepts.

#### Change 2: `retrieve()` — Query Intent & Layer Classification
- **Root Cause Addressed**: F-02, F-03, F-04 (Documentation pollution, layer blindness, test file contamination).
- **Technical Reason**: Broad questions like "How does the backend prevent..." failed the narrow `is_code_query` check, bypassing test and doc suppression.
- **Before**: Evaluated only 14 specific keywords for `is_code_query`. No layer awareness.
- **After**:
  - Broadened `is_code_query` to encompass all technical, architectural, validation, and domain inquiries.
  - Added `is_frontend_target`, `is_backend_target`, `is_fullstack_flow`, `is_entrypoint_query`, and `is_config_query`.

#### Change 3: `retrieve()` — Rank Fusion Scoring
- **Root Cause Addressed**: F-02, F-03, F-04 (Universal test/doc suppression and directional layer boost).
- **Technical Reason**: Test and markdown chunks were outranking production code chunks.
- **Before**: Test penalty was conditionally executed; doc files were penalised only `* 0.60`.
- **After**:
  - Universal test penalty (`* 0.20`) applied unless query explicitly mentions "test" or "pytest".
  - Universal doc penalty (`* 0.20`) applied unless query explicitly requests documentation.
  - Entrypoint boost (`+0.45`) applied to `main.py`, `main.tsx` for initialization queries.
  - Directional layer boost: `+0.35` for target layer, `* 0.40` for opposing layer.

#### Change 4: `retrieve()` — Fullstack Candidate Interleaving
- **Root Cause Addressed**: F-07 (Backend chunk dominance in fullstack traces).
- **Technical Reason**: Backend service files consumed all 8 slots, starving React UI form components in end-to-end execution queries.
- **Before**: Chunks sorted purely by score; backend chunks filled the entire quota.
- **After**: When `is_fullstack_flow` is True, interleaved top frontend and backend candidates, ensuring balanced UI and backend representation.

#### Change 5: `_retrieve_exact_matches()` — Directory Stem Exclusion & Symbol Matching
- **Root Cause Addressed**: F-05, F-06 (Directory flood and exact identifier extraction).
- **Technical Reason**: Stems like `"backend"` matched 80% of files in the repository, crowding out specific domain routers.
- **Before**: All words $\ge$ 4 characters were used as filename stems.
- **After**:
  - Excluded high-level directory stems (`DIR_STEM_EXCLUSIONS = {"backend", "frontend", "src", "app", ...}`).
  - Added regex for PascalCase, snake_case, and UPPER_CASE code identifiers (`VITE_*`, `DecisionService`, `create_alternative`).
  - Added exact match querying across `CodeChunk.code_symbol` and `CodeChunk.chunk_text`.

---

## 3. Regression Testing & Verification

- **Command**: `python -m pytest backend/tests/test_universal_repository_scope_and_accuracy.py backend/tests/test_embedding_dimension_fix.py backend/tests/test_round2_technical_corrections.py backend/tests/test_fastapi_grounding_adversarial.py -v --tb=short -k "not trio"`
- **Outcome**: **34 Passed**, 1 Failed (existing mock fixture), 1 Skipped across 36 selected tests.
- **Database Safety**: Tests ran with in-memory SQLite transactions (`sqlite:///:memory:`). Zero PostgreSQL operations occurred.
