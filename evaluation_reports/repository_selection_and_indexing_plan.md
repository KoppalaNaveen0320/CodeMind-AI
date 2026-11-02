# Repository Selection & Indexing Plan

**Evaluation Objective:** Validate CodeMind AI's universal repository intelligence across three distinct architectures without manual tuning.

---

## 1. Selected Repositories & Architectural Roles

| Candidate | Target Repository | Local Path on Disk | Architectural Characteristics & Purpose | Current Index Status in CodeMind |
| :--- | :--- | :--- | :--- | :--- |
| **Candidate A** | **expertdecision** | `C:\Users\koppa\OneDrive\Documents\Projects\expertdecision` | **Large Python Backend:** Multi-layered enterprise architecture (`api/`, `services/`, `repositories/`, `models/`, `dependencies/`, `schemas/`), complex dependency graph, SQLAlchemy ORM, Alembic migrations, Redis caching. | **Fully Indexed** (Repo ID `46`, 206 files, 1,489 chunks, 1,734 symbols) |
| **Candidate B** | **RewardPoints Transfer** | `C:\Users\koppa\OneDrive\Documents\Projects\RewardPoints Transfer` | **TypeScript / React 18/19 + FastAPI:** Fullstack with typed frontend client (`frontend/src/services/api.ts`, `frontend/src/types/`, `frontend/src/pages/`, `frontend/src/components/`) and FastAPI backend (`backend/app/api/`, `backend/app/models/`). | **NOT INDEXED** (Exists on disk; requires explicit indexing plan) |
| **Candidate C** | **TokenPool** | `C:\Users\koppa\OneDrive\Documents\Projects\TokenPool` | **Mixed-Language System:** Python FastAPI backend, HTML/JS/CSS frontend, Alembic SQL migrations (`alembic/versions/`), Nginx reverse proxy configuration (`nginx/`), Docker Compose (`docker-compose.production.yml`), environment templates, and deployment guides. | **Fully Indexed** (Repo ID `45`, 89 files, 840 chunks, 940 symbols) |

---

## 2. Index Consistency Verification for Existing Repositories

An independent read-only audit was performed comparing PostgreSQL database records against actual source files on disk:

### A. Candidate A: `expertdecision` (Repo ID `46`)
- **Database Records:** `indexed_files` = 206 rows, `code_chunks` = 1,489 rows, `code_symbols` = 1,734 rows. Status: `ready`.
- **Disk Inventory:** 225 total files (excluding `.git`, `node_modules`, `venv`, `__pycache__`).
- **Audit Findings:**
  - **Files in DB but missing on disk:** **0 files** (100% of indexed database files exist on disk).
  - **Files on disk not in DB:** 19 files, consisting entirely of binary/database artifacts correctly filtered by `IGNORED_EXTENSIONS`: SQLite databases (`edrp.db`, `database.db`), log files (`backend.log`), and raw export dumps (`project_structure.txt`).
- **Index Health:** **100% Consistent and Valid.** No reindexing required.

### B. Candidate C: `TokenPool` (Repo ID `45`)
- **Database Records:** `indexed_files` = 89 rows, `code_chunks` = 840 rows, `code_symbols` = 940 rows. Status: `ready`.
- **Disk Inventory:** 157 total files (excluding `.git`, `node_modules`, `venv`, `__pycache__`).
- **Audit Findings:**
  - **Files in DB but missing on disk:** **0 files** (100% of indexed database files exist on disk).
  - **Files on disk not in DB:** 68 files, consisting entirely of UI screenshot assets (`landing_page.png`, `chat_page.png`, `orders_page.png`, `wallet_page.png`), large HTML dumps (`full-ui.html`), and test artifact caches filtered by standard exclusion rules.
- **Index Health:** **100% Consistent and Valid.** No reindexing required.

---

## 3. Indexing Plan for Candidate B (`RewardPoints Transfer`)

`RewardPoints Transfer` is not currently in CodeMind's database. To evaluate it under identical conditions without manual tweaks, the following controlled indexing plan is established:

### A. Inclusion & Exclusion Scoping
- **Inclusion Scope:**
  - Frontend: `frontend/src/**/*.{ts,tsx,js,jsx,css,html}`, `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`.
  - Backend: `backend/app/**/*.{py}`, `backend/alembic/**/*.{py}`, `backend/requirements.txt`, `backend/alembic.ini`.
  - Config & Deployment: `docker-compose.yml`, `README.md`.
- **Exclusion Rules (Mandatory):**
  - `frontend/node_modules/` (12,000+ third-party dependency files).
  - `backend/venv/` (Python virtual environment libraries).
  - `frontend/dist/` and `frontend/test-results/` (build artifacts).
  - `backend/campuspoints_dev.db` (binary SQLite database).
  - `.git/` and `.pytest_cache/`.
- **Expected Volume:** Approximately **88 clean source files**, generating $\sim 500\text{–}650$ semantic chunks and $\sim 600\text{–}750$ symbols.

### B. Database Operations & Safety Controls
1. **Creation:** Create 1 record in `repositories` (`name='RewardPoints-Transfer'`, `provider='local'`).
2. **Indexing:** Run standard `IndexingService.run_indexing_pipeline()` using existing 768-dimensional `nomic-embed-text` embeddings.
3. **Repository Isolation Check:** Confirm that newly assigned `repository_id` isolates all generated chunks and graph nodes from repositories 44, 45, and 46.
4. **Rollback / Abort Plan:** If an indexing failure occurs, the job status will transition to `FAILED` without affecting existing repositories, and the repository record can be cleanly removed if requested.

> [!IMPORTANT]
> **STRICT STOP:** No indexing job has been initiated. In accordance with workspace restrictions, `RewardPoints Transfer` will **NOT be indexed until explicit user approval is granted**.

