# Approval & Execution Checklist

**Current Status:** All Phase 1–9 Static Inspection Reports Complete  
**Mode:** STRICT STOP — Zero Prohibited Actions Executed

---

## 1. Action Authorization Status Table

| Checkpoint ID | Action Description | Target Project / System | Files / Databases Accessed | Write Operations Involved | Current Authorization Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AUTH-01** | **Controlled Benchmark V2 Execution** | `CodeMind AI` | `scratch/benchmark_http_fastapi_v2.py` | Launches temporary Uvicorn subprocess on port 18768; writes `scratch/benchmark_http_fastapi_v2_results.json` | **BLOCKED — Awaiting Approval** |
| **AUTH-02** | **Isolated Evaluation Database Setup** | PostgreSQL localhost:5432 | `codemind_eval_db` (new DB) | Creates `codemind_eval_db`; copies metadata & chunks from `codemind_db` (Zero writes to `codemind_db`) | **BLOCKED — Awaiting Approval** |
| **AUTH-03** | **Index Candidate B (`RewardPoints Transfer`)** | `RewardPoints Transfer` & DB | `RewardPoints Transfer/`, `codemind_eval_db` | Inserts 1 row in `repositories`, $\sim 88$ rows in `indexed_files`, $\sim 600$ chunks into `code_chunks` | **BLOCKED — Awaiting Approval** |
| **AUTH-04** | **Execute 60-Question Blind Evaluation** | CodeMind AI Assistant | `codemind_eval_db`, `evaluation_reports/` | Normal assistant pipeline execution; writes conversation/message rows strictly into `codemind_eval_db` | **BLOCKED — Awaiting Approval** |
| **AUTH-05** | **Run Existing Regression Test Suites** | `CodeMind AI` | `backend/tests/test_*.py` | Executes pytest runner on existing regression tests; zero permanent file or database writes | **BLOCKED — Awaiting Approval** |

---

## 2. Detailed Technical Operations for Each Checkpoint

### Checkpoint AUTH-01: Controlled Benchmark Execution
- **Command:** `python scratch/benchmark_http_fastapi_v2.py`
- **What it does:** Starts an isolated Uvicorn subprocess on `127.0.0.1:18768` with ASGI timing middleware; runs 3 interleaved repetitions of 500 requests at 50 concurrency; separates server processing time (`X-Server-Time-Ms`) from client round-trip latency.
- **Side Effects:** Writes raw JSON measurements to `scratch/benchmark_http_fastapi_v2_results.json`. Terminates the subprocess upon completion.

### Checkpoint AUTH-02: Isolated Evaluation Database Setup
- **Commands:**
  1. `psql -U postgres -c "CREATE DATABASE codemind_eval_db;"`
  2. `psql -U postgres -d codemind_eval_db -c "CREATE EXTENSION IF NOT EXISTS vector;"`
  3. Selective copy of read-only tables (`repositories`, `indexed_files`, `code_chunks`, `code_symbols`, `graph_nodes`, `graph_edges`) from `codemind_db` to `codemind_eval_db`.
- **Side Effects:** Production database `codemind_db` is accessed strictly read-only. All evaluation conversation state will be isolated to `codemind_eval_db`.

### Checkpoint AUTH-03: Index Candidate B (`RewardPoints Transfer`)
- **Pipeline:** Runs standard `IndexingService.run_indexing_pipeline()` on `C:\Users\koppa\OneDrive\Documents\Projects\RewardPoints Transfer`.
- **Side Effects:** Indexes 88 clean source files (excluding `node_modules` and `venv`). Persists $\sim 600$ chunks with 768-dimensional `nomic-embed-text` embeddings into `codemind_eval_db`.

### Checkpoint AUTH-04: Execute 60-Question Blind Evaluation
- **Pipeline:** Executes the 60 questions from `blind_evaluation_methodology.md` across Repositories 46 (`expertdecision`), Candidate B (`RewardPoints Transfer`), and 45 (`TokenPool`) using `AssistantService.answer_question()` pointed to `codemind_eval_db`.
- **Side Effects:** Stores generated answers and exact citations into `evaluation_reports/blind_evaluation_results.json` and generates the final scorecard.

### Checkpoint AUTH-05: Run Existing Regression Test Suites
- **Command:** `pytest backend/tests/test_round2_technical_corrections.py backend/tests/test_fastapi_grounding_adversarial.py backend/tests/test_embedding_dimension_fix.py backend/tests/test_universal_repository_scope_and_accuracy.py`
- **Side Effects:** Verifies regression stability across all 41 existing test cases without modifying tests.

---

> [!IMPORTANT]
> **STRICT STOP CONDITION OBSERVED:**
> All 10 deliverables have been authored and placed inside `evaluation_reports/`.
> 
> No source code has been altered, no benchmarks have been executed, no repositories have been indexed, no databases have been created, and no tests have been run.
> 
> Awaiting explicit user approval before proceeding with any checkpoint.

