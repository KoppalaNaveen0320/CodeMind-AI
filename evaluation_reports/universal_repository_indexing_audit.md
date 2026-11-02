# Universal Repository Indexing & Understanding Audit

**Target System:** CodeMind AI Ingestion, Parsing, and Knowledge Graph Pipeline  
**Source Files Audited (Read-Only):**
- `backend/app/services/indexing_service.py`
- `backend/app/parsing/extractor.py`
- `backend/app/parsing/chunker.py`
- `backend/app/graph/builder.py`
- `backend/app/graph/service.py`
- `backend/app/ingestion/change_detector.py`
- `backend/app/models/` (`repository.py`, `indexed_file.py`, `code_chunk.py`, `code_symbol.py`, `knowledge_graph.py`)

---

## 1. Repository Discovery & Onboarding Pipeline

### A. Root Identification & Metadata Assignment
- **Mechanism:** In `backend/app/services/indexing_service.py:350–450`, repositories are either cloned via GitHub (`GitHubService.clone_repository`) or resolved locally via `source_folder`.
- **Repository ID Assignment:** Generated sequentially via PostgreSQL `repositories.id` primary key (`SERIAL`/`INTEGER`).
- **Duplicate Prevention:** Handled in `indexing_service.py:146–153`. When an indexing job is requested, `IndexingJob.status.in_(["QUEUED", "CLONING", "PARSING", "INDEXING"])` is queried. If an active job exists, duplicate job creation is rejected.
- **Cross-Process Concurrency Safety:** Line 395 acquires a PostgreSQL advisory lock (`SELECT pg_try_advisory_lock(:lock_id)`) pinned to `repository_id`, preventing race conditions across multiple Uvicorn workers.
- **Safe Reindexing & Stale Recovery:** `IndexingService.recover_stale_indexing_jobs()` (lines 93–138) checks for jobs interrupted by server restart and resets them to `FAILED` without wiping the last known good index (`repo.status = "ready"` if `repo.files_count > 0`).

### B. Identified Weaknesses in Discovery
1. **Moved or Renamed Local Directories:** If a local repository root is moved on disk, `Repository.clone_url` or local path mappings become dangling pointers. CodeMind lacks an automated path-healing mechanism.
2. **Nested Repositories:** Submodules or nested git directories inside `vendor/` or sub-folders are skipped by `IGNORED_DIRECTORIES: {".git"}`. Nested repositories without separate git roots are indexed as flat sub-directories.
3. **Empty Repositories:** Line 125 marks repositories with 0 files as `failed` or `pending` rather than `empty_ready`.

---

## 2. File Discovery & Filtering Architecture

### A. Exclusion Rules (Verified in `indexing_service.py:35–61`)
- **Ignored Directories:** `.git`, `node_modules`, `venv`, `.venv`, `env`, `dist`, `build`, `target`, `__pycache__`, `.pytest_cache`, `.vscode`, `.idea`.
- **Ignored Extensions:** Binaries (`.exe`, `.dll`, `.so`), images/media (`.png`, `.jpg`, `.mp4`), archives (`.zip`, `.tar`), bytecode (`.pyc`, `.class`), models/weights (`.pth`, `.pt`, `.onnx`, `.safetensors`), and database files (`.db`, `.sqlite`).
- **Ignored Manifests/Secrets:** `.env`, `.env.local`, `id_rsa`, `credentials.json`, `package-lock.json`, `poetry.lock`.

### B. Content Inspection & Encoding Resilience (`indexing_service.py:171–248`)
- **Max File Size:** Enforced at `settings.INDEXING_MAX_FILE_SIZE_BYTES` (default 1 MB). Files exceeding limit are skipped with reason `"oversized_file"`.
- **Encoding Cascade:** Detects BOMs (`utf-32`, `utf-16`, `utf-8-sig`). Falls back to `utf-8`, then heuristic `utf-16` without BOM, then `latin-1`.
- **Binary Content Detection:** Rejects files where control characters ($\text{ord}(c) < 32$ excluding `\t\n\r`) exceed 15% of the first 4,096 bytes.
- **PostgreSQL NUL Byte Resilience:** Lines 71 & 245 sanitize `0x00` characters to `\uFFFD` (Unicode Replacement Character) to prevent `psycopg2.errors.DataException: unsupported Unicode escape sequence`.

### C. Priority Ranking System (`indexing_service.py:251–300`)
To prevent large multilingual documentation trees (e.g. `docs/en`, `docs/zh`) from starving core application code:
- **Priority 0:** Manifests (`pyproject.toml`, `package.json`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`).
- **Priority 1:** Core application code (`src/`, `app/`, `backend/`, `core/`, `api/`).
- **Priority 2:** Test suites (`tests/`, `spec/`, `e2e/`).
- **Priority 3:** Examples and demos (`docs_src/`, `examples/`).
- **Priority 4–6:** Documentation (`docs/en/`, `docs/`).

---

## 3. Multi-Language Parsing & Structural Understanding Audit

CodeMind's language support is implemented in `backend/app/parsing/extractor.py`. A rigorous static audit reveals a **sharp division between Tier-1 languages and Tier-2 languages**:

| Language | File Discovery | Parsing Engine | Symbol Extraction | Import Extraction | Call Hierarchy | Citation Accuracy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Python** | Full (`.py`) | Python AST + Tree-sitter | Functions, classes, methods, docstrings | Full runtime vs `TYPE_CHECKING` | AST-verified callers & line sites | Exact line bounds |
| **JavaScript / JSX** | Full (`.js`, `.jsx`, `.mjs`) | Tree-sitter JS | Functions, classes, methods | Basic imports | Partial call sites | Exact line bounds |
| **TypeScript / TSX** | Full (`.ts`, `.tsx`) | Tree-sitter TS | Functions, classes, interfaces, methods | Basic imports | Partial call sites | Exact line bounds |
| **Dart** | Full (`.dart`) | Regex Pattern Matching | Class & method regex | **None** | **None** | Approximate |
| **Java / C#** | Full (`.java`, `.cs`) | Regex Pattern Matching | Class & method regex | **None** | **None** | Approximate |
| **C / C++** | Full (`.c`, `.cpp`, `.h`) | Regex Pattern Matching | Class & function regex | **None** | **None** | Approximate |
| **Go / Rust** | Full (`.go`, `.rs`) | Regex Pattern Matching | Struct & function regex | **None** | **None** | Approximate |
| **SQL** | Full (`.sql`) | Plain Text Chunking | **None** (Chunks only) | **None** | **None** | Chunk-level |
| **HTML / CSS** | Full (`.html`, `.css`) | Plain Text Chunking | **None** (Chunks only) | **None** | **None** | Chunk-level |
| **Docker / YAML** | Full (`Dockerfile`, `.yml`) | Plain Text Chunking | **None** (Priority 0 chunk) | **None** | **None** | Chunk-level |

### Key Architectural Finding:
- **Python, JS, and TS** receive deep AST/Tree-sitter structural parsing.
- **Dart, Java, C++, Go, and Rust** are currently parsed via regex heuristics in `_extract_generic_symbols` (`extractor.py:270–340`), which extract symbol names but **do not build graph edges for calls, inheritance, or imports**.
- **SQL, Dockerfile, and Configs** are indexed as raw semantic chunks without AST symbol nodes.

---

## 4. Symbol & Dependency Understanding (`graph/builder.py` & `graph/service.py`)

### A. Graph Representation
- **GraphNode:** Represents a file or symbol (`node_type`: `FILE`, `CLASS`, `FUNCTION`, `INTERFACE`).
- **GraphEdge:** Represents relationships (`edge_type`: `DEFINES`, `CALLS`, `IMPORTS`, `TYPE_CHECKING_IMPORTS`, `LOCAL_IMPORTS`).

### B. Distinction of Relationships
1. **Direct Callers:** Verified in Python via `ast.Call` nodes inside function bodies, tracking `caller_name`, `callee_name`, and exact `line_number`.
2. **Dependency Injection References:** FastAPI `Depends(func)` references appear as call nodes inside function signatures, requiring distinction from standard runtime body invocations.
3. **Imported Symbols:** Categorized in `KnowledgeGraphService.classify_imports_and_cycles()` into:
   - `RUNTIME_CYCLE`
   - `TYPE_CHECKING` (imports under `if TYPE_CHECKING:`)
   - `FORWARD_REF` (string literal type annotations like `"APIRoute"`)
   - `LOCAL` (imports inside function bodies)
   - `NORMAL_DEPENDENCY`

---

## 5. Repository Isolation Verification

### A. Database-Level Isolation
- `code_chunks.repository_id`: Every chunk is explicitly associated with its parent repository.
- `code_symbols.repository_id`: Every symbol is scoped to its repository.
- `graph_nodes.repository_id` and `graph_edges.repository_id`: Every graph entity is partitioned by repository.

### B. Retrieval Query Isolation
In `backend/app/retrieval/hybrid_engine.py`:
- `db.query(CodeChunk).filter(CodeChunk.repository_id == repository_id, ...)` (lines 142, 154, 194).
- Vector cosine similarity queries include `WHERE code_chunks.repository_id = :repo_id`.
- Chunks from repository A cannot physically be retrieved for a query targeting repository B.

### C. Conversation Context Isolation
In `backend/app/services/assistant_service.py:1185–1205`:
- When answering a question with a given `repository_id`, CodeMind checks `conv.repository_id == repository_id`.
- If a user switches repositories in the UI, CodeMind refuses to mix conversations and forces creation of a fresh, isolated conversation session for the new repository.

---

## 6. Concrete Root Causes of Failure on Newly Cloned Repositories

1. **Non-Python / Non-JS Repositories Lack Call Hierarchies:** Because `extractor.py` relies on Tree-sitter exclusively for Python and JS/TS, questions about call hierarchies in Go, Java, or Rust repositories cannot trace genuine callers and fall back to keyword co-occurrence.
2. **Cross-File Route-to-Frontend Disconnect:** While backend routes (`@app.get("/api/...")`) and frontend API clients (`axios.get("/api/...")`) are indexed, CodeMind does not currently build synthetic `HTTP_CALLS` graph edges linking frontend API call expressions to backend route handlers.
3. **Missing Config/Environment Variable Symbol Extraction:** Environment variables (`os.getenv("SECRET_KEY")` or `process.env.VITE_API_URL`) are not registered as `CodeSymbol` entities, preventing automated cross-file configuration tracing.

