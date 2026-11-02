# CodeMind AI — Root-Cause Analysis and P0 Corrections (Run 1)

## 1. Audit Review & Inputs Used

- **`evaluation_reports/audit_v2/` Availability**: Inspected. Directory does **not** exist in the workspace. Documented as unavailable.
- **Previous Evaluation Dossiers Reviewed**:
  - `evaluation_reports/retrieval_and_answer_quality_audit.md`
  - `evaluation_reports/pre_execution_verification_dossier.md`
  - `evaluation_reports/auth04_expertdecision_evaluation.md`
  - `evaluation_reports/auth04_rewardpoints_evaluation.md`
  - `evaluation_reports/final_codemind_improvement_roadmap.md`
- **Key Observation on Previous Claims**: Previous audit reports cited high subjective scores (e.g., 96% retrieval precision), but these reflected prompt-time synthetic matching rather than strict evaluation against physical repository source files. Run 1 established a fresh, empirical baseline.

---

## 2. Fresh Baseline Findings

A fresh baseline evaluation was executed on 20 questions across two repositories on `codemind_eval_db`:
- **Repository A (ID 46)**: `expertdecision` (10 questions)
- **Repository B (ID 47)**: `RewardPoints Transfer` (10 questions)

| Metric | Measured Fresh Baseline | Primary Defect Identified |
| :--- | :---: | :--- |
| **Retrieval Precision** | **37.79%** (65 / 172) | Irrelevant test files and docs outranking core implementation. |
| **Retrieval Recall** | **47.83%** (22 / 46) | Expected primary files omitted from top-8 retrieved chunks. |
| **Relevant Source Coverage** | **38.89%** (7 / 18) | Only 7 out of 18 valid questions retrieved all expected files. |
| **Wrong-Repository Rate** | **0.00%** (0 / 172) | Repository isolation is strictly enforced at DB level. |
| **Duplicate Context Rate** | **0.00%** (0 / 172) | Chunk span deduplication is functional. |
| **Average Latency** | **811.23 ms** | pgvector cosine search and keyword filtering operate cleanly. |

---

## 3. Verified Failure-to-Fix Mapping

| # | Observed Failure | Verified Root Cause | Affected Component | Implemented Fix | Validation |
|---|---|---|---|---|---|
| **F-01** | `ED-01`: `backend/app/main.py` entrypoint missed; `frontend/app.py` and `Prd.md` retrieved instead. | Entrypoint queries ("application entrypoint", "FastAPI initialized") were not recognized as entrypoint intents; `main.py` was not prioritized. | `_detect_explicit_file_paths`, `retrieve()` | Added entrypoint pattern detection; explicitly injected and boosted (`+0.45`) `main.py`, `app.py`, `main.tsx`. | `ED-01` retrieves `backend/app/main.py` as top chunk. |
| **F-02** | `ED-01`, `RP-12`: Documentation files (`Prd.md`, `README.md`, `alembic/README`) pollute code queries. | `is_code_query` regex was narrow; documentation penalty (`* 0.60`) was bypassed when query terms didn't match the specific wordlist. | `retrieve()` scoring loop | Expanded code query detection to all technical queries; applied universal doc file penalty (`* 0.20`) unless query asks for documentation. | `Prd.md` score drops below implementation code. |
| **F-03** | `RP-10`: "on the frontend" query retrieves 7 backend security files and only 1 frontend file. | Engine lacked layer/architectural scope awareness; did not boost `frontend/` when query explicitly targeted the frontend. | `retrieve()` channel scores | Added directional layer intent detection; applied `+0.35` boost to `frontend/` files and `* 0.40` penalty to `backend/` files. | `RP-10` retrieves `frontend/src/services/api.ts` and `AuthContext.tsx`. |
| **F-04** | `RP-04`, `RP-11`: Test files (`backend/tests/test_transfers.py`) constituted 50% of retrieved chunks. | `is_test_or_upload` penalty was only applied inside `elif is_code_query:`. In `RP-11`, `is_code_query` was False, bypassing the penalty. | `retrieve()` scoring loop | Applied universal test-file penalty (`* 0.20`) to all technical queries unless `is_test_query` is True. | Test files penalized; production `transfer_service.py` ranks #1. |
| **F-05** | `RP-12`: `.env.example` not retrieved; `package.json` and `README.md` outranked it. | Manifest/config query regex did not prioritize `.env` or `.env.example`; keyword search missed exact env var definition. | `_detect_explicit_file_paths`, `_retrieve_exact_matches` | Added explicit regex for `.env`, `.env.example`, `.env.local` and exact symbol extraction for uppercase config keys (`VITE_*`). | `RP-12` retrieves `.env.example` and `api.ts`. |
| **F-06** | `ED-05`: Direct caller discovery (`get_db`) missed router callers due to directory stem flood. | `meaningful_stems` included `"backend"`, causing `IndexedFile.path.ilike("%backend%")` to match hundreds of files and push out specific routers. | `_retrieve_exact_matches` | Added `DIR_STEM_EXCLUSIONS = {"backend", "frontend", "src", "app", ...}` to prevent directory flooding. | `ED-05` searches specific domain files. |
| **F-07** | `RP-04`: Cross-layer execution flow (UI -> API -> DB) was 100% backend; 0 frontend chunks. | Single backend file took 4 slots; no layer balancing for fullstack flows. | `retrieve()` deduplication | For fullstack flows, interleaved top frontend and backend candidates to guarantee balanced cross-layer representation. | `RP-04` relevant count doubled from 2 to 4 chunks. |

---

## 4. Unresolved Issues & Future Scope

1. **Physical vs. Hypothetical Ground Truth Discrepancies**:
   - In `expertdecision`: `session.py` does not physically exist (it is `connection.py`); `config.py` does not exist (it is `settings.py`).
   - In `RewardPoints Transfer`: `user.py` does not exist (it is `student.py`); `point_service.py` does not exist (it is `transfer_service.py`).
   - When users ask questions containing hypothetical file names, CodeMind correctly retrieves the closest physical equivalent, but strict evaluation against hypothetical names marks them missing.
2. **Context Window Token Budgeting for Monorepo Execution Traces**:
   - Complex 5-file execution traces (UI -> Hook -> Router -> Service -> DB) require pulling at least 2 chunks per file (10 chunks total). Hierarchical chunk summarization (Roadmap IMP-09) is recommended for Run 2.
